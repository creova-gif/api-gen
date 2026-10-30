"""
APIGen Schema Diff & Self-Maintaining API Engine.
Detects schema drift between two data sources or an existing OpenAPI specification and a new data source.
Categorizes changes into BREAKING vs NON-BREAKING, and can auto-patch client and server code.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from apigen.infer import FieldDef, SchemaDef, infer_from_file


class ChangeType(str, Enum):
    FIELD_ADDED = "FIELD_ADDED"
    FIELD_REMOVED = "FIELD_REMOVED"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABILITY_CHANGED = "NULLABILITY_CHANGED"
    PRIMARY_KEY_CHANGED = "PRIMARY_KEY_CHANGED"
    ENUM_VALUES_CHANGED = "ENUM_VALUES_CHANGED"


class Severity(str, Enum):
    BREAKING = "BREAKING"
    NON_BREAKING = "NON_BREAKING"


@dataclass
class FieldChange:
    field_name: str
    change_type: ChangeType
    severity: Severity
    description: str
    old_value: Any = None
    new_value: Any = None
    migration_advice: str = ""


@dataclass
class SchemaDiff:
    old_resource: str
    new_resource: str
    changes: List[FieldChange] = field(default_factory=list)
    has_breaking_changes: bool = False

    @property
    def breaking_changes(self) -> List[FieldChange]:
        return [c for c in self.changes if c.severity == Severity.BREAKING]

    @property
    def non_breaking_changes(self) -> List[FieldChange]:
        return [c for c in self.changes if c.severity == Severity.NON_BREAKING]


def diff_schemas(old_schema: SchemaDef, new_schema: SchemaDef) -> SchemaDiff:
    """
    Computes semantic differences between two SchemaDef objects.
    Identifies breaking changes that impact API consumers.
    """
    changes: List[FieldChange] = []
    old_fields: Dict[str, FieldDef] = {f.name: f for f in old_schema.fields}
    new_fields: Dict[str, FieldDef] = {f.name: f for f in new_schema.fields}

    # 1. Primary Key Changes
    if old_schema.primary_key != new_schema.primary_key:
        changes.append(
            FieldChange(
                field_name=new_schema.primary_key or "pk",
                change_type=ChangeType.PRIMARY_KEY_CHANGED,
                severity=Severity.BREAKING,
                description=f"Primary key changed from '{old_schema.primary_key}' to '{new_schema.primary_key}'",
                old_value=old_schema.primary_key,
                new_value=new_schema.primary_key,
                migration_advice="Consumers fetching by ID must update path parameters to use the new primary key.",
            )
        )

    # 2. Removed Fields (BREAKING: consumer expects them in response payload)
    for name, old_f in old_fields.items():
        if name not in new_fields:
            changes.append(
                FieldChange(
                    field_name=name,
                    change_type=ChangeType.FIELD_REMOVED,
                    severity=Severity.BREAKING,
                    description=f"Field '{name}' ({old_f.python_type}) was removed",
                    old_value=old_f.python_type,
                    new_value=None,
                    migration_advice=f"Deprecate field '{name}'. Consumers reading this field will fail or receive null.",
                )
            )

    # 3. Added Fields (NON-BREAKING if nullable or has default, POTENTIALLY BREAKING on POST if non-nullable)
    for name, new_f in new_fields.items():
        if name not in old_fields:
            sev = Severity.BREAKING if not new_f.nullable else Severity.NON_BREAKING
            advice = (
                f"Field '{name}' is non-nullable. Client POST requests will fail validation (422) unless provided."
                if sev == Severity.BREAKING
                else f"New optional field '{name}'. Existing clients can safely ignore."
            )
            changes.append(
                FieldChange(
                    field_name=name,
                    change_type=ChangeType.FIELD_ADDED,
                    severity=sev,
                    description=f"Field '{name}' ({new_f.python_type}) added"
                    + (" [Required]" if sev == Severity.BREAKING else " [Optional]"),
                    old_value=None,
                    new_value=new_f.python_type,
                    migration_advice=advice,
                )
            )

    # 4. Modified Fields (Type or Nullability)
    for name in old_fields.keys() & new_fields.keys():
        old_f = old_fields[name]
        new_f = new_fields[name]

        # Type change
        if old_f.python_type != new_f.python_type:
            # e.g., int -> float might be non-breaking in some cases, but generally type change is breaking
            changes.append(
                FieldChange(
                    field_name=name,
                    change_type=ChangeType.TYPE_CHANGED,
                    severity=Severity.BREAKING,
                    description=f"Field '{name}' type changed from '{old_f.python_type}' to '{new_f.python_type}'",
                    old_value=old_f.python_type,
                    new_value=new_f.python_type,
                    migration_advice=f"Update client serialization and data models for '{name}'.",
                )
            )

        # Nullability change
        if old_f.nullable != new_f.nullable:
            # Previously nullable, now non-nullable = BREAKING for writers
            # Previously non-nullable, now nullable = BREAKING for readers expecting non-null
            changes.append(
                FieldChange(
                    field_name=name,
                    change_type=ChangeType.NULLABILITY_CHANGED,
                    severity=Severity.BREAKING,
                    description=f"Field '{name}' nullability changed: nullable={old_f.nullable} -> nullable={new_f.nullable}",
                    old_value=old_f.nullable,
                    new_value=new_f.nullable,
                    migration_advice="Verify client null checks and payload validation rules.",
                )
            )

        # Enum values changed
        if old_f.enum_values != new_f.enum_values and (old_f.enum_values or new_f.enum_values):
            old_set = set(old_f.enum_values or [])
            new_set = set(new_f.enum_values or [])
            removed_enums = old_set - new_set
            added_enums = new_set - old_set
            sev = Severity.BREAKING if removed_enums else Severity.NON_BREAKING
            changes.append(
                FieldChange(
                    field_name=name,
                    change_type=ChangeType.ENUM_VALUES_CHANGED,
                    severity=sev,
                    description=f"Enum values for '{name}' changed. Added: {list(added_enums)}, Removed: {list(removed_enums)}",
                    old_value=old_f.enum_values,
                    new_value=new_f.enum_values,
                    migration_advice="Update client enum mappings."
                    if removed_enums
                    else "Non-breaking enum expansion.",
                )
            )

    has_breaking = any(c.severity == Severity.BREAKING for c in changes)

    return SchemaDiff(
        old_resource=old_schema.resource_name,
        new_resource=new_schema.resource_name,
        changes=changes,
        has_breaking_changes=has_breaking,
    )


def diff_files(
    old_file: Union[str, Path], new_file: Union[str, Path], resource_name: Optional[str] = None
) -> SchemaDiff:
    """Diffs two data files directly (CSV, JSON, or SQLite)."""
    old_schema = infer_from_file(old_file, resource_name=resource_name)
    new_schema = infer_from_file(new_file, resource_name=resource_name)
    return diff_schemas(old_schema, new_schema)

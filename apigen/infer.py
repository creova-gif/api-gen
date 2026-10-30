"""
APIGen Schema Inference Engine.
Infers field types, nullability, primary keys, and enums from CSV, JSON, and SQLite sources.
"""

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class FieldDef:
    name: str
    python_type: str  # 'int', 'float', 'bool', 'str', 'datetime', 'date'
    openapi_type: str  # 'integer', 'number', 'boolean', 'string'
    openapi_format: Optional[str] = None
    nullable: bool = False
    is_primary_key: bool = False
    is_filter_candidate: bool = False
    example: Any = None
    enum_values: Optional[List[str]] = None
    description: str = ""


@dataclass
class SchemaDef:
    resource_name: str
    plural_name: str
    fields: List[FieldDef] = field(default_factory=list)
    primary_key: Optional[str] = None
    sample_records: List[Dict[str, Any]] = field(default_factory=list)


def _sanitize_field_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"
    return cleaned.lower() or "field"


def _infer_value_type(val: Any) -> Tuple[str, str, Optional[str]]:
    """Returns (python_type, openapi_type, openapi_format)."""
    if val is None:
        return ("str", "string", None)

    if isinstance(val, bool):
        return ("bool", "boolean", None)
    if isinstance(val, int):
        return ("int", "integer", "int64")
    if isinstance(val, float):
        return ("float", "number", "float")

    s = str(val).strip()
    if s.lower() in ("true", "false", "yes", "no"):
        return ("bool", "boolean", None)

    # Integer check
    if re.fullmatch(r"[-+]?\d+", s):
        return ("int", "integer", "int64")

    # Float check
    if re.fullmatch(r"[-+]?\d*\.\d+", s):
        return ("float", "number", "float")

    # ISO Datetime check
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", s):
        return ("datetime", "string", "date-time")

    # Date check
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return ("date", "string", "date")

    # Email check
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        return ("str", "string", "email")

    # UUID check
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s):
        return ("str", "string", "uuid")

    return ("str", "string", None)


def infer_schema_from_records(
    records: List[Dict[str, Any]], resource_name: str = "item"
) -> SchemaDef:
    if not records:
        raise ValueError("Cannot infer schema from empty records")

    plural_name = f"{resource_name}s" if not resource_name.endswith("s") else resource_name
    field_stats: Dict[str, Dict[str, Any]] = {}

    for row in records:
        for k, v in row.items():
            sanitized_key = _sanitize_field_name(k)
            if sanitized_key not in field_stats:
                field_stats[sanitized_key] = {
                    "original_name": k,
                    "types": set(),
                    "non_null_count": 0,
                    "values": set(),
                    "example": None,
                }
            if v is not None and str(v).strip() != "":
                py_t, oapi_t, oapi_f = _infer_value_type(v)
                field_stats[sanitized_key]["types"].add((py_t, oapi_t, oapi_f))
                field_stats[sanitized_key]["non_null_count"] += 1
                if len(field_stats[sanitized_key]["values"]) < 50:
                    field_stats[sanitized_key]["values"].add(str(v).strip())
                if field_stats[sanitized_key]["example"] is None:
                    field_stats[sanitized_key]["example"] = v

    total_rows = len(records)
    fields: List[FieldDef] = []
    pk_candidate: Optional[str] = None

    for col_name, stats in field_stats.items():
        types = stats["types"]
        nullable = stats["non_null_count"] < total_rows

        if ("float", "number", "float") in types:
            py_type, oapi_type, oapi_fmt = "float", "number", "float"
        elif ("int", "integer", "int64") in types and not any(t[0] in ("str", "float") for t in types):
            py_type, oapi_type, oapi_fmt = "int", "integer", "int64"
        elif ("bool", "boolean", None) in types and len(types) == 1:
            py_type, oapi_type, oapi_fmt = "bool", "boolean", None
        elif any(t[2] == "date-time" for t in types) and not any(t[0] in ("int", "float") for t in types):
            py_type, oapi_type, oapi_fmt = "datetime", "string", "date-time"
        elif any(t[2] == "date" for t in types) and not any(t[0] in ("int", "float") for t in types):
            py_type, oapi_type, oapi_fmt = "date", "string", "date"
        else:
            py_type, oapi_type, oapi_fmt = "str", "string", None
            if len(types) == 1:
                only_fmt = next(iter(types))[2]
                if only_fmt in ("email", "uuid"):
                    oapi_fmt = only_fmt

        # Detect Primary Key
        is_pk = False
        if col_name in ("id", f"{resource_name.lower()}_id", "uuid", "pk"):
            is_pk = True
            pk_candidate = col_name

        # Detect Enums: small set of distinct values relative to dataset
        enum_values = None
        unique_vals = list(stats["values"])
        if py_type == "str" and 1 < len(unique_vals) <= 6 and total_rows >= 10:
            enum_values = sorted(unique_vals)

        # Detect filter candidate
        is_filter = is_pk or enum_values is not None or "status" in col_name or "category" in col_name or "type" in col_name

        fields.append(
            FieldDef(
                name=col_name,
                python_type=py_type,
                openapi_type=oapi_type,
                openapi_format=oapi_fmt,
                nullable=nullable,
                is_primary_key=is_pk,
                is_filter_candidate=is_filter,
                example=stats["example"],
                enum_values=enum_values,
                description=f"{col_name.replace('_', ' ').capitalize()} field",
            )
        )

    # If no explicit PK found, pick the first unique or first column
    if not pk_candidate:
        for f in fields:
            if f.name.endswith("_id") or f.name == "id":
                f.is_primary_key = True
                pk_candidate = f.name
                break
        if not pk_candidate and fields:
            fields[0].is_primary_key = True
            pk_candidate = fields[0].name

    return SchemaDef(
        resource_name=resource_name,
        plural_name=plural_name,
        fields=fields,
        primary_key=pk_candidate,
        sample_records=records[:100],  # keep first 100 as seed
    )


def infer_from_file(file_path: Union[str, Path], resource_name: Optional[str] = None) -> SchemaDef:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    res_name = resource_name or path.stem.rstrip("s").lower()

    if path.suffix.lower() == ".csv":
        with open(path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            records = [row for row in reader]
        return infer_schema_from_records(records, resource_name=res_name)

    elif path.suffix.lower() == ".json":
        with open(path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                # Check if it has a list inside
                for k, v in data.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        data = v
                        res_name = resource_name or k.rstrip("s").lower()
                        break
                else:
                    data = [data]
            if not isinstance(data, list):
                raise ValueError("JSON data must be a list of objects or contain one")
        return infer_schema_from_records(data, resource_name=res_name)

    elif path.suffix.lower() in (".sqlite", ".db", ".sqlite3"):
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [r[0] for r in cur.fetchall()]
        if not tables:
            raise ValueError(f"No tables found in SQLite database {path}")
        target_table = tables[0]
        cur.execute(f"SELECT * FROM {target_table} LIMIT 100")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return infer_schema_from_records(rows, resource_name=resource_name or target_table.rstrip("s").lower())

    else:
        raise ValueError(f"Unsupported file extension: {path.suffix}")

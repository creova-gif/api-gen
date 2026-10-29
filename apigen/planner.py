"""
APIGen Intent & API Design Planner.
Translates user natural language instructions into concrete API endpoint specifications.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from apigen.infer import SchemaDef


@dataclass
class APIPlan:
    title: str
    version: str
    description: str
    schema: SchemaDef
    allow_create: bool = True
    allow_read: bool = True
    allow_update: bool = True
    allow_delete: bool = True
    search_enabled: bool = True
    pagination_enabled: bool = True
    filter_fields: List[str] = field(default_factory=list)
    auth_enabled: bool = False
    mock_count: int = 0
    rate_limiting_enabled: bool = False


def create_api_plan(
    schema: SchemaDef,
    intent: Optional[str] = None,
    auth_enabled: Optional[bool] = None,
    mock_count: int = 0,
) -> APIPlan:
    plan = APIPlan(
        title=f"{schema.resource_name.capitalize()} API",
        version="v1.0.0",
        description=f"Auto-generated high-performance RESTful API for {schema.plural_name}.",
        schema=schema,
        filter_fields=[f.name for f in schema.fields if f.is_filter_candidate and not f.is_primary_key],
        mock_count=mock_count,
    )

    if auth_enabled is not None:
        plan.auth_enabled = auth_enabled

    if not intent:
        return plan

    lower_intent = intent.lower()

    # Read-only check
    if "read-only" in lower_intent or "read only" in lower_intent or "query only" in lower_intent:
        plan.allow_create = False
        plan.allow_update = False
        plan.allow_delete = False

    # Specific operations
    if "no delete" in lower_intent or "cannot delete" in lower_intent or "disable delete" in lower_intent:
        plan.allow_delete = False

    if "no update" in lower_intent or "immutable" in lower_intent:
        plan.allow_update = False

    if "auth" in lower_intent or "secure" in lower_intent or "token" in lower_intent or "api key" in lower_intent:
        plan.auth_enabled = True

    # Check for specific filter intents
    for f in schema.fields:
        if f.name in lower_intent:
            if f.name not in plan.filter_fields and not f.is_primary_key:
                plan.filter_fields.append(f.name)

    return plan

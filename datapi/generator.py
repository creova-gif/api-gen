"""
Datapi Code & Specification Generator.
Generates OpenAPI 3.1, FastAPI app with Pydantic models, Dockerfile, Terraform for Cloud Run, and Docs.
"""

import base64
from datetime import date, datetime, timedelta
from decimal import Decimal
import http
import json
import pprint
import random
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from datapi.planner import APIPlan
from datapi.infer import FieldDef, SchemaDef
from datapi.sdk_generator import generate_typescript_sdk
from datapi.python_sdk_generator import generate_python_sdk


def _is_decimal_field(field: FieldDef) -> bool:
    if getattr(field, "openapi_format", None) == "decimal":
        return True
    py_t = str(getattr(field, "python_type", "")).lower()
    if py_t in ("decimal", "decimal.decimal"):
        return True
    name_lower = getattr(field, "name", "").lower()
    if any(kw in name_lower for kw in ("price", "amount", "balance", "currency")):
        return True
    return False


def _py_type_annotation(field: FieldDef) -> str:
    if _is_decimal_field(field):
        base = "Decimal"
    else:
        mapping = {
            "int": "int",
            "float": "float",
            "bool": "bool",
            "str": "str",
            "datetime": "datetime",
            "date": "date",
            "decimal": "Decimal",
            "Decimal": "Decimal",
        }
        base = mapping.get(field.python_type, "str")
    if field.nullable:
        return f"Optional[{base}] = None"
    return base


def _py_type_annotation_optional(field: FieldDef) -> str:
    if _is_decimal_field(field):
        base = "Decimal"
    else:
        mapping = {
            "int": "int",
            "float": "float",
            "bool": "bool",
            "str": "str",
            "datetime": "datetime",
            "date": "date",
            "decimal": "Decimal",
            "Decimal": "Decimal",
        }
        base = mapping.get(field.python_type, "str")
    return f"Optional[{base}] = None"


def _generate_synthetic_record(schema: SchemaDef, idx: int) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for f in schema.fields:
        if f.openapi_format == "uuid":
            row[f.name] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{schema.resource_name}/{f.name}/{idx}"))
        elif f.is_primary_key:
            row[f.name] = idx if f.python_type == "int" else f"ID_{idx:04d}"
        elif f.enum_values:
            row[f.name] = random.choice(f.enum_values)
        elif f.openapi_format == "email":
            row[f.name] = f"user_{idx}@example.com"
        elif f.openapi_format == "date":
            row[f.name] = (date.today() - timedelta(days=idx * 3)).isoformat()
        elif f.openapi_format == "date-time":
            row[f.name] = (datetime.now() - timedelta(hours=idx * 6)).isoformat()
        elif _is_decimal_field(f):
            row[f.name] = round(19.99 + (idx * 5.5), 2)
        elif f.python_type == "int":
            row[f.name] = idx * 10
        elif f.python_type == "float":
            row[f.name] = round(19.99 + (idx * 5.5), 2)
        elif f.python_type == "bool":
            row[f.name] = idx % 2 == 0
        else:
            row[f.name] = f"Sample {f.name.replace('_', ' ').capitalize()} {idx}"
    return row


def _build_resource_components(schema: SchemaDef) -> Dict[str, Any]:
    res_title = schema.resource_name.capitalize()
    properties: Dict[str, Any] = {}
    required_fields: List[str] = []

    for f in schema.fields:
        if _is_decimal_field(f):
            prop: Dict[str, Any] = {"type": "number", "format": "decimal", "description": f.description}
        else:
            prop: Dict[str, Any] = {"type": f.openapi_type, "description": f.description}
            if f.openapi_format:
                prop["format"] = f.openapi_format
        if f.enum_values:
            prop["enum"] = f.enum_values
        if f.example is not None:
            prop["example"] = f.example
        properties[f.name] = prop
        if not f.nullable and not f.is_primary_key:
            required_fields.append(f.name)

    return {
        f"{res_title}Base": {
            "type": "object",
            "properties": properties,
            "required": required_fields,
        },
        f"{res_title}Create": {
            "type": "object",
            "properties": {k: v for k, v in properties.items() if k != schema.primary_key},
            "required": [r for r in required_fields if r != schema.primary_key],
        },
        f"{res_title}Update": {
            "type": "object",
            "properties": {k: v for k, v in properties.items() if k != schema.primary_key},
        },
        f"{res_title}Response": {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
        },
        f"{res_title}ListResponse": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": f"#/components/schemas/{res_title}Response"},
                },
                "total": {"type": "integer"},
                "next_cursor": {"type": "string"},
                "has_more": {"type": "boolean"},
                "pagination": {"$ref": "#/components/schemas/PaginationMetadata"},
            },
            "required": ["items", "total", "has_more"],
        },
    }


def _build_resource_paths(schema: SchemaDef, plan: APIPlan) -> Dict[str, Any]:
    res_title = schema.resource_name.capitalize()
    res_path = f"/{schema.plural_name}"
    pk = schema.primary_key or "id"
    item_path = f"{res_path}/{{{pk}}}"

    list_op: Dict[str, Any] = {
        "summary": f"List {schema.plural_name}",
        "tags": [res_title],
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 20},
                "description": "Max number of items to return",
            },
            {
                "name": "offset",
                "in": "query",
                "schema": {"type": "integer", "default": 0},
                "description": "Offset for pagination",
            },
            {
                "name": "cursor",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Cursor token for keyset pagination",
            },
            {
                "name": "sort",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Sort field (prefix with '-' for descending)",
            },
        ],
        "responses": {
            "200": {
                "description": "Successful retrieval",
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{res_title}ListResponse"}
                    }
                },
            }
        },
    }

    if plan.search_enabled:
        list_op["parameters"].append(
            {
                "name": "q",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Free-text search query across string fields",
            }
        )

    for filter_f in plan.filter_fields:
        f_def = next((f for f in schema.fields if f.name == filter_f), None)
        f_type = f_def.openapi_type if f_def else "string"
        list_op["parameters"].append(
            {
                "name": filter_f,
                "in": "query",
                "schema": {"type": f_type},
                "description": f"Filter by exact {filter_f}",
            }
        )

    paths: Dict[str, Any] = {res_path: {"get": list_op}}

    if plan.allow_create:
        paths[res_path]["post"] = {
            "summary": f"Create a new {schema.resource_name}",
            "tags": [res_title],
            "parameters": [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Unique key to ensure idempotent request processing",
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{res_title}Create"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "Created successfully",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{res_title}Response"}
                        }
                    },
                }
            },
        }

    paths[item_path] = {
        "get": {
            "summary": f"Get {schema.resource_name} by ID",
            "tags": [res_title],
            "parameters": [
                {
                    "name": pk,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Item details",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{res_title}Response"}
                        }
                    },
                },
                "404": {"description": "Resource not found"},
            },
        }
    }

    if plan.allow_update:
        paths[item_path]["patch"] = {
            "summary": f"Update {schema.resource_name}",
            "tags": [res_title],
            "parameters": [
                {
                    "name": pk,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{res_title}Update"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Updated item",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{res_title}Response"}
                        }
                    },
                },
                "404": {"description": "Resource not found"},
            },
        }

    if plan.allow_delete:
        paths[item_path]["delete"] = {
            "summary": f"Delete {schema.resource_name}",
            "tags": [res_title],
            "parameters": [
                {
                    "name": pk,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "204": {"description": "Item successfully deleted"},
                "404": {"description": "Resource not found"},
            },
        }

    return paths


def generate_openapi_spec(plan: APIPlan) -> Dict[str, Any]:
    schemas = getattr(plan, "all_schemas", [plan.schema])

    components: Dict[str, Any] = {
        "schemas": {
            "PaginationMetadata": {
                "type": "object",
                "properties": {
                    "total": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "next_cursor": {"type": "string"},
                    "has_more": {"type": "boolean"},
                },
            },
            "ProblemDetails": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "integer"},
                    "detail": {},
                    "instance": {"type": "string"},
                },
                "required": ["type", "title", "status", "detail", "instance"],
            },
        }
    }

    for s in schemas:
        components["schemas"].update(_build_resource_components(s))

    if plan.auth_enabled:
        components["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "Standard API Key Authentication",
            }
        }

    spec: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": plan.title,
            "version": plan.version,
            "description": plan.description,
        },
        "servers": [{"url": "/", "description": "Local & Cloud Run base path"}],
        "paths": {},
        "components": components,
    }

    if plan.auth_enabled:
        spec["security"] = [{"ApiKeyAuth": []}]

    for s in schemas:
        spec["paths"].update(_build_resource_paths(s, plan))

    return spec


def generate_fastapi_code(plan: APIPlan) -> str:
    schema = plan.schema
    res_title = schema.resource_name.capitalize()
    pk = schema.primary_key or "id"

    # Build Pydantic model definitions
    create_fields_code = []
    response_fields_code = []
    update_fields_code = []

    for f in schema.fields:
        if f.name != pk:
            create_fields_code.append(f"    {f.name}: {_py_type_annotation(f)}")
            update_fields_code.append(f"    {f.name}: {_py_type_annotation_optional(f)}")
        response_fields_code.append(f"    {f.name}: {_py_type_annotation(f)}")

    create_fields_str = "\n".join(create_fields_code) or "    pass"
    response_fields_str = "\n".join(response_fields_code)
    update_fields_str = "\n".join(update_fields_code) or "    pass"

    # Filters arguments for list endpoint
    filter_args = []
    filter_checks = []
    for ff in plan.filter_fields:
        f_def = next((f for f in schema.fields if f.name == ff), None)
        if f_def and _is_decimal_field(f_def):
            annot = "Decimal"
        else:
            py_t = f_def.python_type if f_def else "str"
            py_t_map = {"int": "int", "float": "float", "bool": "bool", "str": "str", "datetime": "datetime", "date": "date"}
            annot = py_t_map.get(py_t, "str")
        filter_args.append(f"{ff}: Optional[{annot}] = Query(None, description='Filter by {ff}')")
        filter_checks.append(f"    if {ff} is not None:\n        results = [x for x in results if str(x.get('{ff}')) == str({ff})]")

    filter_args_str = ", ".join(filter_args)
    if filter_args_str:
        filter_args_str = ", " + filter_args_str
    filter_checks_str = "\n".join(filter_checks)

    # Seed or mock data
    records = list(schema.sample_records)
    if plan.mock_count > len(records):
        needed = plan.mock_count - len(records)
        start_idx = len(records) + 1
        for i in range(needed):
            records.append(_generate_synthetic_record(schema, start_idx + i))

    seed_json = pprint.pformat(json.loads(json.dumps(records, default=str)), indent=4, sort_dicts=False)

    # Auth block
    auth_imports = ""
    endpoint_security = ""
    if plan.auth_enabled:
        auth_imports = """
import hmac
import os
from fastapi.security import APIKeyHeader
from fastapi import Security, Depends

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key auth is enabled but the API_KEY environment variable is not set"
        )
    if not api_key or not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return api_key
"""
        endpoint_security = ", dependencies=[Depends(verify_api_key)]"

    code = f'''"""
{plan.title} - Production FastAPI Service.
Generated by Datapi Engine.
"""

import base64
from datetime import date, datetime
from decimal import Decimal
import http
import json
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
{auth_imports}

app = FastAPI(
    title="{plan.title}",
    version="{plan.version}",
    description="{plan.description}",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --- RFC 7807 Problem Details Exception Handlers ---

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    try:
        phrase = http.HTTPStatus(exc.status_code).phrase
    except ValueError:
        phrase = "HTTP Error"
    status_slug = phrase.lower().replace(" ", "-")
    return JSONResponse(
        status_code=exc.status_code,
        content={{
            "type": f"urn:problem-type:{{status_slug}}",
            "title": phrase,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": request.url.path,
        }},
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    status_code = 422
    return JSONResponse(
        status_code=status_code,
        content={{
            "type": "urn:problem-type:validation-error",
            "title": "Unprocessable Entity",
            "status": status_code,
            "detail": jsonable_encoder(exc.errors()),
            "instance": request.url.path,
        }},
        media_type="application/problem+json",
    )


# --- Scalar Modern Interactive API Reference ---
@app.get("/scalar", response_class=HTMLResponse, include_in_schema=False)
def scalar_docs():
    return """
    <!doctype html>
    <html>
      <head>
        <title>{plan.title} - Scalar Reference</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body>
        <script
          id="api-reference"
          data-url="/openapi.json"
          data-configuration='{{"theme":"purple"}}'>
        </script>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
      </body>
    </html>
    """

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Data Models ---

class {res_title}Create(BaseModel):
{create_fields_str}


class {res_title}Update(BaseModel):
{update_fields_str}


class {res_title}Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)
{response_fields_str}


class PaginationMetadata(BaseModel):
    total: int
    limit: int
    offset: int
    next_cursor: Optional[str] = None
    has_more: bool = False


class {res_title}ListResponse(BaseModel):
    items: List[{res_title}Response]
    total: int
    next_cursor: Optional[str] = None
    has_more: bool = False
    pagination: Optional[PaginationMetadata] = None


# --- In-Memory Database / Data Store ---
INITIAL_RECORDS: List[Dict[str, Any]] = {seed_json}

db: Dict[str, Dict[str, Any]] = {{}}
for row in INITIAL_RECORDS:
    item_id = str(row.get("{pk}") or uuid.uuid4())
    row["{pk}"] = item_id
    db[item_id] = row
db_{schema.plural_name} = db

# --- Idempotency Cache ---
IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {{}}
IDEMPOTENCY_TTL_SECONDS = 300


# --- Health Probe for Cloud Run ---

@app.get("/healthz", tags=["System"])
def health_check():
    return {{"status": "healthy", "service": "{schema.resource_name}-api", "records_count": len(db)}}


# --- Resource Endpoints ---

@app.get(
    "/{schema.plural_name}",
    response_model={res_title}ListResponse,
    summary="List {schema.plural_name}",
    tags=["{res_title}"]{endpoint_security},
)
def list_{schema.plural_name}(
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    cursor: Optional[str] = Query(None, description="Cursor for keyset pagination"),
    sort: Optional[str] = Query(None, description="Sort field (prefix with '-' for descending)"),
    q: Optional[str] = Query(None, description="Search query across text fields"){filter_args_str}
):
    results = list(db.values())

    if q:
        query = q.lower()
        results = [
            item for item in results
            if any(query in str(v).lower() for v in item.values() if v is not None)
        ]

{filter_checks_str}

    # Sorting
    if sort:
        reverse = sort.startswith("-")
        sort_key = sort[1:] if reverse else sort
        def _sort_val(x):
            v = x.get(sort_key)
            if v is None:
                return (1, "")
            try:
                return (0, v)
            except Exception:
                return (0, str(v))
        try:
            results = sorted(results, key=_sort_val, reverse=reverse)
        except TypeError:
            results = sorted(results, key=lambda x: str(x.get(sort_key, "")), reverse=reverse)

    total = len(results)

    # Keyset / Cursor pagination
    last_id = None
    if cursor:
        try:
            cursor_data = json.loads(base64.b64decode(cursor.encode("utf-8")).decode("utf-8"))
            last_id = cursor_data.get("id")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor token")

    def _is_greater(item_val, cursor_val):
        try:
            return int(item_val) > int(cursor_val)
        except (ValueError, TypeError):
            return str(item_val) > str(cursor_val)

    if last_id is not None:
        results = [x for x in results if _is_greater(x.get("{pk}", x.get("id")), last_id)]

    if cursor is not None:
        paged_items = results[:limit]
        has_more = len(results) > limit
    else:
        paged_items = results[offset : offset + limit]
        has_more = (offset + limit) < total

    next_cursor = None
    if has_more and paged_items:
        last_item_id = paged_items[-1].get("{pk}")
        if last_item_id is None:
            last_item_id = paged_items[-1].get("id")
        next_cursor = base64.b64encode(json.dumps({{"id": last_item_id}}).encode("utf-8")).decode("utf-8")

    return {{
        "items": paged_items,
        "total": total,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "pagination": {{
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }},
    }}


@app.get(
    "/{schema.plural_name}/{{{pk}}}",
    response_model={res_title}Response,
    summary="Get {schema.resource_name} by ID",
    tags=["{res_title}"]{endpoint_security},
)
def get_{schema.resource_name}({pk}: str):
    if {pk} not in db:
        raise HTTPException(status_code=404, detail="{schema.resource_name.capitalize()} not found")
    return db[{pk}]
'''

    if plan.allow_create:
        pk_field = next((f for f in schema.fields if f.name == pk), None)
        if pk_field and pk_field.python_type == "int":
            id_gen_logic = """    int_keys = [int(k) for k in db.keys() if str(k).isdigit()]
    new_id = (max(int_keys) + 1) if int_keys else 1"""
        else:
            id_gen_logic = """    new_id = str(uuid.uuid4())"""

        code += f'''
@app.post(
    "/{schema.plural_name}",
    response_model={res_title}Response,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new {schema.resource_name}",
    tags=["{res_title}"]{endpoint_security},
)
def create_{schema.resource_name}(
    payload: {res_title}Create,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    now = time.time()
    if idempotency_key:
        cached = IDEMPOTENCY_CACHE.get(idempotency_key)
        if cached:
            created_at = cached.get("timestamp", 0)
            if now - created_at < IDEMPOTENCY_TTL_SECONDS:
                return JSONResponse(
                    content=cached["data"],
                    status_code=status.HTTP_201_CREATED,
                    headers={{"X-Cache-Lookup": "HIT"}},
                )
            else:
                IDEMPOTENCY_CACHE.pop(idempotency_key, None)

{id_gen_logic}
    record = payload.model_dump()
    record["{pk}"] = new_id
    db[str(new_id)] = record
    if idempotency_key:
        response.headers["X-Cache-Lookup"] = "MISS"
        IDEMPOTENCY_CACHE[idempotency_key] = {{
            "timestamp": now,
            "data": jsonable_encoder(record),
        }}
    return record
'''

    if plan.allow_update:
        code += f'''
@app.patch(
    "/{schema.plural_name}/{{{pk}}}",
    response_model={res_title}Response,
    summary="Update {schema.resource_name}",
    tags=["{res_title}"]{endpoint_security},
)
def update_{schema.resource_name}({pk}: str, payload: {res_title}Update):
    if {pk} not in db:
        raise HTTPException(status_code=404, detail="{schema.resource_name.capitalize()} not found")

    existing = db[{pk}]
    updates = payload.model_dump(exclude_unset=True)
    existing.update(updates)
    db[{pk}] = existing
    return existing
'''

    if plan.allow_delete:
        code += f'''
@app.delete(
    "/{schema.plural_name}/{{{pk}}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete {schema.resource_name}",
    tags=["{res_title}"]{endpoint_security},
)
def delete_{schema.resource_name}({pk}: str):
    if {pk} not in db:
        raise HTTPException(status_code=404, detail="{schema.resource_name.capitalize()} not found")
    del db[{pk}]
    return None
'''

    extra_schemas = [s for s in getattr(plan, "all_schemas", [plan.schema]) if s.resource_name != schema.resource_name]
    for s in extra_schemas:
        s_title = s.resource_name.capitalize()
        s_res = s.resource_name
        s_pk = s.primary_key or "id"
        s_plural = s.plural_name

        s_create_fields_code = []
        s_response_fields_code = []
        s_update_fields_code = []

        for f in s.fields:
            if f.name != s_pk:
                s_create_fields_code.append(f"    {f.name}: {_py_type_annotation(f)}")
                s_update_fields_code.append(f"    {f.name}: {_py_type_annotation_optional(f)}")
            s_response_fields_code.append(f"    {f.name}: {_py_type_annotation(f)}")

        s_create_fields_str = "\n".join(s_create_fields_code) or "    pass"
        s_response_fields_str = "\n".join(s_response_fields_code)
        s_update_fields_str = "\n".join(s_update_fields_code) or "    pass"

        s_records = list(s.sample_records)
        s_seed_json = pprint.pformat(json.loads(json.dumps(s_records, default=str)), indent=4, sort_dicts=False)

        s_pk_field = next((f for f in s.fields if f.name == s_pk), None)
        if s_pk_field and s_pk_field.python_type == "int":
            s_id_gen = f"""    int_keys = [int(k) for k in db_{s_plural}.keys() if str(k).isdigit()]
    new_id = (max(int_keys) + 1) if int_keys else 1"""
        else:
            s_id_gen = """    new_id = str(uuid.uuid4())"""

        code += f'''

# --- Data Models for {s_title} ---

class {s_title}Create(BaseModel):
{s_create_fields_str}


class {s_title}Update(BaseModel):
{s_update_fields_str}


class {s_title}Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)
{s_response_fields_str}


class {s_title}ListResponse(BaseModel):
    items: List[{s_title}Response]
    total: int
    next_cursor: Optional[str] = None
    has_more: bool = False
    pagination: Optional[PaginationMetadata] = None


# --- In-Memory Database for {s_plural} ---
INITIAL_RECORDS_{s_plural.upper()}: List[Dict[str, Any]] = {s_seed_json}

db_{s_plural}: Dict[str, Dict[str, Any]] = {{}}
for row in INITIAL_RECORDS_{s_plural.upper()}:
    item_id = str(row.get("{s_pk}") or uuid.uuid4())
    row["{s_pk}"] = item_id
    db_{s_plural}[item_id] = row


# --- Resource Endpoints for {s_plural} ---

@app.get(
    "/{s_plural}",
    response_model={s_title}ListResponse,
    summary="List {s_plural}",
    tags=["{s_title}"]{endpoint_security},
)
def list_{s_plural}(
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    cursor: Optional[str] = Query(None, description="Cursor for keyset pagination"),
    sort: Optional[str] = Query(None, description="Sort field (prefix with '-' for descending)"),
    q: Optional[str] = Query(None, description="Search query across text fields"),
):
    results = list(db_{s_plural}.values())
    if q:
        query = q.lower()
        results = [
            item for item in results
            if any(query in str(v).lower() for v in item.values() if v is not None)
        ]

    if sort:
        reverse = sort.startswith("-")
        sort_key = sort[1:] if reverse else sort
        def _sort_val(x):
            v = x.get(sort_key)
            if v is None:
                return (1, "")
            try:
                return (0, v)
            except Exception:
                return (0, str(v))
        try:
            results = sorted(results, key=_sort_val, reverse=reverse)
        except TypeError:
            results = sorted(results, key=lambda x: str(x.get(sort_key, "")), reverse=reverse)

    total = len(results)
    last_id = None
    if cursor:
        try:
            cursor_data = json.loads(base64.b64decode(cursor.encode("utf-8")).decode("utf-8"))
            last_id = cursor_data.get("id")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor token")

    def _is_greater(item_val, cursor_val):
        try:
            return int(item_val) > int(cursor_val)
        except (ValueError, TypeError):
            return str(item_val) > str(cursor_val)

    if last_id is not None:
        results = [x for x in results if _is_greater(x.get("{s_pk}", x.get("id")), last_id)]

    if cursor is not None:
        paged_items = results[:limit]
        has_more = len(results) > limit
    else:
        paged_items = results[offset : offset + limit]
        has_more = (offset + limit) < total

    next_cursor = None
    if has_more and paged_items:
        last_item_id = paged_items[-1].get("{s_pk}")
        if last_item_id is None:
            last_item_id = paged_items[-1].get("id")
        next_cursor = base64.b64encode(json.dumps({{"id": last_item_id}}).encode("utf-8")).decode("utf-8")

    return {{
        "items": paged_items,
        "total": total,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "pagination": {{
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }},
    }}


@app.get(
    "/{s_plural}/{{{s_pk}}}",
    response_model={s_title}Response,
    summary="Get {s_res} by ID",
    tags=["{s_title}"]{endpoint_security},
)
def get_{s_res}({s_pk}: str):
    if {s_pk} not in db_{s_plural}:
        raise HTTPException(status_code=404, detail="{s_title} not found")
    return db_{s_plural}[{s_pk}]
'''

        if plan.allow_create:
            code += f'''
@app.post(
    "/{s_plural}",
    response_model={s_title}Response,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new {s_res}",
    tags=["{s_title}"]{endpoint_security},
)
def create_{s_res}(
    payload: {s_title}Create,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    now = time.time()
    if idempotency_key:
        cached = IDEMPOTENCY_CACHE.get(idempotency_key)
        if cached:
            created_at = cached.get("timestamp", 0)
            if now - created_at < IDEMPOTENCY_TTL_SECONDS:
                return JSONResponse(
                    content=cached["data"],
                    status_code=status.HTTP_201_CREATED,
                    headers={{"X-Cache-Lookup": "HIT"}},
                )
            else:
                IDEMPOTENCY_CACHE.pop(idempotency_key, None)

{s_id_gen}
    record = payload.model_dump()
    record["{s_pk}"] = new_id
    db_{s_plural}[str(new_id)] = record
    if idempotency_key:
        response.headers["X-Cache-Lookup"] = "MISS"
        IDEMPOTENCY_CACHE[idempotency_key] = {{
            "timestamp": now,
            "data": jsonable_encoder(record),
        }}
    return record
'''

        if plan.allow_update:
            code += f'''
@app.patch(
    "/{s_plural}/{{{s_pk}}}",
    response_model={s_title}Response,
    summary="Update {s_res}",
    tags=["{s_title}"]{endpoint_security},
)
def update_{s_res}({s_pk}: str, payload: {s_title}Update):
    if {s_pk} not in db_{s_plural}:
        raise HTTPException(status_code=404, detail="{s_title} not found")

    existing = db_{s_plural}[{s_pk}]
    updates = payload.model_dump(exclude_unset=True)
    existing.update(updates)
    db_{s_plural}[{s_pk}] = existing
    return existing
'''

        if plan.allow_delete:
            code += f'''
@app.delete(
    "/{s_plural}/{{{s_pk}}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete {s_res}",
    tags=["{s_title}"]{endpoint_security},
)
def delete_{s_res}({s_pk}: str):
    if {s_pk} not in db_{s_plural}:
        raise HTTPException(status_code=404, detail="{s_title} not found")
    del db_{s_plural}[{s_pk}]
    return None
'''

    from datapi.analytics import generate_duckdb_analytics_code
    code += "\n\n" + generate_duckdb_analytics_code(getattr(plan, "all_schemas", [plan.schema]))

    return code


def generate_tests(plan: APIPlan) -> str:
    schema = plan.schema
    pk = schema.primary_key or "id"

    if plan.auth_enabled:
        auth_setup = 'os.environ.setdefault("API_KEY", "test-api-key")\n'
        auth_header = '{"X-API-Key": os.environ["API_KEY"]}'
        auth_tests = f'''

def test_missing_api_key_rejected():
    response = client.get("/{schema.plural_name}")
    assert response.status_code == 401


def test_invalid_api_key_rejected():
    response = client.get("/{schema.plural_name}", headers={{"X-API-Key": "wrong-key"}})
    assert response.status_code == 401
'''
    else:
        auth_setup = ""
        auth_header = "{}"
        auth_tests = ""

    return f'''"""
Automated Pytest & Contract Test Suite.
Generated by Datapi Engine.
"""

import os

{auth_setup}
from fastapi.testclient import TestClient
from app.main import app  # noqa: E402

client = TestClient(app)
AUTH_HEADERS = {auth_header}


def test_health_check():
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "records_count" in data


def test_list_{schema.plural_name}():
    response = client.get("/{schema.plural_name}?limit=5", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "pagination" in data
    assert len(data["items"]) <= 5


def test_get_{schema.resource_name}_by_id():
    list_res = client.get("/{schema.plural_name}?limit=1", headers=AUTH_HEADERS)
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    if items:
        target_id = items[0]["{pk}"]
        item_res = client.get(f"/{schema.plural_name}/{{target_id}}", headers=AUTH_HEADERS)
        assert item_res.status_code == 200
        assert item_res.json()["{pk}"] == target_id


def test_not_found():
    response = client.get("/{schema.plural_name}/nonexistent-id-9999", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.headers.get("content-type") == "application/problem+json"
    problem = response.json()
    assert problem["status"] == 404
    assert "type" in problem
    assert "title" in problem
    assert "instance" in problem
{auth_tests}'''


def generate_dockerfile() -> str:
    return """# Lightweight Python container for Google Cloud Run
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app
USER appuser

# Cloud Run injects PORT (defaults to 8080)
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
"""


def generate_requirements() -> str:
    return """fastapi>=0.110.0,<1.0.0
uvicorn[standard]>=0.29.0,<1.0.0
pydantic>=2.7.0,<3.0.0
"""


def generate_dev_requirements() -> str:
    return """-r requirements.txt
pytest>=8.0.0
httpx>=0.27.0
"""


def generate_terraform(service_name: str, auth_enabled: bool) -> str:
    secret_block = ""
    env_block = ""
    if auth_enabled:
        secret_block = f"""
variable "api_key" {{
  type        = string
  sensitive   = true
  description = "API key clients must send in the X-API-Key header"
}}

# Secret Manager Secret for API Key
resource "google_secret_manager_secret" "api_key" {{
  secret_id = "{service_name}-api-key"
  replication {{
    auto {{}}
  }}
}}

resource "google_secret_manager_secret_version" "api_key_val" {{
  secret      = google_secret_manager_secret.api_key.id
  secret_data = var.api_key
}}

data "google_project" "project" {{}}

resource "google_secret_manager_secret_iam_member" "cloud_run_secret_access" {{
  secret_id = google_secret_manager_secret.api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${{data.google_project.project.number}}-compute@developer.gserviceaccount.com"
}}
"""
        env_block = """
      env {
        name = "API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = "latest"
          }
        }
      }
"""

    return f"""terraform {{
  required_version = ">= 1.5.0"
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
  }}
}}

variable "project_id" {{
  type        = string
  description = "Google Cloud Project ID"
}}

variable "region" {{
  type        = string
  default     = "us-central1"
  description = "Google Cloud region"
}}

variable "image_tag" {{
  type        = string
  default     = "latest"
  description = "Container image tag"
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}
{secret_block}
# Cloud Run Service (v2)
resource "google_cloud_run_v2_service" "{service_name}" {{
  name     = "{service_name}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {{
    scaling {{
      min_instance_count = 0
      max_instance_count = 10
    }}

    containers {{
      image = "${{var.region}}-docker.pkg.dev/${{var.project_id}}/{service_name}/{service_name}:${{var.image_tag}}"
      resources {{
        limits = {{
          cpu    = "1000m"
          memory = "512Mi"
        }}
      }}
      ports {{
        container_port = 8080
      }}
      startup_probe {{
        http_get {{
          path = "/healthz"
          port = 8080
        }}
      }}
{env_block}
    }}
  }}
}}

# Public Invocation
resource "google_cloud_run_v2_service_iam_member" "public_access" {{
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.{service_name}.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}}

output "service_url" {{
  value       = google_cloud_run_v2_service.{service_name}.uri
  description = "Public URL of deployed API"
}}
"""


def generate_readme(plan: APIPlan) -> str:
    schema = plan.schema
    res_title = schema.resource_name.capitalize()
    auth_doc = ""
    auth_curl = ""
    if plan.auth_enabled:
        auth_doc = "\n- **Authentication**: `X-API-Key` required on all resource endpoints. Set the `API_KEY` environment variable on the server; requests are rejected (503) until it is set."
        auth_curl = ' -H "X-API-Key: $API_KEY"'

    return f"""# {plan.title}

> Auto-generated with **Datapi Engine**

## Overview
- **Resource**: `{schema.resource_name}` (plural: `{schema.plural_name}`)
- **Specification**: OpenAPI 3.1 (`openapi.json` & `openapi.yaml`)
- **Framework**: FastAPI (Python 3.12+), Pydantic v2
- **Deployment Target**: Google Cloud Run (Containerized, auto-scaling 0 -> 10){auth_doc}

## Quickstart (Local)

### 1. Install dependencies
```bash
pip install -r requirements-dev.txt
```

### 2. Run automated tests
```bash
pytest tests/
```

### 3. Run API server
```bash
{"export API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" + chr(10) if plan.auth_enabled else ""}uvicorn app.main:app --reload --port 8000
```

### 4. Explore Interactive Docs
- Scalar Modern UI: [http://localhost:8000/scalar](http://localhost:8000/scalar)
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Redoc UI: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- OpenAPI Spec: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## TypeScript Client SDK

A zero-dependency typed client SDK is automatically emitted to `sdk/client.ts`.

```typescript
import {{ {res_title}Client }} from "./sdk/client";

const client = new {res_title}Client({{
  baseUrl: "http://localhost:8000",
  apiKey: "your-api-key",
}});

// Fully typed response with pagination
const response = await client.list({{ limit: 10, q: "alice" }});
console.log(response.items);
```

---

## API Testing with Curl

### List records (with search & pagination)
```bash
curl -X GET "http://localhost:8000/{schema.plural_name}?limit=5&offset=0"{auth_curl}
```

### Free-text search
```bash
curl -X GET "http://localhost:8000/{schema.plural_name}?q=test"{auth_curl}
```

### Health check
```bash
curl -X GET "http://localhost:8000/healthz"
```
"""


def generate_project(plan: APIPlan, output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app_dir = output_dir / "app"
    tests_dir = output_dir / "tests"
    tf_dir = output_dir / "terraform"
    app_dir.mkdir(exist_ok=True)
    tests_dir.mkdir(exist_ok=True)
    tf_dir.mkdir(exist_ok=True)

    generated_files: Dict[str, str] = {}

    # 1. OpenAPI JSON
    openapi_spec = generate_openapi_spec(plan)
    openapi_json_path = output_dir / "openapi.json"
    with open(openapi_json_path, "w", encoding="utf-8") as f:
        json.dump(openapi_spec, f, indent=2)
    generated_files["openapi.json"] = str(openapi_json_path)

    # 2. FastAPI Code (app/main.py)
    fastapi_code = generate_fastapi_code(plan)
    main_py_path = app_dir / "main.py"
    with open(main_py_path, "w", encoding="utf-8") as f:
        f.write(fastapi_code)
    generated_files["app/main.py"] = str(main_py_path)

    init_py = app_dir / "__init__.py"
    init_py.touch()
    generated_files["app/__init__.py"] = str(init_py)

    # 3. Pytest suite (tests/test_api.py)
    test_code = generate_tests(plan)
    test_py_path = tests_dir / "test_api.py"
    with open(test_py_path, "w", encoding="utf-8") as f:
        f.write(test_code)
    generated_files["tests/test_api.py"] = str(test_py_path)

    test_init = tests_dir / "__init__.py"
    test_init.touch()
    generated_files["tests/__init__.py"] = str(test_init)

    # 4. requirements.txt
    reqs = generate_requirements()
    req_path = output_dir / "requirements.txt"
    with open(req_path, "w", encoding="utf-8") as f:
        f.write(reqs)
    generated_files["requirements.txt"] = str(req_path)

    dev_req_path = output_dir / "requirements-dev.txt"
    with open(dev_req_path, "w", encoding="utf-8") as f:
        f.write(generate_dev_requirements())
    generated_files["requirements-dev.txt"] = str(dev_req_path)

    # 5. Dockerfile
    dockerfile = generate_dockerfile()
    docker_path = output_dir / "Dockerfile"
    with open(docker_path, "w", encoding="utf-8") as f:
        f.write(dockerfile)
    generated_files["Dockerfile"] = str(docker_path)

    # 6. Terraform
    service_name = f"{plan.schema.resource_name.lower()}-api"
    tf_code = generate_terraform(service_name, plan.auth_enabled)
    tf_path = tf_dir / "main.tf"
    with open(tf_path, "w", encoding="utf-8") as f:
        f.write(tf_code)
    generated_files["terraform/main.tf"] = str(tf_path)

    # 7. README.md
    readme = generate_readme(plan)
    readme_path = output_dir / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)
    generated_files["README.md"] = str(readme_path)

    # 8. TypeScript & Python Client SDKs (sdk/client.ts, sdk/client.py)
    sdk_dir = output_dir / "sdk"
    sdk_dir.mkdir(exist_ok=True)
    ts_sdk = generate_typescript_sdk(plan)
    ts_sdk_path = sdk_dir / "client.ts"
    with open(ts_sdk_path, "w", encoding="utf-8") as f:
        f.write(ts_sdk)
    generated_files["sdk/client.ts"] = str(ts_sdk_path)

    py_sdk = generate_python_sdk(plan)
    py_sdk_path = sdk_dir / "client.py"
    with open(py_sdk_path, "w", encoding="utf-8") as f:
        f.write(py_sdk)
    generated_files["sdk/client.py"] = str(py_sdk_path)

    return generated_files

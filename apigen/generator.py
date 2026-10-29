"""
APIGen Code & Specification Generator.
Generates OpenAPI 3.1, FastAPI app with Pydantic models, Dockerfile, Terraform for Cloud Run, and Docs.
"""

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from apigen.planner import APIPlan
from apigen.infer import FieldDef, SchemaDef


def _py_type_annotation(field: FieldDef) -> str:
    mapping = {
        "int": "int",
        "float": "float",
        "bool": "bool",
        "str": "str",
        "datetime": "datetime",
        "date": "date",
    }
    base = mapping.get(field.python_type, "str")
    if field.nullable:
        return f"Optional[{base}] = None"
    return base


def _py_type_annotation_optional(field: FieldDef) -> str:
    mapping = {
        "int": "int",
        "float": "float",
        "bool": "bool",
        "str": "str",
        "datetime": "datetime",
        "date": "date",
    }
    base = mapping.get(field.python_type, "str")
    return f"Optional[{base}] = None"


def _generate_synthetic_record(schema: SchemaDef, idx: int) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for f in schema.fields:
        if f.is_primary_key:
            row[f.name] = idx if f.python_type == "int" else f"ID_{idx:04d}"
        elif f.enum_values:
            row[f.name] = random.choice(f.enum_values)
        elif f.openapi_format == "email":
            row[f.name] = f"user_{idx}@example.com"
        elif f.openapi_format == "date":
            row[f.name] = (date.today() - timedelta(days=idx * 3)).isoformat()
        elif f.openapi_format == "date-time":
            row[f.name] = (datetime.now() - timedelta(hours=idx * 6)).isoformat()
        elif f.python_type == "int":
            row[f.name] = idx * 10
        elif f.python_type == "float":
            row[f.name] = round(19.99 + (idx * 5.5), 2)
        elif f.python_type == "bool":
            row[f.name] = idx % 2 == 0
        else:
            row[f.name] = f"Sample {f.name.replace('_', ' ').capitalize()} {idx}"
    return row


def generate_openapi_spec(plan: APIPlan) -> Dict[str, Any]:
    schema = plan.schema
    res_title = schema.resource_name.capitalize()
    res_path = f"/{schema.plural_name}"

    properties: Dict[str, Any] = {}
    required_fields: List[str] = []

    for f in schema.fields:
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

    components: Dict[str, Any] = {
        "schemas": {
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
            "PaginationMetadata": {
                "type": "object",
                "properties": {
                    "total": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            },
            f"{res_title}ListResponse": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"$ref": f"#/components/schemas/{res_title}Response"},
                    },
                    "pagination": {"$ref": "#/components/schemas/PaginationMetadata"},
                },
            },
        }
    }

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

    # Endpoint: GET /resources
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

    spec["paths"][res_path] = {"get": list_op}

    # Endpoint: POST /resources
    if plan.allow_create:
        spec["paths"][res_path]["post"] = {
            "summary": f"Create a new {schema.resource_name}",
            "tags": [res_title],
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

    # Endpoint: GET /resources/{id}
    pk = schema.primary_key or "id"
    item_path = f"{res_path}/{{{pk}}}"
    spec["paths"][item_path] = {
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

    # Endpoint: PATCH /resources/{id}
    if plan.allow_update:
        spec["paths"][item_path]["patch"] = {
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

    # Endpoint: DELETE /resources/{id}
    if plan.allow_delete:
        spec["paths"][item_path]["delete"] = {
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

    seed_json = json.dumps(records, indent=4, default=str)

    # Auth block
    auth_imports = ""
    auth_dependency = ""
    endpoint_security = ""
    if plan.auth_enabled:
        auth_imports = """
import os
from fastapi.security import APIKeyHeader
from fastapi import Security, Depends

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)
SERVER_API_KEY = os.getenv("API_KEY", "default-dev-secret-key")

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != SERVER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return api_key
"""
        endpoint_security = ", dependencies=[Depends(verify_api_key)]"

    code = f'''"""
{plan.title} - Production FastAPI Service.
Generated by APIGen Blueprint Engine.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
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


class {res_title}ListResponse(BaseModel):
    items: List[{res_title}Response]
    pagination: PaginationMetadata


# --- In-Memory Database / Data Store ---
INITIAL_RECORDS: List[Dict[str, Any]] = {seed_json}

db: Dict[str, Dict[str, Any]] = {{}}
for row in INITIAL_RECORDS:
    item_id = str(row.get("{pk}") or uuid.uuid4())
    row["{pk}"] = item_id
    db[item_id] = row


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

    total = len(results)
    paged_items = results[offset : offset + limit]
    return {{"items": paged_items, "pagination": {{"total": total, "limit": limit, "offset": offset}}}}


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
def create_{schema.resource_name}(payload: {res_title}Create):
{id_gen_logic}
    record = payload.model_dump()
    record["{pk}"] = new_id
    db[str(new_id)] = record
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

    return code


def generate_tests(plan: APIPlan) -> str:
    schema = plan.schema
    pk = schema.primary_key or "id"

    auth_header = '{"X-API-Key": "default-dev-secret-key"}' if plan.auth_enabled else "{}"

    return f'''"""
Automated Pytest & Contract Test Suite.
Generated by APIGen Blueprint Engine.
"""

from fastapi.testclient import TestClient
from app.main import app

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
'''


def generate_dockerfile() -> str:
    return """# Multi-stage lightweight Python container for Google Cloud Run
FROM python:3.12-slim as builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run defaults to PORT 8080
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
"""


def generate_requirements() -> str:
    return """fastapi>=0.110.0,<1.0.0
uvicorn[standard]>=0.29.0,<1.0.0
pydantic>=2.7.0,<3.0.0
pytest>=8.0.0
httpx>=0.27.0
"""


def generate_terraform(service_name: str, auth_enabled: bool) -> str:
    secret_block = ""
    env_block = ""
    iam_secret_block = ""
    if auth_enabled:
        secret_block = f"""
# Secret Manager Secret for API Key
resource "google_secret_manager_secret" "api_key" {{
  secret_id = "{service_name}-api-key"
  replication {{
    auto {{}}
  }}
}}

resource "google_secret_manager_secret_version" "api_key_val" {{
  secret      = google_secret_manager_secret.api_key.id
  secret_data = "prod-secure-api-key-change-me"
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
    auth_doc = ""
    auth_curl = ""
    if plan.auth_enabled:
        auth_doc = "\n- **Authentication**: `X-API-Key` required on all resource endpoints."
        auth_curl = ' -H "X-API-Key: default-dev-secret-key"'

    return f"""# {plan.title}

> Auto-generated with **APIGen Blueprint Engine**

## Overview
- **Resource**: `{schema.resource_name}` (plural: `{schema.plural_name}`)
- **Specification**: OpenAPI 3.1 (`openapi.json` & `openapi.yaml`)
- **Framework**: FastAPI (Python 3.12+), Pydantic v2
- **Deployment Target**: Google Cloud Run (Containerized, auto-scaling 0 -> 10){auth_doc}

## Quickstart (Local)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run automated tests
```bash
pytest tests/
```

### 3. Run API server
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Explore Interactive Docs
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Redoc UI: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- OpenAPI Spec: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

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

    return generated_files

<div align="center">

<img src="datapi/studio/assets/datapi-logo.svg" alt="datapi logo" width="380" />

### Raw data in. Production APIs out.

**Turn raw schemas and legacy data into tested, containerized, production-ready APIs in seconds.**

[![CI](https://github.com/creova-gif/api-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/creova-gif/api-gen/actions)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1.0-6BA539.svg?logo=openapi-initiative&logoColor=white)](https://spec.openapis.org/oas/v3.1.0)
[![Terraform](https://img.shields.io/badge/Terraform-1.5%2B-844FBA.svg?logo=terraform&logoColor=white)](https://www.terraform.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<p align="center">
  <a href="#-quickstart">Quickstart</a> •
  <a href="#-how-it-works">How It Works</a> •
  <a href="#-why-datapi-vs-alternatives">Why datapi?</a> •
  <a href="#%EF%B8%8F-configuration">Configuration</a> •
  <a href="#-generated-project-structure">Generated Structure</a> •
  <a href="#-cli-reference">CLI Reference</a> •
  <a href="#-contributing">Contributing</a>
</p>

</div>

---

## 📌 The Problem

Forward-Deployed Engineers, Solutions Architects, and backend developers waste **2 to 4 weeks** during customer onboarding manually writing boilerplate to expose legacy customer exports (CSV, JSON, database dumps). 

Existing "database-to-API" tools (Hasura, PostgREST) fail in enterprise workflows because security and architecture teams **reject black-box proxy layers** in front of production data. Developers need clean, typed, inspectable, and git-committable code that integrates into standard CI/CD pipelines.

**datapi solves this.** In well under a second, datapi inspects a raw dataset and generates a complete, tested, containerized microservice repository.

---

## 🏗️ How It Works

```
[Raw Legacy Data]                     [datapi Engine]                      [Production Microservice]
  (CSV, JSON, SQLite)                  (Zero Dependencies)
          │                                   │
          ├──> 1. Type & PK Inference  ───────┤
          │                                   │
          ├──> 2. Synthetic Mocks  ───────────┼──> OpenAPI 3.1.0 Spec (openapi.json)
          │                                   ├──> FastAPI Service (Pydantic v2)
          ├──> 3. Security & Auth Guard  ─────┼──> Pytest Contract Suite (test_api.py)
          │                                   ├──> Dockerfile (Python 3.12-slim)
          └──> 4. Cloud Run IaC Synthesis ────└──> Terraform Scripts (GCP Cloud Run v2)
```

---

## ✨ Key Features

- **Schema inference** from CSV, JSON and SQLite: types (`int`, `float`, `bool`, `date`, `datetime`, `uuid`, `email`, `str`), primary keys and filter candidates.
- **FastAPI + Pydantic v2 service** with full CRUD, pagination, free-text search and `/healthz`.
- **OpenAPI 3.1 contract**, Swagger, ReDoc and Scalar docs.
- **Typed SDKs**: zero-dependency TypeScript client and a Python client.
- **Generated pytest contract suite** for every service.
- **Optional `X-API-Key` auth** that fails closed until `API_KEY` is set.
- **Deployment bundles** for Google Cloud Run (Terraform), Fly.io and AWS App Runner.
- **Schema drift detection** (`datapi diff`) and consumer code patching (`datapi patch`).
- **datapi Studio**, a local browser UI for drag-and-drop generation.
- **Zero runtime dependencies** for the generator itself (standard library only).

<!-- TODO: replace with a real screenshot or GIF of datapi Studio -->
<p align="center"><img src="docs/images/studio-placeholder.svg" alt="datapi Studio screenshot (placeholder)" width="720" /></p>

---

## ✅ Prerequisites

- Python **3.10+** (CI runs 3.10–3.13)
- `pip`
- To run a generated service: the packages in its `requirements.txt` (FastAPI, Uvicorn, Pydantic v2)
- Optional: Docker, Terraform 1.5+ and the `gcloud` CLI for deployment

---

## ⚡ Quickstart

### 1. Installation

The core generator has **zero third-party dependencies**:

```bash
git clone https://github.com/creova-gif/api-gen.git
cd api-gen
```

*(Optional: install globally via pip)*
```bash
pip install -e .
```

### 2. Inspect Inferred Schema (Terminal)

Inspect any dataset without touching a database:

```bash
python3 datapi.py inspect -d examples/customers.csv
```

**Output:**
```text
✨ Inferred Schema for: customer (Plural: customers)
Primary Key: customer_id

Field                Python Type    OpenAPI Type   Nullable   Filter Candidate
---------------------------------------------------------------------------
customer_id (PK)     int            integer        False      True
full_name            str            string         False      False
email                str            string         False      False
plan_tier            str            string         False      False
account_balance      float          number         False      False
is_active            bool           boolean        False      False
created_at           datetime       string         False      False

Sample records ingested: 5
```

### 3. Generate Full API Repository

Generate an authenticated FastAPI microservice with 25 synthetic mock records and Cloud Run Terraform:

```bash
python3 datapi.py generate \
  -d examples/customers.csv \
  -o ./my_customer_api \
  --auth \
  --mock 25
```

### 4. Run the Generated API

```bash
cd my_customer_api
pip install -r requirements-dev.txt
pytest tests/
export API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"  # required with --auth
uvicorn app.main:app --port 8080 --reload
```

With `--auth`, the service fails closed: resource endpoints return `503` until `API_KEY` is set, and `401` for a missing or wrong `X-API-Key`. The Terraform module takes the key as a sensitive `api_key` variable (`terraform apply -var="api_key=..."`).

- **Interactive Swagger UI**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **Interactive Scalar UI**: [http://localhost:8080/scalar](http://localhost:8080/scalar)
- **ReDoc Technical Docs**: [http://localhost:8080/redoc](http://localhost:8080/redoc)
- **Health Liveness Probe**: [http://localhost:8080/healthz](http://localhost:8080/healthz)

---

## 🔍 Why datapi vs. Alternatives?

| Feature | datapi | Hasura / PostgREST | Supabase / PocketBase | Manual Coding |
| :--- | :---: | :---: | :---: | :---: |
| **Output Type** | **Git-Committable Code** | Black-box Proxy | Proprietary BaaS | Custom Code |
| **Data Ingestion** | **Raw CSV, JSON, SQLite** | Requires Live Postgres | DB Migration Required | Manual Mapping |
| **Vendor Lock-In** | **None (Standard Python)** | High | High | None |
| **Enterprise Auditable** | **100% Inspectable** | ❌ Opaque Proxy | ❌ Proprietary Cloud | ✅ Custom |
| **Time to Live API** | **< 5 seconds** | 10–30 minutes | 15–45 minutes | 2–3 weeks |
| **Turnkey Cloud Run IaC** | **Included (Terraform)** | ❌ No | ❌ No | ❌ Manual |
| **Automated Test Suite** | **Included (Pytest)** | ❌ No | ❌ No | ❌ Manual |

---

## 📦 Generated Project Structure

Every generated microservice is a clean, production-ready repository:

```text
my_customer_api/
├── README.md               # Quickstart and endpoint documentation
├── requirements.txt        # Runtime dependencies (FastAPI, Uvicorn, Pydantic v2)
├── requirements-dev.txt    # Test dependencies (pytest, httpx)
├── Dockerfile              # Non-root Python 3.12-slim container
├── openapi.json            # Strict OpenAPI 3.1.0 contract
├── app/
│   ├── __init__.py
│   └── main.py             # FastAPI service, Pydantic v2 models, Scalar docs & auth
├── sdk/
│   └── client.ts           # Zero-dependency typed TypeScript Client SDK
├── tests/
│   ├── __init__.py
│   └── test_api.py         # Automated contract tests (health, CRUD, pagination, auth)
└── terraform/
    └── main.tf             # Google Cloud Run v2 service + Secret Manager IAM policy
```

---

## 🛠️ CLI Reference

```text
usage: datapi [-h] {inspect,generate,diff,studio} ...
```

### `datapi studio` *(Interactive Web UI)*
Launches the zero-setup, dark-mode datapi Studio in your browser:
```bash
python3 datapi.py studio            # binds 127.0.0.1:3000
python3 datapi.py studio --host 0.0.0.0 --port 8000 --no-open
```
- Drag-and-drop CSV, JSON, or SQLite datasets.
- Interactive in-browser live testing sandbox.
- Live syntax-highlighted previews of FastAPI, TypeScript SDK, and Terraform.
- 1-Click ZIP bundle export.

### `datapi inspect`
Inspects data source and prints detected column types, primary keys, and filter candidates.

| Flag | Shorthand | Required | Description |
| :--- | :---: | :---: | :--- |
| `--data` | `-d` | Yes | Path to source file (`.csv`, `.json`, `.sqlite`, `.db`) |
| `--name` | `-n` | No | Override inferred resource name |

### `datapi generate`
Generates complete OpenAPI spec, FastAPI app, Pytest suite, and Terraform scripts.

| Flag | Shorthand | Default | Description |
| :--- | :---: | :---: | :--- |
| `--data` | `-d` | *Required* | Path to input data file |
| `--out` | `-o` | `./generated_<name>_api` | Destination output directory |
| `--name` | `-n` | Inferred | Override resource singular name |
| `--auth` | | `False` | Enable `X-API-Key` auth wired to Cloud Secret Manager |
| `--mock` | | `0` | Synthesize N schema-valid mock records |
| `--intent` | `-i` | `None` | Natural language guidance (e.g. `"read-only"`) |

### `datapi diff` *(Self-Maintaining APIs)*
Detects breaking vs. non-breaking schema drift between datasets and outputs automated GitHub PR bodies.

| Flag | Shorthand | Default | Description |
| :--- | :---: | :---: | :--- |
| `--old` | `-a` | *Required* | Path to base data source |
| `--new` | `-b` | *Required* | Path to updated data source |
| `--name` | `-n` | Inferred | Override resource name |
| `--pr` | `-p` | None | Save markdown PR body for automated GitHub pull requests |

### `datapi patch`
Rewrites consumer code (`.ts`, `.tsx`, `.py`) when a schema changes. Shows a dry-run diff unless `--apply` is passed.

| Flag | Shorthand | Default | Description |
| :--- | :---: | :---: | :--- |
| `--consumer-dir` | | `.` | Directory containing the consumer codebase (alias `--target-dir`) |
| `--diff` | `-f` | None | Path to a schema diff JSON file |
| `--old` / `--new` | `-a` / `-b` | None | Data files to diff (alternative to `--diff`) |
| `--name` | `-n` | Inferred | Override resource name |
| `--apply` | | `False` | Write patches in place |

### `datapi deploy`
Generates deployment bundles.

| Flag | Shorthand | Default | Description |
| :--- | :---: | :---: | :--- |
| `--target` | `-t` | `all` | `cloudrun`, `fly`, `aws` or `all` |
| `--out` | `-o` | `./deploy` | Output directory |
| `--data` | `-d` | None | Optional input data file |
| `--name` | `-n` | Inferred | Override service name |
| `--auth` | | `False` | Enable API key auth in the configs |
| `--dry-run` | | `False` | Print configs to stdout without writing files |

---

## ⚙️ Configuration

datapi is configured through CLI flags (see above). Generated services read:

| Variable | Used by | Description |
| :--- | :--- | :--- |
| `API_KEY` | Services generated with `--auth` | Expected `X-API-Key` value. Endpoints return `503` until it is set. |
| `api_key` (Terraform variable) | `terraform/main.tf` | Sensitive variable stored in Secret Manager and mounted into Cloud Run. |

A composite GitHub Action for CI lives in [`.github/actions/datapi-action`](.github/actions/datapi-action/action.yml); see [`docs/GITHUB_ACTION.md`](docs/GITHUB_ACTION.md).

---

## 🗂️ Repository Structure

```text
api-gen/
├── datapi/                # Generator package
│   ├── cli.py             # CLI entry point (inspect, generate, diff, patch, studio, deploy)
│   ├── infer.py           # Schema inference for CSV / JSON / SQLite
│   ├── planner.py         # Builds the API plan from schema + intent
│   ├── generator.py       # FastAPI app, OpenAPI spec, tests, Dockerfile, Terraform
│   ├── sdk_generator.py   # TypeScript SDK
│   ├── python_sdk_generator.py
│   ├── diff.py            # Schema drift detection
│   ├── patcher.py         # Consumer code patcher
│   ├── deployer.py        # Cloud Run / Fly.io / App Runner bundles
│   ├── analytics.py       # DuckDB / SQLite analytics helpers
│   └── studio/            # Browser UI
├── datapi.py, apigen.py   # Run-from-source wrappers
├── bin/                   # Shell launchers
├── examples/              # Sample datasets
├── tests/                 # unittest suite
└── docs/                  # Design, brand and GitHub Action docs
```

---

## 🎨 Brand & Design System

The official brand guidelines, design tokens, and vector assets are detailed in:
- [`docs/BRAND_KIT.md`](docs/BRAND_KIT.md)
- [`docs/brand-kit.html`](docs/brand-kit.html) (Interactive Brand Presentation)

---

## 🧪 Testing datapi

Run the test suite across schema inference, code generation, and contract validation:

```bash
pip install ".[test]"
python3 -m unittest discover -s tests -v
```

---

## 🗺️ Roadmap

- [x] CSV, JSON, and SQLite schema inference
- [x] OpenAPI 3.1.0 & Pydantic v2 code generator
- [x] Modern Interactive Scalar Documentation (`/scalar`)
- [x] Zero-Dependency Typed TypeScript Client SDK (`sdk/client.ts`)
- [x] Interactive In-Browser Studio UI (`datapi studio`)
- [x] Google Cloud Run v2 Terraform templates
- [x] API Key authentication via Google Secret Manager
- [x] Synthetic mock data synthesis (`--mock`)
- [x] Schema drift detection & automated PR generator (`datapi diff`)
- [x] Consumer code patcher (`datapi patch`)
- [x] Fly.io and AWS App Runner deployment bundles (`datapi deploy`)
- [ ] Multi-table foreign key relational inference (`--schema-dir`)
- [ ] Pluggable DuckDB & SQLite persistent storage adapters

---

## 🤝 Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup and PR guidelines, and follow our [Code of Conduct](CODE_OF_CONDUCT.md). Release notes are in [`CHANGELOG.md`](CHANGELOG.md).

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

## 💬 Support

- Bugs and feature requests: [open an issue](https://github.com/creova-gif/api-gen/issues)
- Security issues: email creativeinnovationspace@gmail.com instead of opening a public issue
- Maintainer: Justin Mafie ([@creova-gif](https://github.com/creova-gif))

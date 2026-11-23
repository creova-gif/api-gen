# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `0.1.x` | :white_check_mark: |

## Reporting a Vulnerability

Please report security vulnerabilities privately by emailing **creativeinnovationspace@gmail.com** rather than opening a public GitHub issue.

Include:
1. A description of the vulnerability and the affected module (`datapi/infer.py`, `datapi/generator.py`, `datapi/patcher.py`, `datapi/deployer.py`, or `datapi/studio/`).
2. Minimal input dataset or CLI command required to reproduce the issue.
3. Assessment of impact on either the `datapi` compiler or the generated FastAPI/Docker/Terraform artifacts.

We acknowledge vulnerability reports within **48 hours** and target remediation within **7 days**.

---

## Security Architecture & Boundaries

### 1. Zero-Dependency Offline Compiler Core
- The `datapi` (`apigen`) CLI and schema inference engine use only the Python 3.10+ standard library (`csv`, `json`, `sqlite3`, `ast`, `http.server`, `urllib`).
- Schema inspection (`datapi inspect`), code generation (`datapi generate`), drift detection (`datapi diff`), and consumer AST patching (`datapi patch`) execute 100% locally with **zero outbound network requests** or telemetry.

### 2. Fail-Closed API Key Authentication in Generated Services
- When a microservice is generated with `--auth`:
  - The generated FastAPI service requires the `API_KEY` environment variable at runtime and validates incoming `X-API-Key` headers using constant-time comparison (`secrets.compare_digest` / strict header guard).
  - **Fail-Closed Guarantee:** If `API_KEY` is unset or empty in the container environment, protected endpoints return `HTTP 503 Service Unavailable` rather than failing open. Missing or invalid client keys return `HTTP 401 Unauthorized` with RFC 7807 Problem Details payloads.
  - The generated Google Cloud Run v2 Terraform module (`terraform/main.tf`) provisions `api_key` as a `sensitive = true` variable backed by Google Cloud Secret Manager with least-privilege IAM binding.

### 3. Non-Root Container Runtime
- Every generated `Dockerfile` builds on `python:3.12-slim`, creates an unprivileged application user, and drops root privileges (`USER appuser`) prior to launching `uvicorn`. CI verifies `id -u != 0` inside the running container on every push.

### 4. SQL Injection & Input Validation Defenses
- Inferred fields are compiled into strict **Pydantic v2** request/response models with explicit type coercion and validation constraints.
- SQLite and DuckDB analytical queries in `datapi/analytics.py` and `datapi/infer.py` validate identifier names and use parameterized queries for data values.

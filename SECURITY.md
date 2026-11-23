# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `0.2.x` | :white_check_mark: |
| `0.1.x` | :white_check_mark: |

## Reporting a Vulnerability

Please report security vulnerabilities privately by emailing **creativeinnovationspace@gmail.com** rather than opening a public GitHub issue.

Include:
1. A description of the vulnerability and the affected module (`datapi/infer.py`, `datapi/generator.py`, `datapi/analytics.py`, `datapi/patcher.py`, `datapi/deployer.py`, or `datapi/studio/`).
2. Minimal input dataset or CLI command required to reproduce the issue.
3. Assessment of impact on either the `datapi` compiler or the generated FastAPI, Docker, SDK, or Terraform artifacts.

We acknowledge vulnerability reports within **48 hours** and target remediation within **7 days**.

---

## Security Architecture & Boundaries

### 1. Zero-Dependency Offline Compiler Core
- The `datapi` (`apigen`) CLI and schema inference engine use only the Python 3.10+ standard library (`csv`, `json`, `sqlite3`, `ast`, `http.server`, `urllib`) by default (`dependencies = []` in `pyproject.toml`), with `duckdb` isolated to the optional `datapi[analytics]` extra.
- Schema inspection (`datapi inspect`), code generation (`datapi generate`), drift detection (`datapi diff`), and consumer AST patching (`datapi patch`) execute 100% locally with **zero outbound network requests** or telemetry.

### 2. Generated FastAPI Authentication & Strict CORS Defaults
- **Fail-Closed API Key Authentication (`--auth`):**
  - Generated FastAPI services validate incoming `X-API-Key` headers against the runtime `API_KEY` environment variable using constant-time `hmac.compare_digest`.
  - If `API_KEY` is unset or empty in the runtime environment, protected endpoints fail closed with `HTTP 503 Service Unavailable` rather than failing open or falling back to a default key.
  - Missing or invalid client keys return `HTTP 401 Unauthorized` formatted as RFC 7807 `application/problem+json` responses. Both CRUD resource routes and `/analytics/*` aggregation endpoints enforce `Depends(verify_api_key)` when `--auth` is enabled.
- **Safe CORS Configuration:**
  - Generated services read comma-separated origins from `CORS_ALLOW_ORIGINS`.
  - When `CORS_ALLOW_ORIGINS` is unset, `CORSMiddleware` defaults to uncredentialed `allow_origins=["*"]` with `allow_credentials=False`. `allow_credentials=True` is enabled **only** when explicit non-wildcard origins are configured—never combining `*` with credentialed requests.

### 3. DuckDB & SQLite Query Parameterization & Identifier Allowlisting
- All ingested record values in `datapi/analytics.py` (`executemany("INSERT INTO records VALUES (?, ...)")`) and Parquet file paths in `datapi/infer.py` (`SELECT * FROM read_parquet(?)`) are passed via parameterized bindings, never string interpolation.
- Because SQL engines cannot bind column identifiers via `?` placeholders, both `synthesize_summary_sql()` / `synthesize_timeseries_sql()` and the generated `/analytics/summary` & `/analytics/timeseries` FastAPI handlers strictly validate `group_by`, `date_field`, `metric`, and `table_name` against regex identifier rules (`^[A-Za-z_][A-Za-z0-9_]*$`) and the inferred `SchemaDef` column allowlist, and restrict `interval` to `("day", "month", "year")`. Unrecognized identifiers are rejected (`HTTP 400` / `ValueError`) prior to query synthesis.

### 4. Consumer AST Patcher Safety (`datapi/patcher.py`)
- **Dry-Run by Default:** `datapi patch` computes unified diffs (`diff -u`) in memory and never mutates consumer files on disk unless `--apply` is explicitly passed.
- **Workspace & Directory Isolation:** Traversal skips `.git`, `node_modules`, `__pycache__`, `.pytest_cache`, `dist`, `build`, `.venv`, and `venv`.
- **AST Syntax Gate:** Every patched Python consumer file is parsed in memory via `ast.parse()` before writing. Any transformation that fails syntax validation raises `ValueError` and leaves the target file untouched. Removed schema fields are rewritten to safe non-throwing fallbacks (`.get(..., None)` / `getattr(..., None)`) rather than destructive statement deletions.

### 5. Terraform Secret Hygiene & Non-Root Container Runtime
- **GCP Cloud Run (`terraform/main.tf`) & AWS App Runner (`terraform/aws_apprunner.tf`):**
  - When `--auth` is enabled, both Terraform modules declare `variable "api_key"` with `sensitive = true` and **no default value**, requiring explicit operator injection (`-var="api_key=..."` or `TF_VAR_api_key`).
  - Secrets are provisioned into **Google Cloud Secret Manager** (`google_secret_manager_secret` + `secret_key_ref`) and **AWS Secrets Manager** (`aws_secretsmanager_secret` + `runtime_environment_secrets` paired with a least-privilege `secretsmanager:GetSecretValue` App Runner instance IAM role)—never injected as plaintext `runtime_environment_variables` or placeholder strings.
  - Fly.io manifests (`fly.toml`) never embed `API_KEY` values and instruct operators to set runtime secrets via `fly secrets set API_KEY="..."`.
- **Non-Root Container Execution:** Every generated `Dockerfile` builds on `python:3.12-slim`, creates UID `10001` (`appuser`), and drops root privileges (`USER appuser`) before launching `uvicorn`. GitHub Actions CI verifies `id -u != 0` inside the running container on every push and pull request.

# Changelog

All notable changes to **Datapi** (formerly **APIGen**, backwards-compatible via `apigen`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-11-23

### Added
- **Multi-Table Relational Foreign-Key Inference (`datapi/infer.py`)**:
  - `infer_from_directory()` and `infer_multi_table_relationships()` automatically resolve cross-table foreign keys (`<resource>_id` / `<resource>Id` -> target primary key) across CSV, JSON, SQLite, and Parquet files.
  - Optional `.parquet` dataset ingestion via the `datapi[analytics]` (`duckdb>=1.0.0`) extra while keeping core `dependencies = []`.
- **Vectorized DuckDB & SQLite Window Analytics (`datapi/analytics.py`)**:
  - Synthesizes `/<plural>/analytics/summary` (`COUNT`, `AVG`, `MIN`, `MAX`, `SUM`, `GROUP BY`) and `/<plural>/analytics/timeseries` (cumulative sums and 7-period moving averages) using embedded DuckDB when available with automatic fallback to stdlib SQLite window functions.
- **Zero-Dependency Python & TypeScript Client SDKs (`datapi/python_sdk_generator.py`, `datapi/sdk_generator.py`)**:
  - Emits `sdk/client.py` (`urllib.request`) and `sdk/client.ts` (`fetch`) with typed models, cursor pagination helpers, `AbortSignal` / socket timeouts, exponential backoff retries on `429`/`5xx`, and RFC 7807 `DatapiAPIError` exceptions.
- **Consumer AST Code Patcher (`datapi/patcher.py`, `datapi patch`)**:
  - Rewrites downstream `.py`, `.ts`, `.tsx`, `.js`, and `.jsx` consumer files on schema renames/removals with dry-run unified diffs by default and `ast.parse()` syntax validation before disk writes.
- **Multi-Cloud Deployment Bundles (`datapi/deployer.py`, `datapi deploy`)**:
  - Generates production manifests for **Google Cloud Run v2** (`terraform/main.tf`), **AWS App Runner** (`terraform/aws_apprunner.tf`), and **Fly.io** (`fly.toml`).
- **Governance & Architectural Documentation**:
  - Added `SECURITY.md`, `AGENTS.md`, `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/dependabot.yml`, and `docs/adr/0001-deterministic-codegen-and-zero-dep-core.md`.

### Security
- **AWS App Runner Secret Hygiene**: Replaced plaintext placeholder environment variables in `terraform/aws_apprunner.tf` with a `sensitive = true` `api_key` Terraform variable (no default value) backed by `aws_secretsmanager_secret`, `runtime_environment_secrets`, and a least-privilege `secretsmanager:GetSecretValue` App Runner instance IAM role—matching GCP Cloud Run Secret Manager parity.
- **Strict CORS Defaults**: Generated FastAPI apps and Studio templates read `CORS_ALLOW_ORIGINS` and never combine `allow_origins=["*"]` with `allow_credentials=True`.
- **Analytics SQL Identifier Allowlisting & Auth Parity**: `synthesize_summary_sql()`, `synthesize_timeseries_sql()`, and generated `/analytics/*` endpoints validate column/interval identifiers against inferred schema allowlists and enforce `Depends(verify_api_key)` when `--auth` is enabled.
- **CI Action Pinning**: Pinned GitHub Actions in `.github/workflows/ci.yml` and `.github/actions/datapi-action/action.yml` to immutable 40-character commit SHAs.

---

## [0.1.0] - 2026-10-29

### Added
- **Zero-Dependency Inference Engine**:
  - Ingests CSV, JSON, and SQLite data sources.
  - Automatically classifies types (`int`, `float`, `bool`, `date`, `datetime`, `str`, `uuid`, `email`).
  - Detects primary keys (`id`, `{resource}_id`, UUIDs) and enum candidates.
- **Production FastAPI Code Generator**:
  - Emits Pydantic v2 schemas (`Create`, `Update`, `Response`, `ListResponse`).
  - Implements complete REST CRUD (`GET /resources`, `GET /resources/{id}`, `POST`, `PATCH`, `DELETE`).
  - Built-in pagination (`limit`, `offset`) and free-text search (`?q=`).
  - `/healthz` liveness probes for container platforms.
- **Turnkey API Key Authentication**:
  - Injects `X-API-Key` FastAPI security dependencies (`--auth`).
  - Automatically provisions Google Secret Manager resources and Cloud Run IAM bindings.
- **Synthetic Mock Data Synthesizer**:
  - Generates realistic, schema-valid mock records (`--mock <count>`) for client demos.
- **Automated Pytest Contract Suite**:
  - Generates `tests/test_api.py` validating OpenAPI compliance and CRUD status codes.
- **Infrastructure as Code (Terraform)**:
  - Provisions Google Cloud Run v2 services with automatic scaling and zero-downtime rollback probes.
  - Google Artifact Registry container integration.
- **CLI Interface**:
  - `datapi inspect` (`apigen inspect`): Visual terminal table of inferred schema, types, and primary keys.
  - `datapi generate` (`apigen generate`): Generates production microservice codebase in < 50ms.
  - `datapi studio` (`apigen studio`): Serves the bundled in-browser Studio (`datapi/studio/index.html`), bound to `127.0.0.1` by default (`--host`, `--port`, `--no-open`).
- **Datapi Studio (Interactive Web UI)**:
  - Zero-setup in-browser schema inference, live request simulator, code previews (FastAPI, TypeScript SDK, Terraform), cURL copy, and ZIP export.
- **Typed TypeScript Client SDK (`sdk/client.ts`)** and **Scalar API reference** (`/scalar`) in generated services.
- **Self-Maintaining API Diff & Drift Detection Engine (`datapi/diff.py`)**:
  - Diffs two schema snapshots or datasets to detect breaking vs. non-breaking changes.
  - Detects added/removed fields, type modifications, nullability changes, PK alterations, and enum drift.
- **Autonomous Pull Request Markdown Generator (`datapi/patcher.py`)**:
  - Automatically synthesizes GitHub PR descriptions with actionable impact summaries and migration steps.

### Security
- Generated `--auth` services fail closed: `503` when `API_KEY` is unset, constant-time key comparison, `401` on missing/invalid keys. No default API key is embedded.
- Generated Terraform takes the API key from a `sensitive` `api_key` variable instead of a hardcoded value.
- Generated Dockerfile runs as a non-root user; test-only dependencies moved to `requirements-dev.txt`.

### Fixed
- `--mock` seed data is emitted as Python literals (previously `true`/`false` broke the generated app's import).
- Email and UUID string formats are preserved during inference.
- `bin/datapi`, `bin/apigen`, `datapi.py`, and `apigen.py` work from any working directory; Studio is included in the installed package.

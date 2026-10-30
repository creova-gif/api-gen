# Changelog

All notable changes to **APIGen** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
  - `apigen inspect`: Visual terminal table of inferred schema, types, and primary keys.
  - `apigen generate`: Generates 6-file production codebase in < 50ms.
  - `apigen studio`: Serves the bundled in-browser Studio (`apigen/studio/index.html`), bound to `127.0.0.1` by default (`--host`, `--port`, `--no-open`).
- **APIGen Studio (Interactive Web UI)**:
  - Zero-setup in-browser schema inference, live request simulator, code previews (FastAPI, TypeScript SDK, Terraform), cURL copy, and ZIP export.
- **Typed TypeScript Client SDK (`sdk/client.ts`)** and **Scalar API reference** (`/scalar`) in generated services.
- **Self-Maintaining API Diff & Drift Detection Engine (`apigen/diff.py`)**:
  - Diffs two schema snapshots or datasets to detect breaking vs. non-breaking changes.
  - Detects added/removed fields, type modifications, nullability changes, PK alterations, and enum drift.
- **Autonomous Pull Request Markdown Generator (`apigen/patcher.py`)**:
  - Automatically synthesizes GitHub PR descriptions with actionable impact summaries and migration steps.
- **CLI Subcommand `apigen diff`**:
  - Added `-a/--old` and `-b/--new` comparison with optional `-p/--pr` automated PR output.
- **Comprehensive Unit Tests**:
  - Added test coverage for breaking and backward-compatible schema changes.

### Security
- Generated `--auth` services fail closed: `503` when `API_KEY` is unset, constant-time key comparison, `401` on missing/invalid keys. No default API key is embedded.
- Generated Terraform takes the API key from a `sensitive` `api_key` variable instead of a hardcoded value.
- Generated Dockerfile runs as a non-root user; test-only dependencies moved to `requirements-dev.txt`.

### Fixed
- `--mock` seed data is emitted as Python literals (previously `true`/`false` broke the generated app's import).
- Email and UUID string formats are preserved during inference.
- `bin/apigen` and `apigen.py` work from any working directory; Studio is now included in the installed package.

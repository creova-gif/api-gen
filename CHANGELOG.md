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

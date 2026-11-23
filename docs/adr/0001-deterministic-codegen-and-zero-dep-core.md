# ADR 0001: Deterministic Code Generation over Runtime Proxy Reflection & Zero-Dependency Compiler Core

- **Status:** Accepted
- **Date:** 2026-11-22
- **Owner:** Justin Mafie (`@creova-gif`)

---

## Context

Enterprise solutions architects, forward-deployed engineers, and backend teams frequently need to expose legacy or flat-file datasets (`.csv`, `.json`, `.sqlite`, relational directory dumps) as authenticated, documented REST APIs deployed on cloud container runtimes (Google Cloud Run, Fly.io, AWS App Runner).

Existing "data-to-API" platforms (such as Hasura, PostgREST, or BaaS proxies) introduce an opaque runtime middleware proxy that reflects over a live database connection at request time. Enterprise security and platform engineering teams routinely reject these proxy layers because:
1. They cannot be statically audited, type-checked, or diffed in pull requests like standard application source code.
2. Adding custom endpoint logic, custom auth guards, or bespoke validation rules requires escaping the proxy layer.
3. Heavy CLI generators with dozens of transitive dependencies break in restricted corporate Python environments or CI runners.

---

## Decision

1. **Deterministic Source-to-Source Code Generation over Runtime Reflection:**
   - `datapi` (`apigen`) operates as a deterministic compiler (`datapi/infer.py -> datapi/planner.py -> datapi/generator.py`) rather than a runtime proxy.
   - Given a raw dataset, it emits human-readable, git-committable source code: a **FastAPI + Pydantic v2** service (`app/main.py`), a strict **OpenAPI 3.1.0** specification (`openapi.json`), a **Pytest** contract suite (`tests/test_api.py`), typed **TypeScript and Python SDKs** (`sdk/client.ts`, `sdk/client.py`), a non-root **Dockerfile**, and **Terraform / multi-cloud IaC bundles**.

2. **Zero-Dependency Python Standard Library Compiler Core:**
   - The `datapi` compiler package itself has `dependencies = []` in `pyproject.toml`, relying exclusively on Python 3.10+ standard library modules (`csv`, `json`, `sqlite3`, `ast`, `http.server`).
   - Third-party runtime packages (`fastapi`, `uvicorn`, `pydantic`, `httpx`, `pytest`) are required only inside the *generated* microservice (`requirements.txt` / `requirements-dev.txt`) and in optional test extras (`pip install ".[test]"`).

3. **OpenAPI 3.1.0 Contract-First Output & AST-Guided Evolution (`diff` / `patch`):**
   - Schema changes between dataset versions are computed deterministically (`datapi diff`) and classified into breaking vs. non-breaking changes.
   - Consumer codebases (`.py`, `.ts`, `.tsx`) are updated via deterministic AST/token rewriting (`datapi patch`) with dry-run unified diffs by default.

4. **Dual CLI Entrypoint Compatibility (`datapi` and `apigen`):**
   - To preserve backwards compatibility across existing CI pipelines and scripts after the rebrand from `apigen` to `datapi`, both `datapi` and `apigen` console scripts (`pyproject.toml`, `datapi.py`, `apigen.py`, `bin/`) route to `datapi.cli:main`.

---

## Consequences

### Positive
- **Zero Vendor Lock-In:** Teams own 100% of the generated FastAPI, Pydantic v2, Dockerfile, and Terraform code and can eject or customize at any time.
- **Instant Install & Air-Gapped Execution:** Installing `datapi` requires zero third-party packages and runs offline in milliseconds.
- **Fail-Closed Security by Default:** Generated `--auth` services return `503` if `API_KEY` is unconfigured and `401` on invalid `X-API-Key`, and run as a non-root user inside Docker.

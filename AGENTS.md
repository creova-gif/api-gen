# Repository Engineering & AI Agent Contract (`AGENTS.md`)

Project facts, stack, and verification gates are declared in [`.ai/project.yaml`](.ai/project.yaml). Claude Code users: see [`CLAUDE.md`](CLAUDE.md).

## 1. Decision Hierarchy
1. **Verified Repository State:** Actual source code (`datapi/`), passing tests (`tests/`), and live CI workflows (`.github/workflows/ci.yml`).
2. **Accepted ADRs:** Architectural invariants recorded in [`docs/adr/`](docs/adr/0001-deterministic-codegen-and-zero-dep-core.md).
3. **Repository-Specific Constraints:** Rules in this file and [`.ai/project.yaml`](.ai/project.yaml).
4. **Shared Engineering Governance Standard (`v1.0`):** Portfolio-wide security, epistemic honesty, and PR verification rules.

## 2. Hard Invariants for All Agents (Antigravity, Devin, Claude, Codex, GStack)
- **Epistemic Honesty:** Never claim a feature, data adapter, cloud target, or runtime capability is implemented unless backed by real code and automated tests. Distinguish zero-dependency stdlib features, optional extras (`datapi[analytics]`), and planned roadmap items explicitly.
- **Zero-Dependency Core Lock:** Keep `dependencies = []` in `pyproject.toml`. Optional capabilities (such as `duckdb` for Parquet ingestion and OLAP acceleration) belong strictly under `[project.optional-dependencies]`, with clean stdlib fallbacks or explicit error messages when absent.
- **No Harness or Asset Pollution:** Never commit `.claude/`, `.agents/`, `.cursor/`, `gstack/`, `attached_assets/`, `mockup-sandbox/`, `archive/`, `dist/`, `test_api*/`, or `.env` files.
- **Security Fail-Closed:**
  - Never introduce fallback/placeholder API keys in generated FastAPI code or Terraform (`variable "api_key"` must stay `sensitive = true` with no default value, wired to GCP Secret Manager / AWS Secrets Manager).
  - Never combine wildcard CORS (`allow_origins=["*"]`) with `allow_credentials=True`.
  - Validate all SQL column/table identifiers against schema allowlists before synthesizing DuckDB/SQLite queries, and keep all data values parameterized.
  - Preserve `ast.parse()` validation before writing any patched Python source in `datapi/patcher.py`.
- **PR & Verification Discipline:** Place imports at module top. Author commits using `Justin Mafie <244837074+creova-gif@users.noreply.github.com>`, follow Conventional Commits on feature branches (never commit directly to `main`), and run every configured verification gate in `.ai/project.yaml` before opening a pull request.

## 3. Verification Gates
Run all gates from the repository root (if a gate cannot run, report `NOT VERIFIED` with the reason):
```bash
pip install -e ".[test]"
pip install ruff
ruff check --select E9,F datapi datapi.py apigen.py tests
python3 -m compileall -q datapi datapi.py apigen.py tests
python3 -m unittest discover -s tests -v
```

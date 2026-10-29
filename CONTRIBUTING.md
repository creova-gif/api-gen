# Contributing to APIGen

We welcome contributions to APIGen! Whether you are adding a new schema parser, expanding infrastructure targets, or improving documentation, here is how to get started.

---

## Development Setup

APIGen is built with **zero external dependencies** for the core generator itself (using Python's standard library `csv`, `json`, `sqlite3`, `dataclasses`, and `argparse`).

1. **Clone the repository:**
   ```bash
   git clone https://github.com/creova-gif/api-gen.git
   cd api-gen
   ```

2. **Verify tests pass:**
   ```bash
   python3 -m unittest discover -s tests -v
   ```

3. **Install in editable mode (optional):**
   ```bash
   pip install -e .
   ```

---

## Architectural Principles

1. **Zero Runtime Dependencies for the Generator**: The CLI and inference engine must run on standard Python without requiring `pip install` before generation.
2. **Inspectable Code Generation Over Black Boxes**: APIGen emits clean, human-readable FastAPI and Terraform code that developers can version control, review, and extend. We do not build opaque runtime proxies.
3. **100% Test Backed**: Every new endpoint or generator capability must be accompanied by corresponding unit tests in `tests/test_apigen.py`.

---

## Submitting Changes

1. Fork the repository and create a descriptive branch: `git checkout -b feat/duckdb-inference`.
2. Ensure existing tests pass: `python3 -m unittest discover -s tests`.
3. Add tests covering any new behavior or bugfixes.
4. Open a Pull Request with a clear summary of the change and rationale.

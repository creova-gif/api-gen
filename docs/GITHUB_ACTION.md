# datapi GitHub Action: CI/CD Data-as-Code Automation
*Continuous Schema Verification, Drift Detection, and Production API Generation in 3 Lines of YAML.*

---

## 1. The 3-Line Promise

Turn any CSV, JSON, Parquet, or SQLite dataset into a self-maintaining, continuously tested REST API inside your GitHub Actions pipeline:

```yaml
- name: Generate & Verify Data API
  uses: datapi-dev/datapi-action@v1
  with:
    data-file: data/customers.csv
```

With just those three lines, every commit or pull request automatically:
1. **Inspects** the incoming data and infers strict Pydantic schemas, primary keys, and types.
2. **Diffs** against your baseline schema (when configured) to detect breaking changes and post automated PR review comments.
3. **Generates** a production FastAPI service, OpenAPI 3.1 spec, TypeScript SDK, and Terraform configs.
4. **Executes** Pytest contract tests to guarantee zero regressions before merging.

---

## 2. Architecture & Pipeline Lifecycle

The `datapi-action` encapsulates the entire Data-to-API lifecycle into a unified composite action:

```
+---------------------------------------------------------------------------------------------------------+
|                                  datapi GitHub Actions Workflow                                         |
|                                                                                                         |
|   +-------------------+    +--------------------+    +--------------------+    +--------------------+   |
|   | 1. Setup & Ingest |    | 2. Drift & Diff    |    | 3. Code Generation |    | 4. Contract Tests  |   |
|   |-------------------|    |--------------------|    |--------------------|    |--------------------|   |
|   | • Python 3.11     | -> | • Compare baseline | -> | • FastAPI service  | -> | • Pytest suite     |   |
|   | • datapi inspect  |    | • Flag breaking    |    | • OpenAPI 3.1 spec |    | • Schema check     |   |
|   | • Parse fields    |    | • PR Comment & Sum |    | • TypeScript SDK   |    | • Auth validation  |   |
|   +-------------------+    +--------------------+    +--------------------+    +--------------------+   |
+---------------------------------------------------------------------------------------------------------+
```

---

## 3. End-to-End Workflow Recipes

### Recipe 1: Pull Request Schema Gate (Block Breaking Drift)

Place this workflow in `.github/workflows/data-contracts.yml`. It compares incoming data against the `main` branch baseline, writes an automated PR review comment, and fails if breaking changes are introduced:

```yaml
name: Data Contract Gate

on:
  pull_request:
    paths:
      - 'data/**'
      - '.github/workflows/data-contracts.yml'

jobs:
  contract-gate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write # Required for automated PR comments

    steps:
      - name: Checkout Current PR Branch
        uses: actions/checkout@v4

      - name: Fetch Baseline Data from Main
        run: |
          git fetch origin main:main
          git show main:data/customers.csv > /tmp/customers_baseline.csv || true

      - name: Run datapi Contract Verification
        uses: datapi-dev/datapi-action@v1
        with:
          data-file: data/customers.csv
          old-schema: /tmp/customers_baseline.csv
          fail-on-breaking: 'true'
          auth: 'true'
          output-dir: ./build/api
```

---

### Recipe 2: Nightly Regeneration & Client SDK Publishing

Automatically regenerate the API specification, compile the zero-dependency TypeScript SDK, and upload the build artifacts:

```yaml
name: Generate & Publish API Artifacts

on:
  push:
    branches: [ main ]
    paths:
      - 'data/**'
  workflow_dispatch:

jobs:
  build-and-package:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Generate API Microservice
        id: datapi
        uses: datapi-dev/datapi-action@v1
        with:
          data-file: data/inventory.json
          output-dir: ./dist/inventory-service
          auth: 'true'
          mock-count: '50'

      - name: Upload OpenAPI Spec & TypeScript SDK
        uses: actions/upload-artifact@v4
        with:
          name: api-artifacts
          path: |
            ${{ steps.datapi.outputs.api-directory }}/openapi.json
            ${{ steps.datapi.outputs.api-directory }}/sdk/client.ts
            ${{ steps.datapi.outputs.api-directory }}/terraform/main.tf
```

---

### Recipe 3: GitOps Automated Cloud Run Deployment

Take raw data in a commit, generate the microservice container, and deploy directly to Google Cloud Run:

```yaml
name: Deploy Data API to Cloud Run

on:
  push:
    branches: [ main ]
    paths:
      - 'data/transactions.csv'

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Synthesize Tested Microservice
        uses: datapi-dev/datapi-action@v1
        with:
          data-file: data/transactions.csv
          output-dir: ./dist/transactions-api
          auth: 'true'

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Build & Deploy Container to Cloud Run
        run: |
          cd ./dist/transactions-api
          gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT }}/transactions-api:latest
          gcloud run deploy transactions-api \
            --image gcr.io/${{ secrets.GCP_PROJECT }}/transactions-api:latest \
            --platform managed \
            --region us-central1 \
            --allow-unauthenticated
```

---

## 4. Inputs Reference

| Input | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `data-file` | **Yes** | — | Path to primary data file (`.csv`, `.json`, `.sqlite`, `.parquet`). |
| `output-dir` | No | `./generated-api` | Destination directory where the complete API codebase will be written. |
| `fail-on-breaking` | No | `true` | When `true`, halts the workflow with an exit code 1 if breaking changes are detected against `old-schema`. |
| `auth` | No | `false` | When `true`, secures all endpoints with `X-API-Key` header authentication. |
| `old-schema` | No | `""` | Path to baseline data file or schema. When provided, triggers `datapi diff`. |
| `resource-name` | No | `""` | Override the inferred resource name (e.g. `customer`, `transaction`). |
| `python-version` | No | `3.11` | Python version for virtual environment execution. |
| `mock-count` | No | `10` | Number of synthetic records generated for testing and seeding. |

---

## 5. Outputs Reference

| Output | Type | Description |
| :--- | :---: | :--- |
| `api-directory` | `string` | Resolved path to the generated API codebase. |
| `has-breaking-changes` | `boolean` | `true` if breaking changes were detected against `old-schema`, otherwise `false`. |

---

## 6. How Contract Testing Works

Every generated API includes a complete Pytest contract test suite located in `${output-dir}/tests/test_api.py`. The action automatically runs these tests with the following guarantees:

1. **Schema Integrity:** Verifies that returned payloads strictly match the inferred Pydantic models.
2. **Status Codes:** Asserts that collection queries return `200 OK`, inserts return `201 Created`, and invalid requests return `422 Unprocessable Entity` formatted per RFC 7807.
3. **Security Boundaries:** When `auth: 'true'` is specified, tests verify that missing or incorrect `X-API-Key` headers receive immediate `401 Unauthorized` rejections.
4. **Keyset Pagination:** Validates cursor decoding, boundary slicing, and `next_cursor` token emission.

---

## 7. Sample Automated Pull Request Comment

When `old-schema` is configured, `datapi diff` automatically drafts a review comment on the open Pull Request:

> ### 🚨 Datapi Schema Drift Report: Breaking Changes Detected
> 
> **Resource:** `customer`  
> **Status:** 🚨 **1 breaking change**, 1 non-breaking change.
> 
> | Severity | Change Type | Field | Migration Advice |
> | :--- | :--- | :--- | :--- |
> | `[BREAKING]` | `FIELD_REMOVED` | `phone_number` | Existing consumers expecting `phone_number` will fail. Deprecate before deletion. |
> | `[NON_BREAKING]` | `FIELD_ADDED` | `account_tier` | Added with default `standard`. Backward-compatible. |
> 
> *Generated by [datapi-action](https://github.com/datapi-dev/datapi-action)*

---

## 8. Summary

By treating data schemas as code in your CI/CD pipeline, `datapi` eliminates manual API boilerplate, prevents uncoordinated breaking changes from hitting production, and guarantees contract fidelity across your engineering organization.

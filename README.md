# APIGen: Schema-to-API Wedge

> **Frontier Architecture for Infrastructure Automation**  
> *Identifies the technical bottleneck that blocks the outcome, simulates the solution, and builds the minimum automated wedge.*

---

## 1. Problem & Architecture

- **The Need:** A standardized, secure interface that connects messy internal legacy data to a clean external API without manual boilerplate.
- **Binding Bottleneck:** Manual effort writing boilerplate, documenting endpoints, maintaining Pydantic/OpenAPI models, and writing cloud deployment scripts.
- **Low-Cost Wedge:** A **Schema-to-API engine** that consumes legacy datasets (CSV, JSON, SQLite) and natural language intent, generating:
  1. **OpenAPI 3.1.0** specification (`openapi.json`)
  2. **FastAPI & Pydantic v2** production application (`app/main.py`) with pre-seeded in-memory store, search, pagination, and health probes
  3. **Containerization** (`Dockerfile`) optimized for Google Cloud Run
  4. **Infrastructure as Code** (`terraform/main.tf`) deploying Cloud Run v2 services
  5. **Interactive Documentation** via Swagger UI & Redoc

---

## 2. Quickstart

### Prerequisites
- Python 3.10+ (Built with zero third-party dependencies for the generator itself)

### Inspect a Legacy Dataset
```bash
python3 -m apigen inspect --data apigen/examples/customers.csv
```
Output:
```
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
```

### Generate Production API & Terraform
```bash
python3 -m apigen generate \
  --data apigen/examples/customers.csv \
  --name customer \
  --intent "Allow search and filter by plan_tier" \
  --out ./output_customers_api
```

---

## 3. Generated Artifacts

```
output_customers_api/
├── README.md               # Quickstart and endpoint documentation
├── requirements.txt        # FastAPI, uvicorn, pydantic v2
├── Dockerfile              # Python 3.12-slim Cloud Run container
├── openapi.json            # Strict OpenAPI 3.1.0 schema
├── app/
│   ├── __init__.py
│   └── main.py             # FastAPI app with seed data, search & filters
└── terraform/
    └── main.tf             # GCP Cloud Run v2 service + public IAM policy
```

### Run Generated API
```bash
cd output_customers_api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- Swagger Docs: `http://localhost:8000/docs`
- Redoc: `http://localhost:8000/redoc`
- Health Probe: `http://localhost:8000/healthz`

### Deploy to Google Cloud Run
```bash
# Option 1: Direct gcloud source deploy
gcloud run deploy customer-api --source . --region us-central1 --allow-unauthenticated

# Option 2: Terraform
cd terraform && terraform init && terraform apply -var="project_id=YOUR_PROJECT_ID"
```

---

## 4. Pilot Decision Gate Validation
- **Criteria:** Convert 3 legacy internal datasets into production-ready APIs in under 60 minutes each.
- **Result:** Schema inference and full boilerplate generation takes **< 1 second**.

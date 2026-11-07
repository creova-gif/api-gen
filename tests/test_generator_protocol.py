"""
Protocol & Backend Architecture tests for Datapi generator.
Tests RFC 7807 Problem Details, Cursor Pagination, Idempotency-Key headers,
and financial Decimal type handling.
"""

import ast
import base64
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

from fastapi.testclient import TestClient

from datapi.infer import FieldDef, SchemaDef, infer_schema_from_records
from datapi.planner import create_api_plan
from datapi.generator import generate_project, _is_decimal_field


class TestGeneratorProtocol(unittest.TestCase):
    def setUp(self):
        self.sample_records = [
            {"id": 1, "title": "Widget Alpha", "price": 19.99, "account_balance": 100.50},
            {"id": 2, "title": "Widget Beta", "price": 29.99, "account_balance": 250.00},
            {"id": 3, "title": "Widget Gamma", "price": 39.99, "account_balance": 75.25},
            {"id": 4, "title": "Widget Delta", "price": 49.99, "account_balance": 500.00},
            {"id": 5, "title": "Widget Epsilon", "price": 59.99, "account_balance": 0.00},
        ]
        self.schema = infer_schema_from_records(self.sample_records, resource_name="widget")

    def _generate_and_load_app(self, plan):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_project(plan, out_path)
            with open(files["app/main.py"], "r", encoding="utf-8") as f:
                code = f.read()

        # Verify syntactically valid python AST
        tree = ast.parse(code)
        self.assertIsNotNone(tree)

        mod = {}
        exec(compile(code, "app_main_test", "exec"), mod)
        return mod["app"], code

    def test_ast_parse_and_syntax_validation(self):
        plan = create_api_plan(self.schema, intent="Generate complete API", auth_enabled=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            files = generate_project(plan, Path(tmpdir))
            with open(files["app/main.py"], "r", encoding="utf-8") as f:
                code = f.read()

        tree = ast.parse(code)
        self.assertTrue(isinstance(tree, ast.Module))
        self.assertIn("from decimal import Decimal", code)
        self.assertIn("application/problem+json", code)
        self.assertIn("Idempotency-Key", code)
        self.assertIn("cursor", code)

    def test_rfc7807_problem_details_handlers(self):
        plan = create_api_plan(self.schema, intent="Support error reporting", auth_enabled=False)
        app, code = self._generate_and_load_app(plan)
        client = TestClient(app)

        # Verify handlers exist in code
        self.assertIn("http_exception_handler", code)
        self.assertIn("validation_exception_handler", code)
        self.assertIn('media_type="application/problem+json"', code)

        # 1. Test 404 HTTPException
        res404 = client.get("/widgets/999999")
        self.assertEqual(res404.status_code, 404)
        self.assertEqual(res404.headers.get("content-type"), "application/problem+json")
        body404 = res404.json()
        self.assertEqual(body404["status"], 404)
        self.assertEqual(body404["title"], "Not Found")
        self.assertEqual(body404["type"], "urn:problem-type:not-found")
        self.assertEqual(body404["instance"], "/widgets/999999")
        self.assertIn("detail", body404)

        # 2. Test 422 RequestValidationError (invalid payload type)
        res422 = client.post("/widgets", json={"price": "not_a_valid_number"})
        self.assertEqual(res422.status_code, 422)
        self.assertEqual(res422.headers.get("content-type"), "application/problem+json")
        body422 = res422.json()
        self.assertEqual(body422["status"], 422)
        self.assertEqual(body422["title"], "Unprocessable Entity")
        self.assertEqual(body422["type"], "urn:problem-type:validation-error")
        self.assertEqual(body422["instance"], "/widgets")
        self.assertIn("detail", body422)

        # 3. Test 400 Bad Request on invalid cursor token
        res400 = client.get("/widgets?cursor=invalid-non-base64-token-$$$")
        self.assertEqual(res400.status_code, 400)
        self.assertEqual(res400.headers.get("content-type"), "application/problem+json")
        body400 = res400.json()
        self.assertEqual(body400["status"], 400)
        self.assertEqual(body400["title"], "Bad Request")
        self.assertEqual(body400["instance"], "/widgets")

    def test_cursor_pagination_metadata_and_navigation(self):
        plan = create_api_plan(self.schema, intent="Support cursor navigation", auth_enabled=False)
        app, _ = self._generate_and_load_app(plan)
        client = TestClient(app)

        # First page (limit=2)
        res_page1 = client.get("/widgets?limit=2")
        self.assertEqual(res_page1.status_code, 200)
        data1 = res_page1.json()

        self.assertIn("items", data1)
        self.assertEqual(len(data1["items"]), 2)
        self.assertEqual(data1["total"], 5)
        self.assertTrue(data1["has_more"])
        self.assertIsNotNone(data1["next_cursor"])

        # Validate base64 decoded cursor token
        token1 = data1["next_cursor"]
        decoded_payload = json.loads(base64.b64decode(token1.encode("utf-8")).decode("utf-8"))
        self.assertIn("id", decoded_payload)
        self.assertEqual(str(decoded_payload["id"]), str(data1["items"][-1]["id"]))

        # Second page using cursor
        res_page2 = client.get(f"/widgets?limit=2&cursor={token1}")
        self.assertEqual(res_page2.status_code, 200)
        data2 = res_page2.json()

        self.assertEqual(len(data2["items"]), 2)
        self.assertTrue(data2["has_more"])
        self.assertIsNotNone(data2["next_cursor"])
        # Verify keyset filtered (id > last_id)
        self.assertGreater(int(data2["items"][0]["id"]), int(data1["items"][-1]["id"]))

        # Third page using cursor (exhaustion)
        token2 = data2["next_cursor"]
        res_page3 = client.get(f"/widgets?limit=2&cursor={token2}")
        self.assertEqual(res_page3.status_code, 200)
        data3 = res_page3.json()

        self.assertEqual(len(data3["items"]), 1)
        self.assertFalse(data3["has_more"])
        self.assertIsNone(data3["next_cursor"])

    def test_sorting_ascending_and_descending(self):
        plan = create_api_plan(self.schema, intent="Support sorting", auth_enabled=False)
        app, _ = self._generate_and_load_app(plan)
        client = TestClient(app)

        # Ascending sort by price
        res_asc = client.get("/widgets?sort=price&limit=5")
        self.assertEqual(res_asc.status_code, 200)
        prices_asc = [float(x["price"]) for x in res_asc.json()["items"]]
        self.assertEqual(prices_asc, sorted(prices_asc))

        # Descending sort with leading '-'
        res_desc = client.get("/widgets?sort=-price&limit=5")
        self.assertEqual(res_desc.status_code, 200)
        prices_desc = [float(x["price"]) for x in res_desc.json()["items"]]
        self.assertEqual(prices_desc, sorted(prices_desc, reverse=True))

    def test_idempotency_key_caching_and_replay(self):
        plan = create_api_plan(self.schema, intent="Enable create", auth_enabled=False)
        app, _ = self._generate_and_load_app(plan)
        client = TestClient(app)

        # Baseline count
        initial_list = client.get("/widgets")
        initial_count = len(initial_list.json()["items"])

        idemp_key = "idemp-req-unique-9988"
        new_payload = {"title": "Idempotent Item", "price": 79.99, "account_balance": 150.00}

        # First request with Idempotency-Key
        res1 = client.post("/widgets", json=new_payload, headers={"Idempotency-Key": idemp_key})
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res1.headers.get("x-cache-lookup"), "MISS")
        created_record = res1.json()
        new_id = created_record["id"]

        # Replay request with identical Idempotency-Key
        res2 = client.post("/widgets", json=new_payload, headers={"Idempotency-Key": idemp_key})
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res2.headers.get("x-cache-lookup"), "HIT")
        replayed_record = res2.json()
        self.assertEqual(replayed_record["id"], new_id)
        self.assertEqual(replayed_record["title"], "Idempotent Item")

        # Verify database only grew by 1, not 2
        after_list = client.get("/widgets")
        self.assertEqual(len(after_list.json()["items"]), initial_count + 1)

    def test_financial_decimal_support(self):
        custom_fields = [
            FieldDef(name="id", python_type="int", openapi_type="integer", is_primary_key=True),
            FieldDef(name="unit_price", python_type="float", openapi_type="number"),  # matches 'price'
            FieldDef(name="transfer_amount", python_type="float", openapi_type="number"),  # matches 'amount'
            FieldDef(name="opening_balance", python_type="float", openapi_type="number"),  # matches 'balance'
            FieldDef(name="currency_rate", python_type="float", openapi_type="number"),  # matches 'currency'
            FieldDef(name="vat_fee", python_type="float", openapi_type="number", openapi_format="decimal"),
            FieldDef(name="service_tax", python_type="Decimal", openapi_type="number"),
        ]
        schema = SchemaDef(
            resource_name="invoice",
            plural_name="invoices",
            fields=custom_fields,
            primary_key="id",
            sample_records=[{
                "id": 1,
                "unit_price": 12.34,
                "transfer_amount": 56.78,
                "opening_balance": 90.12,
                "currency_rate": 1.05,
                "vat_fee": 3.45,
                "service_tax": 2.10,
            }]
        )

        for f in custom_fields[1:]:
            self.assertTrue(_is_decimal_field(f), f"Field {f.name} should be recognized as Decimal")

        plan = create_api_plan(schema, intent="Support financial invoices", auth_enabled=False)
        app, code = self._generate_and_load_app(plan)

        # Check model declarations in generated code
        self.assertIn("unit_price: Decimal", code)
        self.assertIn("transfer_amount: Decimal", code)
        self.assertIn("opening_balance: Decimal", code)
        self.assertIn("currency_rate: Decimal", code)
        self.assertIn("vat_fee: Decimal", code)
        self.assertIn("service_tax: Decimal", code)

        client = TestClient(app)
        res = client.get("/invoices/1")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["unit_price"], "12.34")
        self.assertEqual(data["transfer_amount"], "56.78")


if __name__ == "__main__":
    unittest.main()

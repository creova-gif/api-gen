"""
End-to-End Integration Test Suite for Datapi.
Tests multi-table schema inference across realistic relational datasets in examples/,
microservice project synthesis (FastAPI app, TypeScript SDK, Python SDK, OpenAPI spec),
turnkey DuckDB analytics execution, and automated drift detection & PR generation.
"""

import ast
import tempfile
import unittest
from pathlib import Path

from datapi.analytics import (
    DuckDBAnalyticsEngine,
    generate_duckdb_analytics_code,
)
from datapi.diff import diff_schemas
from datapi.generator import _is_decimal_field, generate_project
from datapi.infer import (
    ForeignKeyDef,
    infer_from_directory,
    infer_from_file,
)
from datapi.patcher import generate_pr_markdown
from datapi.planner import create_api_plan


class TestE2EIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Resolve repository root and examples directory
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.examples_dir = cls.repo_root / "examples"

    def test_multi_table_schema_inference_across_examples(self):
        """
        Verify multi-table schema inference across examples/:
        - Calls infer_from_directory("examples")
        - Asserts discovered foreign key: orders.customer_id -> customers.customer_id
        - Asserts precise type detections:
            - Decimal/float for prices (total_amount, unit_price)
            - Datetime/date for order_date
            - Booleans for flags (is_expedited, is_active)
            - Enums for low-cardinality categoricals (status, payment_method, category)
        """
        schemas = infer_from_directory(self.examples_dir)
        schema_map = {s.resource_name: s for s in schemas}

        self.assertIn("customer", schema_map, "Customers table must be inferred")
        self.assertIn("order", schema_map, "Orders table must be inferred")
        self.assertIn("product", schema_map, "Products table must be inferred")

        customer_schema = schema_map["customer"]
        order_schema = schema_map["order"]
        product_schema = schema_map["product"]

        # 1. Assert Discovered Foreign Key: orders.customer_id -> customers.customer_id
        order_fk = next(
            (fk for fk in order_schema.foreign_keys if fk.field_name == "customer_id"),
            None,
        )
        self.assertIsNotNone(order_fk, "Foreign key customer_id not found in order schema")
        self.assertIsInstance(order_fk, ForeignKeyDef)
        self.assertEqual(order_fk.field_name, "customer_id")
        self.assertEqual(order_fk.target_resource, "customer")
        self.assertEqual(order_fk.target_field, "customer_id")

        relational_link = (
            f"{order_schema.plural_name}.{order_fk.field_name} -> "
            f"{customer_schema.plural_name}.{order_fk.target_field}"
        )
        self.assertEqual(
            relational_link,
            "orders.customer_id -> customers.customer_id",
            "Relational foreign key link must resolve orders.customer_id -> customers.customer_id",
        )

        # 2. Assert Type Detections (Decimal/float for financial values)
        order_fields = {f.name: f for f in order_schema.fields}
        prod_fields = {f.name: f for f in product_schema.fields}

        # total_amount in orders
        self.assertIn("total_amount", order_fields)
        total_field = order_fields["total_amount"]
        self.assertEqual(total_field.python_type, "float")
        self.assertEqual(total_field.openapi_type, "number")
        self.assertTrue(_is_decimal_field(total_field), "total_amount must be recognized as Decimal financial field")

        # unit_price in products
        self.assertIn("unit_price", prod_fields)
        price_field = prod_fields["unit_price"]
        self.assertEqual(price_field.python_type, "float")
        self.assertEqual(price_field.openapi_type, "number")
        self.assertTrue(_is_decimal_field(price_field), "unit_price must be recognized as Decimal financial field")

        # 3. Assert Date / Datetime Detection
        self.assertIn("order_date", order_fields)
        order_date_field = order_fields["order_date"]
        self.assertIn(
            order_date_field.python_type,
            ("datetime", "date"),
            "order_date must be inferred as datetime or date",
        )
        self.assertIn(
            order_date_field.openapi_format,
            ("date-time", "date"),
            "order_date format must be date-time or date",
        )

        # 4. Assert Boolean Detection
        self.assertIn("is_expedited", order_fields)
        expedited_field = order_fields["is_expedited"]
        self.assertEqual(expedited_field.python_type, "bool")
        self.assertEqual(expedited_field.openapi_type, "boolean")

        self.assertIn("is_active", prod_fields)
        active_field = prod_fields["is_active"]
        self.assertEqual(active_field.python_type, "bool")
        self.assertEqual(active_field.openapi_type, "boolean")

        # 5. Assert Enum Detections
        # status in orders
        self.assertIn("status", order_fields)
        status_field = order_fields["status"]
        self.assertIsNotNone(status_field.enum_values, "status should be detected as enum")
        self.assertEqual(sorted(status_field.enum_values), ["completed", "pending", "refunded"])

        # payment_method in orders
        self.assertIn("payment_method", order_fields)
        pm_field = order_fields["payment_method"]
        self.assertIsNotNone(pm_field.enum_values, "payment_method should be detected as enum")
        self.assertEqual(sorted(pm_field.enum_values), ["card", "stripe", "wire"])

        # category in products
        self.assertIn("category", prod_fields)
        cat_field = prod_fields["category"]
        self.assertIsNotNone(cat_field.enum_values, "category should be detected as enum")
        self.assertEqual(sorted(cat_field.enum_values), ["apparel", "electronics", "software"])

    def test_full_project_synthesis_multi_table(self):
        """
        Verify complete microservice project synthesis across multi-table schemas:
        - Generates complete microservice project using generate_project()
        - Validates generated app/main.py parses with Python ast.parse
        - Validates generated sdk/client.ts contains methods and types for all entities
        - Validates generated sdk/client.py parses with ast.parse
        - Validates DuckDB analytical code generation executes against multi-table schema
        """
        schemas = infer_from_directory(self.examples_dir)
        plan = create_api_plan(schemas, intent="Full microservice API", auth_enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_project(plan, out_path)

            # Assert all core project artifacts generated
            self.assertIn("app/main.py", files)
            self.assertIn("sdk/client.ts", files)
            self.assertIn("sdk/client.py", files)
            self.assertIn("openapi.json", files)
            self.assertIn("Dockerfile", files)
            self.assertIn("requirements.txt", files)
            self.assertIn("terraform/main.tf", files)

            # 1. Validate app/main.py parses cleanly with ast.parse
            main_py_path = Path(files["app/main.py"])
            main_code = main_py_path.read_text(encoding="utf-8")
            main_tree = ast.parse(main_code)
            self.assertIsInstance(main_tree, ast.Module, "app/main.py must be a valid Python AST Module")

            # Verify entities are modeled in app/main.py
            self.assertIn("CustomerResponse", main_code)
            self.assertIn("OrderResponse", main_code)
            self.assertIn("ProductResponse", main_code)
            self.assertIn("/orders", main_code)
            self.assertIn("/products", main_code)
            self.assertIn("/customers", main_code)

            # 2. Validate sdk/client.ts contains methods and types for all entities
            ts_sdk_path = Path(files["sdk/client.ts"])
            ts_code = ts_sdk_path.read_text(encoding="utf-8")

            # Check TypeScript interfaces for all entities
            self.assertIn("export interface Customer", ts_code)
            self.assertIn("export interface Order", ts_code)
            self.assertIn("export interface Product", ts_code)
            self.assertIn("export interface CustomerCreateInput", ts_code)
            self.assertIn("export interface OrderCreateInput", ts_code)
            self.assertIn("export interface ProductCreateInput", ts_code)

            # Check typed methods for all entities
            self.assertIn("listCustomers", ts_code)
            self.assertIn("getCustomer", ts_code)
            self.assertIn("createCustomer", ts_code)
            self.assertIn("listOrders", ts_code)
            self.assertIn("getOrder", ts_code)
            self.assertIn("createOrder", ts_code)
            self.assertIn("listProducts", ts_code)
            self.assertIn("getProduct", ts_code)
            self.assertIn("createProduct", ts_code)

            # Check entity accessors
            self.assertIn("get orders()", ts_code)
            self.assertIn("get products()", ts_code)
            self.assertIn("get customers()", ts_code)

            # 3. Validate sdk/client.py parses cleanly with ast.parse
            py_sdk_path = Path(files["sdk/client.py"])
            py_sdk_code = py_sdk_path.read_text(encoding="utf-8")
            py_sdk_tree = ast.parse(py_sdk_code)
            self.assertIsInstance(py_sdk_tree, ast.Module, "sdk/client.py must be a valid Python AST Module")

            self.assertIn("def list_orders", py_sdk_code)
            self.assertIn("def get_order", py_sdk_code)
            self.assertIn("def list_products", py_sdk_code)
            self.assertIn("def get_product", py_sdk_code)

            # 4. Validate DuckDB analytical code generation executes against multi-table schema
            analytics_code = generate_duckdb_analytics_code(schemas)
            analytics_tree = ast.parse(analytics_code)
            self.assertIsInstance(analytics_tree, ast.Module, "Generated DuckDB analytics code must parse cleanly")

            # Execute analytics engine against orders
            order_schema = next(s for s in schemas if s.resource_name == "order")
            order_engine = DuckDBAnalyticsEngine(order_schema.sample_records, order_schema)

            order_summary = order_engine.summary(group_by="status")
            self.assertIn(order_summary["engine"], ("duckdb", "sqlite"))
            self.assertEqual(order_summary["resource"], "orders")
            self.assertGreater(len(order_summary["metrics"]), 0)
            status_map = {m["status"]: m["total_count"] for m in order_summary["metrics"]}
            self.assertIn("completed", status_map)
            self.assertIn("pending", status_map)

            order_ts = order_engine.timeseries(date_field="order_date", metric_field="total_amount")
            self.assertIn(order_ts["engine"], ("duckdb", "sqlite"))
            self.assertGreater(len(order_ts["timeseries"]), 0)
            first_period = order_ts["timeseries"][0]
            self.assertIn("cumulative_count", first_period)
            self.assertIn("sum_metric", first_period)

            # Execute analytics engine against products
            prod_schema = next(s for s in schemas if s.resource_name == "product")
            prod_engine = DuckDBAnalyticsEngine(prod_schema.sample_records, prod_schema)

            prod_summary = prod_engine.summary(group_by="category")
            self.assertIn(prod_summary["engine"], ("duckdb", "sqlite"))
            self.assertEqual(prod_summary["resource"], "products")
            self.assertGreater(len(prod_summary["metrics"]), 0)
            cat_map = {m["category"]: m["total_count"] for m in prod_summary["metrics"]}
            self.assertIn("electronics", cat_map)
            self.assertIn("software", cat_map)
            self.assertIn("apparel", cat_map)

    def test_end_to_end_drift_detection_and_pr_generation(self):
        """
        Verify end-to-end drift detection and automated PR generation:
        - Mutates records in temporary directory
        - Runs diff_schemas to discover breaking and non-breaking contract changes
        - Asserts generate_pr_markdown captures the changes accurately
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            orig_orders_path = tmp / "orders_v1.csv"
            mutated_orders_path = tmp / "orders_v2.csv"

            # Copy baseline orders from examples/
            base_orders = (self.examples_dir / "orders.csv").read_text(encoding="utf-8")
            orig_orders_path.write_text(base_orders, encoding="utf-8")

            # Mutate:
            # 1. Add non-nullable tracking_number (breaking for client POST requests)
            # 2. Add nullable gift_message (non-breaking)
            lines = base_orders.strip().splitlines()
            header = lines[0] + ",tracking_number,gift_message"
            mutated_lines = [header]
            for idx, line in enumerate(lines[1:]):
                gift = "Happy Birthday!" if idx % 2 == 0 else ""
                mutated_lines.append(f"{line},TRK-{1000 + idx},{gift}")

            mutated_orders_path.write_text("\n".join(mutated_lines), encoding="utf-8")

            old_schema = infer_from_file(orig_orders_path, resource_name="order")
            new_schema = infer_from_file(mutated_orders_path, resource_name="order")

            # Compute semantic schema diff
            diff = diff_schemas(old_schema, new_schema)
            self.assertTrue(diff.has_breaking_changes, "Non-nullable new column should trigger breaking change")
            self.assertEqual(len(diff.changes), 2, "Expected 2 field changes detected (tracking_number, gift_message)")

            changed_field_names = [c.field_name for c in diff.changes]
            self.assertIn("tracking_number", changed_field_names)
            self.assertIn("gift_message", changed_field_names)

            # Generate autonomous PR markdown
            pr_markdown = generate_pr_markdown(diff, base_version="1.0.0", next_version="1.1.0")

            # Verify PR markdown structure & contents
            self.assertIn("Automated API Maintenance: `order` Schema Upgrade", pr_markdown)
            self.assertIn("BREAKING%20CHANGES", pr_markdown)
            self.assertIn("Breaking Changes", pr_markdown)
            self.assertIn("tracking_number", pr_markdown)
            self.assertIn("gift_message", pr_markdown)
            self.assertIn("Change Summary", pr_markdown)
            self.assertIn("Breaking Changes & Required Action", pr_markdown)
            self.assertIn("Backward-Compatible Additions", pr_markdown)
            self.assertIn("Verification & Test Plan", pr_markdown)


if __name__ == "__main__":
    unittest.main()

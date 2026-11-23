"""
Unit tests for multi-table relational schema inference and embedded DuckDB analytics.
Tests foreign key inference, directory scanning, turnkey analytics code generation,
SQL synthesis, and vectorized in-memory query execution.
"""

import ast
from datetime import date, datetime
from decimal import Decimal
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from datapi.generator import generate_project
from datapi.infer import (
    _duckdb,
    ForeignKeyDef,
    infer_from_directory,
    infer_from_file,
    infer_multi_table_relationships,
    infer_schema_from_records,
)
from datapi.planner import create_api_plan
from datapi.analytics import (
    DuckDBAnalyticsEngine,
    generate_analytics_endpoints,
    generate_analytics_routes,
    generate_duckdb_analytics_code,
    synthesize_summary_sql,
    synthesize_timeseries_sql,
)


class TestRelationalAndAnalytics(unittest.TestCase):
    def test_multi_table_schema_inference_linking_customers_and_orders(self):
        """
        Test multi-table schema inference linking customers.csv and an orders.csv
        (where orders.csv has customer_id). Verify orders schema has FK pointing
        to customer.customer_id.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            customers_csv = p / "customers.csv"
            orders_csv = p / "orders.csv"

            customers_csv.write_text(
                "customer_id,name,email,tier\n"
                "1,Alice,alice@example.com,gold\n"
                "2,Bob,bob@example.com,silver\n"
                "3,Charlie,charlie@example.com,bronze\n"
            )

            orders_csv.write_text(
                "order_id,customer_id,total,status,created_at\n"
                "1001,1,49.99,pending,2026-11-01T10:00:00\n"
                "1002,2,19.99,completed,2026-11-02T11:00:00\n"
                "1003,1,99.50,completed,2026-11-03T12:00:00\n"
            )

            customer_schema = infer_from_file(customers_csv)
            order_schema = infer_from_file(orders_csv)

            self.assertEqual(customer_schema.resource_name, "customer")
            self.assertEqual(customer_schema.primary_key, "customer_id")
            self.assertEqual(order_schema.resource_name, "order")
            self.assertEqual(order_schema.primary_key, "order_id")

            # Link relationships across schemas
            infer_multi_table_relationships([customer_schema, order_schema])

            # Customers should have no outbound foreign keys
            self.assertEqual(len(customer_schema.foreign_keys), 0)

            # Orders must have foreign key pointing to customer.customer_id
            self.assertEqual(len(order_schema.foreign_keys), 1)
            fk = order_schema.foreign_keys[0]
            self.assertIsInstance(fk, ForeignKeyDef)
            self.assertEqual(fk.field_name, "customer_id")
            self.assertEqual(fk.target_resource, "customer")
            self.assertEqual(fk.target_field, "customer_id")
            self.assertEqual(f"{fk.target_resource}.{fk.target_field}", "customer.customer_id")

    def test_multi_table_inference_with_id_primary_key(self):
        """Verify foreign key linking when target resource uses 'id' as primary key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            users_csv = p / "users.csv"
            posts_csv = p / "posts.csv"

            users_csv.write_text(
                "id,username,email\n"
                "1,user1,u1@example.com\n"
                "2,user2,u2@example.com\n"
            )
            posts_csv.write_text(
                "id,user_id,title,views\n"
                "101,1,Hello World,150\n"
                "102,2,Second Post,300\n"
            )

            user_schema = infer_from_file(users_csv)
            post_schema = infer_from_file(posts_csv)

            infer_multi_table_relationships([user_schema, post_schema])
            self.assertEqual(len(post_schema.foreign_keys), 1)
            fk = post_schema.foreign_keys[0]
            self.assertEqual(fk.field_name, "user_id")
            self.assertEqual(fk.target_resource, "user")
            self.assertEqual(fk.target_field, "id")

    def test_infer_from_directory(self):
        """Test scanning a directory for CSV, JSON, and SQLite files with automated FK resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)

            # 1. CSV: customers
            (p / "customers.csv").write_text(
                "customer_id,name,email\n"
                "1,Alice,alice@example.com\n"
                "2,Bob,bob@example.com\n"
            )

            # 2. CSV: orders referencing customer
            (p / "orders.csv").write_text(
                "order_id,customer_id,total,status\n"
                "1001,1,49.99,pending\n"
                "1002,2,19.99,completed\n"
            )

            # 3. JSON: order_items referencing order
            (p / "order_items.json").write_text(
                json.dumps([
                    {"item_id": 1, "order_id": 1001, "product_name": "Widget A", "price": 25.00},
                    {"item_id": 2, "order_id": 1001, "product_name": "Widget B", "price": 24.99},
                    {"item_id": 3, "order_id": 1002, "product_name": "Gadget X", "price": 19.99},
                ])
            )

            # 4. SQLite: products table
            db_path = p / "products.db"
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("CREATE TABLE products (product_id INTEGER PRIMARY KEY, title TEXT, price REAL)")
            cur.executemany(
                "INSERT INTO products VALUES (?, ?, ?)",
                [(1, "Laptop", 999.0), (2, "Phone", 499.0)],
            )
            conn.commit()
            conn.close()

            # Execute infer_from_directory
            schemas = infer_from_directory(p)
            schema_map = {s.resource_name: s for s in schemas}

            self.assertIn("customer", schema_map)
            self.assertIn("order", schema_map)
            self.assertIn("order_item", schema_map)
            self.assertIn("product", schema_map)

            # Check orders -> customer foreign key
            order_schema = schema_map["order"]
            self.assertTrue(any(
                fk.field_name == "customer_id" and fk.target_resource == "customer" and fk.target_field == "customer_id"
                for fk in order_schema.foreign_keys
            ))

            # Check order_items -> order foreign key
            item_schema = schema_map["order_item"]
            self.assertTrue(any(
                fk.field_name == "order_id" and fk.target_resource == "order" and fk.target_field == "order_id"
                for fk in item_schema.foreign_keys
            ))

    def test_infer_from_directory_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            infer_from_directory("/nonexistent/directory/path/12345")

    def test_duckdb_analytics_code_generation_valid_ast_syntax(self):
        """Test DuckDB analytics code generation produces valid Python syntax (ast.parse)."""
        records = [
            {"order_id": 101, "customer_id": 1, "total": 49.99, "status": "pending", "created_at": "2026-11-01"},
            {"order_id": 102, "customer_id": 2, "total": 19.99, "status": "completed", "created_at": "2026-11-02"},
        ]
        schema = infer_schema_from_records(records, resource_name="order")

        # Test primary generator and aliases
        for gen_fn in (
            generate_duckdb_analytics_code,
            generate_analytics_routes,
            generate_analytics_endpoints,
        ):
            code = gen_fn(schema)
            self.assertIsInstance(code, str)
            self.assertIn("/orders/analytics/summary", code)
            self.assertIn("/orders/analytics/timeseries", code)

            # ast.parse must succeed with no syntax errors
            tree = ast.parse(code)
            self.assertIsInstance(tree, ast.Module)

            # Verify functions exist in AST
            fn_names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            self.assertIn("get_orders_analytics_summary", fn_names)
            self.assertIn("get_orders_analytics_timeseries", fn_names)
            self.assertIn("_execute_analytics_query", fn_names)

    def test_synthesize_summary_sql(self):
        records = [
            {"id": 1, "sales": 100.0, "quantity": 5, "region": "North"},
            {"id": 2, "sales": 200.0, "quantity": 10, "region": "South"},
        ]
        schema = infer_schema_from_records(records, resource_name="transaction")

        # Basic summary SQL
        sql = synthesize_summary_sql(schema)
        self.assertIn("COUNT(*) AS total_count", sql)
        self.assertIn('AVG("sales") AS avg_sales', sql)
        self.assertIn('SUM("sales") AS sum_sales', sql)
        self.assertIn('MIN("quantity") AS min_quantity', sql)
        self.assertIn('MAX("quantity") AS max_quantity', sql)
        self.assertNotIn("GROUP BY", sql)

        # Group by summary SQL
        sql_grouped = synthesize_summary_sql(schema, group_by="region")
        self.assertIn('GROUP BY "region"', sql_grouped)
        self.assertIn('ORDER BY total_count DESC', sql_grouped)

    def test_synthesize_timeseries_sql(self):
        records = [
            {"id": 1, "revenue": 50.0, "timestamp": "2026-11-01T12:00:00"},
            {"id": 2, "revenue": 80.0, "timestamp": "2026-11-02T14:00:00"},
        ]
        schema = infer_schema_from_records(records, resource_name="invoice")

        # DuckDB engine timeseries SQL
        duck_sql = synthesize_timeseries_sql(schema, date_field="timestamp", metric_field="revenue", engine="duckdb")
        self.assertIn("TRY_CAST", duck_sql)
        self.assertIn("cumulative_count", duck_sql)
        self.assertIn("moving_avg_7d", duck_sql)
        self.assertIn("SUM(count) OVER", duck_sql)

        # SQLite engine timeseries SQL
        sqlite_sql = synthesize_timeseries_sql(schema, date_field="timestamp", metric_field="revenue", engine="sqlite")
        self.assertIn("strftime('%Y-%m-%d', \"timestamp\")", sqlite_sql)
        self.assertIn("cumulative_count", sqlite_sql)
        self.assertIn("moving_avg_7d", sqlite_sql)

    def test_analytics_engine_execution_and_fallback(self):
        records = [
            {"id": 1, "amount": 100.0, "category": "books", "created_at": "2026-11-01"},
            {"id": 2, "amount": 50.0, "category": "electronics", "created_at": "2026-11-01"},
            {"id": 3, "amount": 150.0, "category": "books", "created_at": "2026-11-02"},
        ]
        schema = infer_schema_from_records(records, resource_name="sale")
        engine = DuckDBAnalyticsEngine(records, schema)

        # Summary without group_by
        summary = engine.summary()
        self.assertIn(summary["engine"], ("duckdb", "sqlite"))
        metrics = summary["metrics"][0]
        self.assertEqual(metrics["total_count"], 3)
        self.assertEqual(metrics["sum_amount"], 300.0)
        self.assertEqual(metrics["min_amount"], 50.0)
        self.assertEqual(metrics["max_amount"], 150.0)
        self.assertEqual(metrics["avg_amount"], 100.0)

        # Summary with group_by category
        grouped_summary = engine.summary(group_by="category")
        category_counts = {m["category"]: m["total_count"] for m in grouped_summary["metrics"]}
        self.assertEqual(category_counts["books"], 2)
        self.assertEqual(category_counts["electronics"], 1)

        # Timeseries aggregation with cumulative window functions
        ts = engine.timeseries(date_field="created_at", metric_field="amount", interval="day")
        ts_rows = ts["timeseries"]
        self.assertEqual(len(ts_rows), 2)
        # Period 1
        self.assertEqual(ts_rows[0]["period"], "2026-11-01")
        self.assertEqual(ts_rows[0]["count"], 2)
        self.assertEqual(ts_rows[0]["cumulative_count"], 2)
        self.assertEqual(ts_rows[0]["sum_metric"], 150.0)
        # Period 2
        self.assertEqual(ts_rows[1]["period"], "2026-11-02")
        self.assertEqual(ts_rows[1]["count"], 1)
        self.assertEqual(ts_rows[1]["cumulative_count"], 3)
        self.assertEqual(ts_rows[1]["sum_metric"], 150.0)

    def test_analytics_sql_identifier_allowlist_and_auth_guard(self):
        records = [
            {"id": 1, "amount": 100.0, "category": "books", "created_at": "2026-11-01"},
        ]
        schema = infer_schema_from_records(records, resource_name="sale")

        with self.assertRaises(ValueError):
            synthesize_summary_sql(schema, group_by="nonexistent_column")
        with self.assertRaises(ValueError):
            synthesize_summary_sql(schema, group_by='category"; DROP TABLE records; --')
        with self.assertRaises(ValueError):
            synthesize_summary_sql(schema, table_name="arbitrary_unlisted_table")
        with self.assertRaises(ValueError):
            synthesize_timeseries_sql(schema, interval="hourly; DROP TABLE records")
        with self.assertRaises(ValueError):
            synthesize_timeseries_sql(schema, metric_field="unknown_metric")
        with self.assertRaises(ValueError):
            synthesize_timeseries_sql(schema, table_name="arbitrary_unlisted_table")

        plan_auth = create_api_plan(schema, auth_enabled=True)
        auth_analytics_code = generate_duckdb_analytics_code(plan_auth)
        self.assertIn("dependencies=[Depends(verify_api_key)]", auth_analytics_code)

    def test_analytics_spaced_headers_sqlite_fallback_and_empty_validation(self):
        """Verifies spaced source headers work on SQLite fallback and invalid params fail on empty stores."""
        records = [
            {"id": 1, "amount": 100.0, "Display Name": "Alice", " Rogue!! ": "ignored"},
            {"id": 2, "amount": 50.0, "Display Name": "Bob", " Rogue!! ": "ignored"},
        ]
        schema = infer_schema_from_records(
            [{"id": r["id"], "amount": r["amount"], "Display Name": r["Display Name"]} for r in records],
            resource_name="invoice",
        )
        with patch("datapi.analytics.DUCKDB_AVAILABLE", False):
            engine = DuckDBAnalyticsEngine(records, schema)
            summary = engine.summary()
            self.assertEqual(summary["engine"], "sqlite")
            self.assertEqual(summary["metrics"][0]["total_count"], 2)
            self.assertEqual(summary["metrics"][0]["sum_amount"], 150.0)

        plan = create_api_plan(schema)
        with tempfile.TemporaryDirectory() as tmpdir:
            files = generate_project(plan, Path(tmpdir))
            ns = {}
            exec(compile(Path(files["app/main.py"]).read_text(encoding="utf-8"), files["app/main.py"], "exec"), ns)
            ns["_DUCKDB_AVAILABLE"] = False
            client = TestClient(ns["app"])
            res_ok = client.get("/invoices/analytics/summary")
            self.assertEqual(res_ok.status_code, 200)
            self.assertEqual(res_ok.json()["metrics"][0]["total_count"], 2)

            # Empty store must still reject invalid group_by and interval with HTTP 400
            ns["db"].clear()
            ns["db_invoices"].clear()
            res_bad_group = client.get("/invoices/analytics/summary?group_by=unknown_col")
            self.assertEqual(res_bad_group.status_code, 400)
            res_bad_interval = client.get("/invoices/analytics/timeseries?interval=invalid")
            self.assertEqual(res_bad_interval.status_code, 400)

    def test_parquet_ingestion_dates_decimals_and_directory_error_propagation(self):
        """Verifies native date/datetime/Decimal normalization into JSON OpenAPI and directory error propagation."""
        native_records = [
            {
                "event_id": 1,
                "created_on": date(2026, 11, 1),
                "occurred_at": datetime(2026, 11, 1, 12, 30, 0),
                "unit_price": Decimal("49.99"),
            }
        ]
        native_schema = infer_schema_from_records(native_records, resource_name="event")
        with tempfile.TemporaryDirectory() as tmpdir:
            files = generate_project(create_api_plan(native_schema), Path(tmpdir) / "native_out")
            spec = json.loads(Path(files["openapi.json"]).read_text(encoding="utf-8"))
            props = spec["components"]["schemas"]["EventBase"]["properties"]
            self.assertEqual(props["created_on"]["example"], "2026-11-01")
            self.assertIsInstance(props["unit_price"]["example"], float)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "customers.csv").write_text("id,name\n1,Alice\n", encoding="utf-8")
            parquet_path = tmp_path / "events.parquet"
            parquet_path.write_bytes(b"PAR1")
            with patch("datapi.infer._duckdb", None):
                with self.assertRaises(RuntimeError) as ctx:
                    infer_from_file(parquet_path)
                self.assertIn("datapi[analytics]", str(ctx.exception))
                with self.assertRaises(RuntimeError):
                    infer_from_directory(tmp_path)

            if _duckdb is not None:
                con = _duckdb.connect(":memory:")
                escaped = str(parquet_path).replace("'", "''")
                con.execute(
                    f"COPY (SELECT 1 AS event_id, DATE '2026-11-01' AS created_on, "
                    f"TIMESTAMP '2026-11-01 10:15:00' AS occurred_at, "
                    f"CAST(42.50 AS DECIMAL(10, 2)) AS unit_price) "
                    f"TO '{escaped}' (FORMAT PARQUET)"
                )
                con.close()
                schema = infer_from_file(parquet_path)
                self.assertEqual(schema.resource_name, "event")
                self.assertEqual(schema.primary_key, "event_id")
                field_map = {f.name: f for f in schema.fields}
                self.assertEqual(field_map["created_on"].python_type, "date")
                self.assertEqual(field_map["occurred_at"].python_type, "datetime")
                self.assertEqual(field_map["unit_price"].python_type, "float")

                out_dir = tmp_path / "parquet_api"
                gen_files = generate_project(create_api_plan(schema), out_dir)
                spec = json.loads(Path(gen_files["openapi.json"]).read_text(encoding="utf-8"))
                props = spec["components"]["schemas"]["EventBase"]["properties"]
                self.assertEqual(props["created_on"]["example"], "2026-11-01")
                self.assertIsInstance(props["unit_price"]["example"], float)


if __name__ == "__main__":
    unittest.main()

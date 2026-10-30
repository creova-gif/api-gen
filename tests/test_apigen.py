"""
Unit tests for APIGen Blueprint Wedge.
Tests schema inference, intent planning, mock generation, code generation,
and self-maintaining schema diffing / PR generation.
"""

import json
import tempfile
from pathlib import Path
import unittest

from apigen.infer import infer_schema_from_records
from apigen.planner import create_api_plan
from apigen.generator import generate_project
from apigen.diff import diff_schemas, ChangeType, Severity
from apigen.patcher import generate_pr_markdown


class TestAPIGen(unittest.TestCase):
    def test_infer_from_records(self):
        records = [
            {"id": "1", "name": "Alpha", "score": "98.5", "active": "true"},
            {"id": "2", "name": "Beta", "score": "87.0", "active": "false"},
        ]
        schema = infer_schema_from_records(records, resource_name="device")
        self.assertEqual(schema.resource_name, "device")
        self.assertEqual(schema.plural_name, "devices")
        self.assertEqual(schema.primary_key, "id")

        field_map = {f.name: f for f in schema.fields}
        self.assertEqual(field_map["id"].python_type, "int")
        self.assertEqual(field_map["name"].python_type, "str")
        self.assertEqual(field_map["score"].python_type, "float")
        self.assertEqual(field_map["active"].python_type, "bool")

    def test_planner_read_only(self):
        records = [{"id": 1, "title": "Report A"}]
        schema = infer_schema_from_records(records, resource_name="report")
        plan = create_api_plan(schema, intent="Create a read-only reporting endpoint")
        self.assertFalse(plan.allow_create)
        self.assertFalse(plan.allow_update)
        self.assertFalse(plan.allow_delete)
        self.assertTrue(plan.allow_read)

    def test_generate_project_with_auth_and_mocks(self):
        records = [
            {"order_id": 1001, "total": 49.99, "status": "pending"},
        ]
        schema = infer_schema_from_records(records, resource_name="order")
        plan = create_api_plan(schema, intent="Allow filter by status", auth_enabled=True, mock_count=10)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_project(plan, out_path)

            self.assertIn("openapi.json", files)
            self.assertIn("app/main.py", files)
            self.assertIn("tests/test_api.py", files)
            self.assertIn("Dockerfile", files)
            self.assertIn("terraform/main.tf", files)

            # Check openapi auth
            with open(files["openapi.json"], "r") as f:
                spec = json.load(f)
            self.assertIn("securitySchemes", spec["components"])
            self.assertIn("ApiKeyAuth", spec["components"]["securitySchemes"])

            # Check main.py has mock records
            with open(files["app/main.py"], "r") as f:
                code = f.read()
            self.assertIn("verify_api_key", code)
            self.assertIn("X-API-Key", code)

    def test_diff_schemas_breaking_and_non_breaking(self):
        old_records = [
            {"id": 1, "username": "alice", "age": 28, "status": "active"},
            {"id": 2, "username": "bob", "age": 34, "status": "pending"},
        ]
        new_records = [
            # Removed 'age' (BREAKING)
            # Removed 'username' (BREAKING)
            # Added non-nullable 'user_handle' (BREAKING)
            # Added optional 'avatar_url' (NON-BREAKING)
            {"id": 1, "user_handle": "alice", "status": "active", "avatar_url": "https://img.com/a.png"},
            {"id": 2, "user_handle": "bob", "status": "pending", "avatar_url": None},
        ]
        old_schema = infer_schema_from_records(old_records, resource_name="user")
        new_schema = infer_schema_from_records(new_records, resource_name="user")

        diff = diff_schemas(old_schema, new_schema)
        self.assertTrue(diff.has_breaking_changes)
        self.assertEqual(len(diff.breaking_changes), 3)  # age removed, username removed, user_handle added (required)
        self.assertTrue(any(c.change_type == ChangeType.FIELD_REMOVED and c.field_name == "age" for c in diff.changes))
        self.assertTrue(any(c.change_type == ChangeType.FIELD_REMOVED and c.field_name == "username" for c in diff.changes))
        self.assertTrue(any(c.field_name == "avatar_url" and c.severity == Severity.NON_BREAKING for c in diff.changes))

        pr_markdown = generate_pr_markdown(diff)
        self.assertIn("Automated API Maintenance", pr_markdown)
        self.assertIn("BREAKING%20CHANGES", pr_markdown)
        self.assertIn("🚨 **Breaking Changes**", pr_markdown)


if __name__ == "__main__":
    unittest.main()

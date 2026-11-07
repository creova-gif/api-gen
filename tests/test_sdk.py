"""
Unit tests for TypeScript and Python Client SDK Generators.
Tests retry logic, timeout handling, RFC 7807 error modeling,
cursor pagination, valid Python AST syntax, type annotations, and methods.
"""

import ast
import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch
import urllib.error

from datapi.infer import infer_schema_from_records
from datapi.planner import create_api_plan
from datapi.sdk_generator import generate_typescript_sdk
from datapi.python_sdk_generator import generate_python_sdk


class TestSDKGenerators(unittest.TestCase):
    def setUp(self):
        records = [
            {"id": 1, "name": "Sensor A", "reading": 42.5, "active": True},
            {"id": 2, "name": "Sensor B", "reading": 99.1, "active": False},
        ]
        self.schema = infer_schema_from_records(records, resource_name="sensor")
        self.plan = create_api_plan(self.schema, intent="Allow sensors management", auth_enabled=True)

    # -------------------------------------------------------------------------
    # TypeScript SDK Tests
    # -------------------------------------------------------------------------

    def test_typescript_sdk_contains_retry_logic(self):
        ts_code = generate_typescript_sdk(self.plan)
        # Check 429 and 503 retry triggers
        self.assertIn("429", ts_code)
        self.assertIn("503", ts_code)
        # Check configurable maxRetries and backoffFactor
        self.assertIn("maxRetries", ts_code)
        self.assertIn("backoffFactor", ts_code)
        self.assertIn("maxRetries ?? 3", ts_code)
        self.assertIn("backoffFactor ?? 1.5", ts_code)
        # Check exponential backoff and jitter
        self.assertIn("Math.pow(this.backoffFactor", ts_code)
        self.assertIn("Math.random()", ts_code)

    def test_typescript_sdk_contains_abort_signal_timeout(self):
        ts_code = generate_typescript_sdk(self.plan)
        # Check AbortSignal timeout usage
        self.assertIn("AbortSignal.timeout", ts_code)
        self.assertIn("timeoutMs", ts_code)
        self.assertIn("10000", ts_code)

    def test_typescript_sdk_contains_datapi_api_error(self):
        ts_code = generate_typescript_sdk(self.plan)
        # Check RFC 7807 DatapiApiError class
        self.assertIn("export class DatapiApiError extends Error", ts_code)
        self.assertIn("public status: number", ts_code)
        self.assertIn("public title?: string", ts_code)
        self.assertIn("public type?: string", ts_code)
        self.assertIn("public detail?: string", ts_code)
        self.assertIn("public instance?: string", ts_code)
        self.assertIn("public data?: unknown", ts_code)

    def test_typescript_sdk_contains_list_cursor(self):
        ts_code = generate_typescript_sdk(self.plan)
        # Check listCursor method signature and return properties
        self.assertIn("listCursor", ts_code)
        self.assertIn("nextCursor", ts_code)
        self.assertIn("hasMore", ts_code)
        self.assertIn("items: Sensor[]", ts_code)

    def test_typescript_sdk_zero_external_dependencies(self):
        ts_code = generate_typescript_sdk(self.plan)
        # Verify no external import statements (uses global fetch / AbortSignal)
        lines = [line.strip() for line in ts_code.splitlines()]
        import_lines = [l for l in lines if l.startswith("import ") and not l.startswith("import type")]
        self.assertEqual(import_lines, [])

    # -------------------------------------------------------------------------
    # Python SDK Tests
    # -------------------------------------------------------------------------

    def test_python_sdk_valid_syntax_ast_parse(self):
        py_code = generate_python_sdk(self.plan)
        # ast.parse raises SyntaxError if invalid
        parsed = ast.parse(py_code)
        self.assertIsInstance(parsed, ast.Module)

    def test_python_sdk_client_methods_and_docstrings(self):
        py_code = generate_python_sdk(self.plan)
        namespace = {}
        exec(py_code, namespace)

        self.assertIn("DatapiClient", namespace)
        client_cls = namespace["DatapiClient"]

        # Verify required methods exist
        required_methods = ["list", "get", "create", "delete", "update", "health", "list_cursor"]
        for method_name in required_methods:
            self.assertTrue(
                hasattr(client_cls, method_name),
                f"DatapiClient missing required method: {method_name}",
            )
            method = getattr(client_cls, method_name)
            # Verify docstrings
            self.assertTrue(
                method.__doc__ and len(method.__doc__.strip()) > 0,
                f"Method {method_name} missing docstring",
            )
            # Verify type annotations
            self.assertTrue(
                len(method.__annotations__) > 0,
                f"Method {method_name} missing type annotations",
            )

    def test_python_sdk_retries_and_rfc7807_error(self):
        py_code = generate_python_sdk(self.plan)
        namespace = {}
        exec(py_code, namespace)

        # Check DatapiApiError class
        self.assertIn("DatapiApiError", namespace)
        error_cls = namespace["DatapiApiError"]
        self.assertTrue(issubclass(error_cls, Exception))

        err = error_cls(
            status=429,
            detail="Rate limit exceeded",
            title="Too Many Requests",
            type="https://api.example.com/errors/rate-limit",
            instance="/sensors",
            data={"retry_after": 5},
        )
        self.assertEqual(err.status, 429)
        self.assertEqual(err.status_code, 429)
        self.assertEqual(err.title, "Too Many Requests")
        self.assertEqual(err.detail, "Rate limit exceeded")
        self.assertEqual(err.type, "https://api.example.com/errors/rate-limit")
        self.assertEqual(err.instance, "/sensors")
        self.assertEqual(err.data, {"retry_after": 5})

        # Check client default parameters
        client = namespace["DatapiClient"]()
        self.assertEqual(client.max_retries, 3)
        self.assertEqual(client.backoff_factor, 1.5)
        self.assertEqual(client.timeout, 10.0)

    def test_python_sdk_retry_execution_on_429(self):
        py_code = generate_python_sdk(self.plan)
        namespace = {}
        exec(py_code, namespace)

        client = namespace["DatapiClient"](base_url="http://mock-api.local", max_retries=2, backoff_factor=1.0)

        # Mock urllib.request.urlopen: first attempt 429, second attempt 200 OK
        resp_200 = MagicMock()
        resp_200.status = 200
        resp_200.read.return_value = json.dumps({"items": [{"id": 1, "name": "Sensor A"}]}).encode("utf-8")
        resp_200.__enter__.return_value = resp_200
        resp_200.__exit__.return_value = None

        http_err_429 = urllib.error.HTTPError(
            url="http://mock-api.local/sensors",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(b'{"detail": "Rate limit exceeded"}'),
        )

        with patch("urllib.request.urlopen", side_effect=[http_err_429, resp_200]):
            with patch("time.sleep"):  # Avoid real sleep in tests
                res = client.list()
                self.assertEqual(len(res["items"]), 1)
                self.assertEqual(res["items"][0]["name"], "Sensor A")

    def test_python_sdk_zero_external_dependencies(self):
        py_code = generate_python_sdk(self.plan)
        tree = ast.parse(py_code)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        # Allowed standard library modules only
        stdlib_allowed = {
            "__future__",
            "base64",
            "json",
            "random",
            "time",
            "urllib",
            "typing",
        }
        self.assertTrue(
            imported_modules.issubset(stdlib_allowed),
            f"Non-standard modules found: {imported_modules - stdlib_allowed}",
        )


if __name__ == "__main__":
    unittest.main()

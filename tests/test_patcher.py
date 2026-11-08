"""
Unit tests for datapi.patcher and self-maintaining code migration engine.
Tests automated PR markdown generation, TypeScript patching, Python patching with AST validation,
and directory scanning with unified diff generation.
"""

import ast
from pathlib import Path
import tempfile
import unittest

from datapi.diff import ChangeType, FieldChange, SchemaDiff, Severity
from datapi.patcher import (
    generate_migration_summary,
    generate_pr_markdown,
    patch_consumer_directory,
    patch_python_source,
    patch_typescript_source,
)


class TestPatcher(unittest.TestCase):
    def setUp(self):
        # Diff with breaking changes (rename + removal)
        self.breaking_diff = SchemaDiff(
            old_resource="user",
            new_resource="user",
            has_breaking_changes=True,
            changes=[
                FieldChange(
                    field_name="username",
                    change_type=ChangeType.FIELD_RENAMED,
                    severity=Severity.BREAKING,
                    description="Field 'username' renamed to 'user_handle'",
                    old_value="username",
                    new_value="user_handle",
                    migration_advice="Update references from 'username' to 'user_handle'.",
                ),
                FieldChange(
                    field_name="age",
                    change_type=ChangeType.FIELD_REMOVED,
                    severity=Severity.BREAKING,
                    description="Field 'age' (int) was removed",
                    old_value="int",
                    new_value=None,
                    migration_advice="Deprecate field 'age'.",
                ),
            ],
        )

        # Diff with non-breaking changes only
        self.non_breaking_diff = SchemaDiff(
            old_resource="user",
            new_resource="user",
            has_breaking_changes=False,
            changes=[
                FieldChange(
                    field_name="avatar_url",
                    change_type=ChangeType.FIELD_ADDED,
                    severity=Severity.NON_BREAKING,
                    description="Field 'avatar_url' (str) added [Optional]",
                    old_value=None,
                    new_value="str",
                    migration_advice="New optional field 'avatar_url'. Existing clients can safely ignore.",
                )
            ],
        )

    # -------------------------------------------------------------------------
    # 1. PR Markdown Generation Tests
    # -------------------------------------------------------------------------

    def test_generate_pr_markdown_with_breaking_changes(self):
        pr = generate_pr_markdown(self.breaking_diff, base_version="1.0.0", next_version="2.0.0")
        self.assertIn("Automated API Maintenance: `user` Schema Upgrade", pr)
        self.assertIn("BREAKING%20CHANGES-red", pr)
        self.assertIn("🚨 **Breaking Changes** | `2`", pr)
        self.assertIn("#### 1. `username` — FIELD_RENAMED", pr)
        self.assertIn("Field 'username' renamed to 'user_handle'", pr)
        self.assertIn("Update references from 'username' to 'user_handle'.", pr)
        self.assertIn("#### 2. `age` — FIELD_REMOVED", pr)
        self.assertIn("Deprecate field 'age'.", pr)

        summary = generate_migration_summary(self.breaking_diff)
        self.assertIn("Breaking Changes: 2", summary)
        self.assertIn("⚠️ ACTION REQUIRED", summary)

    def test_generate_pr_markdown_with_non_breaking_changes(self):
        pr = generate_pr_markdown(self.non_breaking_diff, base_version="1.0.0", next_version="1.1.0")
        self.assertIn("NON--BREAKING-green", pr)
        self.assertIn("No breaking changes detected", pr)
        self.assertIn("### ✨ Backward-Compatible Additions", pr)
        self.assertIn("- **`avatar_url`**:", pr)
        self.assertIn("New optional field 'avatar_url'", pr)

        summary = generate_migration_summary(self.non_breaking_diff)
        self.assertIn("Breaking Changes: 0", summary)
        self.assertIn("✅ SAFE TO AUTO-MERGE", summary)

    # -------------------------------------------------------------------------
    # 2. TypeScript Source Code Patching Tests
    # -------------------------------------------------------------------------

    def test_patch_typescript_source_renames_and_removals(self):
        ts_code = """import { ApiClient } from "./client";

export interface User {
    id: number;
    username: string;
    age?: number;
    created_at: string;
}

export type UserDTO = {
    username: string;
    age: number;
};

export async function processUser(client: ApiClient, id: number): Promise<void> {
    const user = await client.getUser(id);
    const name = user.username;
    const safeName = user?.username;
    const legacyName = user["username"];
    const userAge = user.age;
    const bracketAge = user["age"];

    const payload = { username: name, active: true };
    const { username } = user;

    console.log(`Loaded user ${name} (${user_handle_test})`);
}
"""
        patched, edits = patch_typescript_source(ts_code, self.breaking_diff)

        # 1. Interface & Type definitions
        self.assertIn("user_handle: string;", patched)
        self.assertNotIn("username: string;", patched)
        self.assertNotIn("age?: number;", patched)
        self.assertNotIn("age: number;", patched)

        # 2. Dot property accesses
        self.assertIn("user.user_handle", patched)
        self.assertNotIn("user.username", patched)
        self.assertIn("user?.user_handle", patched)
        self.assertNotIn("user?.username", patched)

        # 3. Bracket access
        self.assertIn('user["user_handle"]', patched)
        self.assertNotIn('user["username"]', patched)

        # 4. Object literal key
        self.assertIn("user_handle: name", patched)

        # 5. Destructuring
        self.assertIn("const { user_handle } = user;", patched)

        # 6. Removed field handling
        self.assertIn("(user as any).age", patched)
        self.assertIn("DEPRECATED: field 'age' was removed in API schema", patched)
        self.assertIn('(user as any)["age"]', patched)

        # 7. Edits audit trail
        self.assertTrue(len(edits) > 0)
        self.assertTrue(any("Renamed property 'username' to 'user_handle'" in e for e in edits))
        self.assertTrue(any("Removed field 'age'" in e for e in edits))

    # -------------------------------------------------------------------------
    # 3. Python Source Code Patching Tests
    # -------------------------------------------------------------------------

    def test_patch_python_source_dict_and_attr_access(self):
        py_code = '''"""Backend consumer script."""
from typing import Optional

class UserModel:
    username: str
    age: int

def handle_user(client, user_id: int):
    user = client.get_user(user_id)
    name = user["username"]
    alt_name = user['username']
    dot_name = user.username
    deep_name = resp.user.username
    get_name = user.get("username", "anonymous")
    
    user_age = user["age"]
    attr_age = user.age

    payload = {"username": name, "status": "active"}
    client.update_user(user_id, username=name)
    return user
'''
        patched, edits = patch_python_source(py_code, self.breaking_diff)

        # MUST parse with valid Python syntax
        tree = ast.parse(patched)
        self.assertIsInstance(tree, ast.Module)

        # Dictionary subscript
        self.assertIn('user["user_handle"]', patched)
        self.assertIn("user['user_handle']", patched)
        self.assertNotIn('user["username"]', patched)
        self.assertNotIn("user['username']", patched)

        # Attribute access
        self.assertIn("user.user_handle", patched)
        self.assertNotIn("user.username", patched)
        self.assertIn("resp.user.user_handle", patched)

        # .get() access
        self.assertIn('user.get("user_handle", "anonymous")', patched)

        # Dict literal key
        self.assertIn('"user_handle": name', patched)

        # Kwarg in call
        self.assertIn("client.update_user(user_id, user_handle=name)", patched)

        # Class annotation
        self.assertIn("user_handle: str", patched)

        # Removed field subscript -> safe .get()
        self.assertIn('user.get("age", None)', patched)
        self.assertNotIn('user["age"]', patched)

        # Removed field attribute -> safe getattr()
        self.assertIn('getattr(user, "age", None)', patched)
        self.assertNotIn("user.age", patched)

        # Class annotation for removed field commented out
        self.assertIn("# [DEPRECATED] age: int", patched)

        # Edits list verification
        self.assertTrue(len(edits) > 0)
        self.assertTrue(any("Renamed dictionary key 'username' -> 'user_handle'" in e for e in edits))
        self.assertTrue(any("Renamed attribute access '.username' -> '.user_handle'" in e for e in edits))

    # -------------------------------------------------------------------------
    # 4. Directory Scanning & Unified Diff Generation Tests
    # -------------------------------------------------------------------------

    def test_patch_consumer_directory_unified_diff(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)

            # Create a TypeScript consumer file
            ts_file = dir_path / "frontend" / "userClient.ts"
            ts_file.parent.mkdir(parents=True, exist_ok=True)
            ts_content = """export interface User {
    username: string;
    age: number;
}
export function getUsername(user: User) {
    return user.username;
}
"""
            ts_file.write_text(ts_content, encoding="utf-8")

            # Create a Python consumer file
            py_file = dir_path / "backend" / "worker.py"
            py_file.parent.mkdir(parents=True, exist_ok=True)
            py_content = """def process(user: dict):
    return user["username"]
"""
            py_file.write_text(py_content, encoding="utf-8")

            # Create an unrelated file that does not reference changed fields
            unrelated_file = dir_path / "shared" / "utils.py"
            unrelated_file.parent.mkdir(parents=True, exist_ok=True)
            unrelated_content = """def add(a: int, b: int) -> int:
    return a + b
"""
            unrelated_file.write_text(unrelated_content, encoding="utf-8")

            # Dry-run patch scan (apply=False)
            diffs = patch_consumer_directory(dir_path, self.breaking_diff, apply=False)

            # Should contain the two changed files, but not the unrelated one
            self.assertEqual(len(diffs), 2)
            self.assertIn(str(ts_file), diffs)
            self.assertIn(str(py_file), diffs)
            self.assertNotIn(str(unrelated_file), diffs)

            # Check unified diff format
            ts_diff = diffs[str(ts_file)]
            self.assertIn("--- a/frontend/userClient.ts", ts_diff)
            self.assertIn("+++ b/frontend/userClient.ts", ts_diff)
            self.assertIn("-    username: string;", ts_diff)
            self.assertIn("+    user_handle: string;", ts_diff)
            self.assertIn("-    return user.username;", ts_diff)
            self.assertIn("+    return user.user_handle;", ts_diff)

            py_diff = diffs[str(py_file)]
            self.assertIn("--- a/backend/worker.py", py_diff)
            self.assertIn("+++ b/backend/worker.py", py_diff)
            self.assertIn('-    return user["username"]', py_diff)
            self.assertIn('+    return user["user_handle"]', py_diff)

            # Files on disk must be unchanged in dry-run
            self.assertEqual(ts_file.read_text(encoding="utf-8"), ts_content)
            self.assertEqual(py_file.read_text(encoding="utf-8"), py_content)

            # Apply in-place (apply=True)
            applied_diffs = patch_consumer_directory(dir_path, self.breaking_diff, apply=True)
            self.assertEqual(len(applied_diffs), 2)

            # Files on disk must now be updated
            updated_ts = ts_file.read_text(encoding="utf-8")
            self.assertIn("user_handle: string;", updated_ts)
            self.assertIn("return user.user_handle;", updated_ts)

            updated_py = py_file.read_text(encoding="utf-8")
            self.assertIn('return user["user_handle"]', updated_py)
            ast.parse(updated_py)  # Must be valid AST

    def test_patch_consumer_directory_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            patch_consumer_directory(Path("/nonexistent/directory/path/datapi"), self.breaking_diff)

    def test_schema_diff_serialization(self):
        diff_json = self.breaking_diff.to_json()
        loaded = SchemaDiff.from_json(diff_json)
        self.assertEqual(loaded.old_resource, self.breaking_diff.old_resource)
        self.assertEqual(len(loaded.changes), len(self.breaking_diff.changes))
        self.assertEqual(loaded.changes[0].field_name, "username")
        self.assertEqual(loaded.changes[0].change_type, ChangeType.FIELD_RENAMED)

    def test_cli_patch_command(self):
        import io
        from unittest.mock import patch as mock_patch
        from datapi.cli import build_parser

        with tempfile.TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)
            diff_file = dir_path / "diff.json"
            diff_file.write_text(self.breaking_diff.to_json(), encoding="utf-8")

            caller_file = dir_path / "caller.py"
            caller_file.write_text('def get_name(user):\n    return user["username"]\n', encoding="utf-8")

            parser = build_parser()

            # Dry-run test via CLI
            args = parser.parse_args(["patch", "--consumer-dir", str(dir_path), "--diff", str(diff_file)])
            with mock_patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                args.func(args)
                out = mock_out.getvalue()
                self.assertIn("Generated patches for 1 file(s)", out)
                self.assertIn("--- a/caller.py", out)
                self.assertIn("Dry-run mode", out)
                # Ensure caller.py was NOT modified
                self.assertIn('user["username"]', caller_file.read_text())

            # Apply test via CLI with --target-dir alias
            args_apply = parser.parse_args(["patch", "--target-dir", str(dir_path), "--diff", str(diff_file), "--apply"])
            with mock_patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                args_apply.func(args_apply)
                out = mock_out.getvalue()
                self.assertIn("Successfully applied patches", out)
                # Ensure caller.py WAS modified
                self.assertIn('user["user_handle"]', caller_file.read_text())


if __name__ == "__main__":
    unittest.main()

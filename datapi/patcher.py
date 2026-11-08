"""
Self-Maintaining API Autonomous PR & Patch Generator.
Generates code migration patches, GitHub PR bodies, and consumer client upgrade instructions
when a schema change or API drift occurs.
"""

import ast
from datetime import datetime, timezone
import difflib
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from datapi.diff import ChangeType, SchemaDiff, Severity


def generate_migration_summary(diff: SchemaDiff) -> str:
    """Generates an executive summary of schema drift."""
    breaking = diff.breaking_changes
    non_breaking = diff.non_breaking_changes

    summary = []
    summary.append(f"Resource: {diff.new_resource}")
    summary.append(f"Total Changes: {len(diff.changes)}")
    summary.append(f"Breaking Changes: {len(breaking)}")
    summary.append(f"Non-Breaking Changes: {len(non_breaking)}")
    summary.append(f"Status: {'⚠️ ACTION REQUIRED (Breaking)' if breaking else '✅ SAFE TO AUTO-MERGE'}")
    return "\n".join(summary)


def generate_pr_markdown(diff: SchemaDiff, base_version: str = "1.0.0", next_version: str = "1.1.0") -> str:
    """
    Generates a ready-to-publish GitHub Pull Request body for consumer codebases.
    Direct implementation of the 'Self-Maintaining APIs' paradigm.
    """
    breaking = diff.breaking_changes
    non_breaking = diff.non_breaking_changes

    badge = (
        "![Status](https://img.shields.io/badge/API%20Upgrade-BREAKING%20CHANGES-red)"
        if breaking
        else "![Status](https://img.shields.io/badge/API%20Upgrade-NON--BREAKING-green)"
    )

    pr = f"""## 🤖 Automated API Maintenance: `{diff.new_resource}` Schema Upgrade

{badge}
> **Generated automatically by Datapi Self-Maintaining Engine.**  
> This Pull Request updates the data contracts, models, and endpoints for `{diff.new_resource}` from version `{base_version}` to `{next_version}`.

---

### 📊 Change Summary

| Impact | Count | Description |
| :--- | :---: | :--- |
| 🚨 **Breaking Changes** | `{len(breaking)}` | Requires code updates to models, query parameters, or deserialization. |
| ✨ **Non-Breaking** | `{len(non_breaking)}` | Backward-compatible additions (optional fields, expanded enums). |

---

### 🚨 Breaking Changes & Required Action
"""

    if breaking:
        for idx, c in enumerate(breaking, 1):
            pr += f"""
#### {idx}. `{c.field_name}` — {c.change_type.value if hasattr(c.change_type, 'value') else str(c.change_type)}
- **Impact**: {c.description}
- **Required Action**: {c.migration_advice}
"""
    else:
        pr += "\n*No breaking changes detected. All existing client calls will continue to succeed without modification.*\n"

    if non_breaking:
        pr += "\n---\n\n### ✨ Backward-Compatible Additions\n\n"
        for idx, c in enumerate(non_breaking, 1):
            pr += f"- **`{c.field_name}`**: {c.description} ({c.migration_advice})\n"

    pr += f"""
---

### 🛠️ Verification & Test Plan
- [x] Schema validated with Datapi diff engine.
- [ ] Pytest contract test suite passing against updated schemas.
- [ ] Client SDK deserialization checks verified.

---
*Created on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')} by Datapi Autonomous Agent.*
"""
    return pr


def _extract_diff_actions(diff: SchemaDiff) -> Tuple[Dict[str, str], List[str]]:
    """
    Extracts field renames (old_field -> new_field) and removed fields from a SchemaDiff.
    Handles explicit FIELD_RENAMED entries, FIELD_REMOVED entries, and descriptions.
    """
    renames: Dict[str, str] = {}
    removals: List[str] = []

    # Check for custom attribute if present
    custom_renames = getattr(diff, "renames", None) or getattr(diff, "field_renames", None)
    if isinstance(custom_renames, dict):
        renames.update(custom_renames)

    for c in diff.changes:
        ct_val = c.change_type.value if hasattr(c.change_type, "value") else str(c.change_type)

        if ct_val == "FIELD_RENAMED":
            old_name = c.old_value or c.field_name
            new_name = c.new_value
            if not new_name or new_name == old_name:
                m = re.search(r"renamed to ['\"]?([a-zA-Z0-9_]+)['\"]?", f"{c.description} {c.migration_advice}", re.IGNORECASE)
                if m:
                    new_name = m.group(1)
            if old_name and new_name and old_name != new_name:
                renames[old_name] = new_name

        elif ct_val == "FIELD_REMOVED":
            # Check if migration advice or description indicates a rename
            m = re.search(r"renamed to ['\"]?([a-zA-Z0-9_]+)['\"]?", f"{c.description} {c.migration_advice}", re.IGNORECASE)
            if m:
                renames[c.field_name] = m.group(1)
            elif c.new_value and isinstance(c.new_value, str) and c.new_value != c.field_name:
                renames[c.field_name] = c.new_value
            else:
                removals.append(c.field_name)

    # Filter out any removals that were classified as renames
    clean_removals = [r for r in removals if r not in renames]
    return renames, clean_removals


def patch_typescript_source(source_code: str, diff: SchemaDiff) -> Tuple[str, List[str]]:
    """
    Takes TypeScript/JavaScript consumer source code (e.g. frontend client calls or API types).
    For each renamed or removed field in the diff, updates property accesses, type interfaces,
    and destructuring patterns, recording descriptions of applied edits.
    """
    renames, removals = _extract_diff_actions(diff)
    edits: List[str] = []
    patched = source_code

    # 1. Field Renames
    for old_field, new_field in renames.items():
        # A. Interface / type definition properties: e.g. "  old_field: string;" or "  old_field?: number;"
        pattern_interface = re.compile(
            rf'(^[ \t]*(?:readonly\s+)?)\b{re.escape(old_field)}\b(\??\s*:[^;\n,]+[;,]?)',
            re.MULTILINE
        )
        patched, count_iface = pattern_interface.subn(rf'\g<1>{new_field}\g<2>', patched)
        if count_iface > 0:
            edits.append(f"Renamed property '{old_field}' to '{new_field}' in TypeScript interface/type definition ({count_iface} occurrence(s))")

        # B. Dot property access: e.g. "user.old_field" or "user?.old_field"
        pattern_dot = re.compile(rf'(?<=\.)\b{re.escape(old_field)}\b')
        patched, count_dot = pattern_dot.subn(new_field, patched)
        if count_dot > 0:
            edits.append(f"Renamed property access '.{old_field}' to '.{new_field}' ({count_dot} occurrence(s))")

        # C. Bracket property access: e.g. obj["old_field"] or obj['old_field']
        pattern_bracket = re.compile(rf'\[\s*(["\']){re.escape(old_field)}\1\s*\]')
        patched, count_bracket = pattern_bracket.subn(f'[\\1{new_field}\\1]', patched)
        if count_bracket > 0:
            edits.append(f"Renamed bracket access '[\"{old_field}\"]' to '[\"{new_field}\"]' ({count_bracket} occurrence(s))")

        # D. Object literal property names: e.g. "{ old_field: val }"
        pattern_obj_key = re.compile(rf'([\{{,]\s*)(["\']?){re.escape(old_field)}\2(\s*:)')
        patched, count_obj = pattern_obj_key.subn(rf'\g<1>\g<2>{new_field}\g<2>\g<3>', patched)
        if count_obj > 0:
            edits.append(f"Renamed object literal property '{old_field}' to '{new_field}' ({count_obj} occurrence(s))")

        # E. Destructuring: e.g. "const { old_field } = obj"
        pattern_destruct = re.compile(rf'([\{{,]\s*)\b{re.escape(old_field)}\b(\s*[,\}}])')
        patched, count_destruct = pattern_destruct.subn(rf'\g<1>{new_field}\g<2>', patched)
        if count_destruct > 0:
            edits.append(f"Renamed destructuring property '{old_field}' to '{new_field}' ({count_destruct} occurrence(s))")

    # 2. Field Removals
    for removed_field in removals:
        # A. Remove from interface / type definitions
        pattern_rem_iface = re.compile(
            rf'^[ \t]*(?:readonly\s+)?\b{re.escape(removed_field)}\b\??\s*:[^;\n]+[;,]?[ \t]*\r?\n?',
            re.MULTILINE
        )
        patched, count_rem_iface = pattern_rem_iface.subn('', patched)
        if count_rem_iface > 0:
            edits.append(f"Removed field '{removed_field}' from TypeScript interface/type definition ({count_rem_iface} occurrence(s))")

        # B. Dot property access on removed field: e.g. "user.old_field" or "user?.old_field"
        pattern_rem_dot = re.compile(
            rf'(\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)(\??\.)\b{re.escape(removed_field)}\b'
        )
        patched, count_rem_dot = pattern_rem_dot.subn(
            rf'(\1 as any)\g<2>{removed_field} /* DEPRECATED: field \'{removed_field}\' was removed in API schema */'.replace(r"\'", "'"),
            patched
        )
        if count_rem_dot > 0:
            edits.append(f"Deprecated property access for removed field '{removed_field}' ({count_rem_dot} occurrence(s))")

        # C. Bracket property access on removed field: e.g. user["old_field"]
        pattern_rem_bracket = re.compile(
            rf'(\b[a-zA-Z_][a-zA-Z0-9_]*)\s*\[\s*(["\']){re.escape(removed_field)}\2\s*\]'
        )
        patched, count_rem_bracket = pattern_rem_bracket.subn(
            rf'(\1 as any)[\g<2>{removed_field}\g<2>] /* DEPRECATED: field \'{removed_field}\' was removed in API schema */'.replace(r"\'", "'"),
            patched
        )
        if count_rem_bracket > 0:
            edits.append(f"Deprecated bracket access for removed field '{removed_field}' ({count_rem_bracket} occurrence(s))")

    return patched, edits


def patch_python_source(source_code: str, diff: SchemaDiff) -> Tuple[str, List[str]]:
    """
    Takes Python consumer source code (e.g. backend caller script using dict["old_field"] or .old_field).
    Updates references to changed field names, ensuring valid syntax with ast.parse.
    """
    renames, removals = _extract_diff_actions(diff)
    edits: List[str] = []
    patched = source_code

    # 1. Field Renames
    for old_field, new_field in renames.items():
        # A. Dict subscript access: user["old_field"] or user['old_field']
        pattern_sub = re.compile(rf'\[\s*(["\']){re.escape(old_field)}\1\s*\]')
        patched, count_sub = pattern_sub.subn(f'[\\1{new_field}\\1]', patched)
        if count_sub > 0:
            edits.append(f"Renamed dictionary key '{old_field}' -> '{new_field}' ({count_sub} occurrence(s))")

        # B. .get() dict access: user.get("old_field") or user.get('old_field')
        pattern_get = re.compile(rf'\.get\(\s*(["\']){re.escape(old_field)}\1')
        patched, count_get = pattern_get.subn(f'.get(\\1{new_field}\\1', patched)
        if count_get > 0:
            edits.append(f"Renamed .get() dictionary key '{old_field}' -> '{new_field}' ({count_get} occurrence(s))")

        # C. Attribute access: user.old_field
        pattern_attr = re.compile(rf'(?<=\.)\b{re.escape(old_field)}\b')
        patched, count_attr = pattern_attr.subn(new_field, patched)
        if count_attr > 0:
            edits.append(f"Renamed attribute access '.{old_field}' -> '.{new_field}' ({count_attr} occurrence(s))")

        # D. Dict literal keys: {"old_field": ...}
        pattern_dict_lit = re.compile(rf'([\{{,]\s*)(["\']){re.escape(old_field)}\2(\s*:)')
        patched, count_lit = pattern_dict_lit.subn(rf'\g<1>\g<2>{new_field}\g<2>\g<3>', patched)
        if count_lit > 0:
            edits.append(f"Renamed dict literal key '{old_field}' -> '{new_field}' ({count_lit} occurrence(s))")

        # E. Function call keyword arguments: func(old_field=...)
        pattern_kwarg = re.compile(rf'([(,]\s*)\b{re.escape(old_field)}\b(\s*=)')
        patched, count_kw = pattern_kwarg.subn(rf'\g<1>{new_field}\g<2>', patched)
        if count_kw > 0:
            edits.append(f"Renamed call keyword argument '{old_field}=' -> '{new_field}=' ({count_kw} occurrence(s))")

        # F. Class attribute / Pydantic field annotations: old_field: str
        pattern_ann = re.compile(rf'^([ \t]*)\b{re.escape(old_field)}\b(\s*:\s*[^=\n]+(?:=.*)?)$', re.MULTILINE)
        patched, count_ann = pattern_ann.subn(rf'\g<1>{new_field}\g<2>', patched)
        if count_ann > 0:
            edits.append(f"Renamed class field annotation '{old_field}' -> '{new_field}' ({count_ann} occurrence(s))")

    # 2. Field Removals
    for removed_field in removals:
        # A. Dict subscript access: user["old_field"] -> user.get("old_field", None)
        pattern_rem_sub = re.compile(
            rf'(\b[a-zA-Z_][a-zA-Z0-9_]*)\s*\[\s*(["\']){re.escape(removed_field)}\2\s*\]'
        )
        patched, count_rem_sub = pattern_rem_sub.subn(
            rf'\g<1>.get(\g<2>{removed_field}\g<2>, None)',
            patched
        )
        if count_rem_sub > 0:
            edits.append(f"Safely converted dict subscript for removed field '{removed_field}' to .get() with None fallback ({count_rem_sub} occurrence(s))")

        # B. Attribute access: user.old_field -> getattr(user, "old_field", None)
        pattern_rem_attr = re.compile(
            rf'(\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\.{re.escape(removed_field)}\b'
        )
        patched, count_rem_attr = pattern_rem_attr.subn(
            rf'getattr(\g<1>, "{removed_field}", None)',
            patched
        )
        if count_rem_attr > 0:
            edits.append(f"Safely wrapped attribute access for removed field '{removed_field}' with getattr() fallback ({count_rem_attr} occurrence(s))")

        # C. Class attribute / Pydantic model field: old_field: str
        pattern_rem_ann = re.compile(
            rf'^([ \t]*)\b{re.escape(removed_field)}\b(\s*:\s*.*)$',
            re.MULTILINE
        )
        patched, count_rem_ann = pattern_rem_ann.subn(
            rf'\g<1># [DEPRECATED] {removed_field}\g<2>',
            patched
        )
        if count_rem_ann > 0:
            edits.append(f"Commented out removed field definition '{removed_field}' ({count_rem_ann} occurrence(s))")

    # Ensure valid Python syntax with ast.parse
    try:
        ast.parse(patched)
    except SyntaxError as e:
        raise ValueError(f"Patched Python code failed AST syntax validation: {e}") from e

    return patched, edits


class PatchDiffDict(dict):
    """Dictionary mapping file paths to unified diff strings, supporting flexible path lookup."""
    def __getitem__(self, key: Any) -> str:
        try:
            return super().__getitem__(str(key))
        except KeyError:
            str_key = str(key)
            for k, v in self.items():
                if k.endswith(str_key) or str_key.endswith(k):
                    return v
            raise


def patch_consumer_directory(
    dir_path: Union[str, Path],
    diff: SchemaDiff,
    apply: bool = False
) -> Dict[str, str]:
    """
    Scans .ts, .tsx, .js, .jsx, and .py files in dir_path, applies patches,
    and returns a dict mapping file path to unified diff strings (diff -u).
    If apply is True, updates the files on disk in-place.
    """
    target_dir = Path(dir_path)
    if not target_dir.exists():
        raise FileNotFoundError(f"Target directory '{target_dir}' does not exist.")

    diffs = PatchDiffDict()
    supported_extensions = {".ts", ".tsx", ".js", ".jsx", ".py"}
    ignored_dirs = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", ".venv", "venv"}

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]

        for file_name in sorted(files):
            file_path = Path(root) / file_name
            ext = file_path.suffix.lower()
            if ext not in supported_extensions:
                continue

            try:
                original = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            if ext in {".ts", ".tsx", ".js", ".jsx"}:
                patched, edits = patch_typescript_source(original, diff)
            elif ext == ".py":
                patched, edits = patch_python_source(original, diff)
            else:
                continue

            if patched != original:
                rel_path = file_path.relative_to(target_dir)
                original_lines = original.splitlines(keepends=True)
                patched_lines = patched.splitlines(keepends=True)
                diff_lines = list(difflib.unified_diff(
                    original_lines,
                    patched_lines,
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                ))
                unified_str = "".join(diff_lines)
                diffs[str(file_path)] = unified_str

                if apply:
                    file_path.write_text(patched, encoding="utf-8")

    return diffs

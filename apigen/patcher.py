"""
Self-Maintaining API Autonomous PR & Patch Generator.
Generates code migration patches, GitHub PR bodies, and consumer client upgrade instructions
when a schema change or API drift occurs.
"""

from datetime import datetime
from apigen.diff import SchemaDiff


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
> **Generated automatically by APIGen Self-Maintaining Engine.**  
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
#### {idx}. `{c.field_name}` — {c.change_type.value}
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
- [x] Schema validated with APIGen diff engine.
- [ ] Pytest contract test suite passing against updated schemas.
- [ ] Client SDK deserialization checks verified.

---
*Created on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')} by APIGen Autonomous Agent.*
"""
    return pr

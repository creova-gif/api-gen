"""
APIGen Command Line Interface (CLI).
Enables rapid schema inspection, end-to-end API generation, schema diffing,
and self-maintaining API PR generation.
"""

import argparse
import http.server
import socketserver
import webbrowser
from pathlib import Path

from apigen.infer import infer_from_file
from apigen.planner import create_api_plan
from apigen.generator import generate_project
from apigen.diff import diff_files
from apigen.patcher import generate_pr_markdown


def cmd_inspect(args: argparse.Namespace) -> None:
    schema = infer_from_file(args.data, resource_name=args.name)
    print(f"\n✨ Inferred Schema for: {schema.resource_name} (Plural: {schema.plural_name})")
    print(f"Primary Key: {schema.primary_key}\n")
    print(f"{'Field':<20} {'Python Type':<14} {'OpenAPI Type':<14} {'Nullable':<10} {'Filter Candidate'}")
    print("-" * 75)
    for f in schema.fields:
        pk_marker = " (PK)" if f.is_primary_key else ""
        print(
            f"{f.name + pk_marker:<20} {f.python_type:<14} {f.openapi_type:<14} {str(f.nullable):<10} {str(f.is_filter_candidate)}"
        )
    print(f"\nSample records ingested: {len(schema.sample_records)}")


def cmd_generate(args: argparse.Namespace) -> None:
    data_path = Path(args.data)
    out_dir = Path(args.out) if args.out else Path(f"./generated_{data_path.stem}_api")

    print(f"\n🚀 APIGen Blueprint: Generating API from '{data_path}'...")
    schema = infer_from_file(data_path, resource_name=args.name)
    print(f"   [1/3] Inferred {len(schema.fields)} fields for resource '{schema.resource_name}'.")

    plan = create_api_plan(
        schema,
        intent=args.intent,
        auth_enabled=args.auth if hasattr(args, "auth") else None,
        mock_count=args.mock if hasattr(args, "mock") else 0,
    )
    print("   [2/3] API Plan formulated:")
    print(f"         - Endpoints: GET /{schema.plural_name}, GET /{schema.plural_name}/{{id}}", end="")
    if plan.allow_create:
        print(f", POST /{schema.plural_name}", end="")
    if plan.allow_update:
        print(f", PATCH /{schema.plural_name}/{{id}}", end="")
    if plan.allow_delete:
        print(f", DELETE /{schema.plural_name}/{{id}}", end="")
    print()
    if plan.filter_fields:
        print(f"         - Filters: {', '.join(plan.filter_fields)}")
    if plan.auth_enabled:
        print("         - Security: API Key (X-API-Key) enabled")
    if plan.mock_count > 0:
        print(f"         - Mock Synthesis: {plan.mock_count} records")

    print(f"   [3/3] Emitting artifacts to '{out_dir}'...")
    generated = generate_project(plan, out_dir)
    for rel, abs_path in generated.items():
        print(f"         + {rel}")

    print("\n✅ Success! API generation complete.")
    print("\nTo run locally:")
    print(f"  cd {out_dir}")
    print("  pip install -r requirements-dev.txt")
    print("  pytest tests/")
    print("  uvicorn app.main:app --reload\n")


def cmd_diff(args: argparse.Namespace) -> None:
    old_path = Path(args.old)
    new_path = Path(args.new)

    print(f"\n🔍 APIGen Diff: Comparing '{old_path}' vs '{new_path}'...")
    diff = diff_files(old_path, new_path, resource_name=args.name)

    if not diff.changes:
        print("✅ No schema changes detected. Data contracts are identical.\n")
        return

    print(f"\nResource: {diff.new_resource}")
    status_icon = "🚨 BREAKING CHANGES DETECTED" if diff.has_breaking_changes else "✅ All changes backward-compatible"
    print(f"Status: {status_icon}")
    print("-" * 80)
    print(f"{'Severity':<16} {'Change Type':<24} {'Field':<18} {'Details'}")
    print("-" * 80)

    for c in diff.changes:
        sev_label = f"[{c.severity.value}]"
        print(f"{sev_label:<16} {c.change_type.value:<24} {c.field_name:<18} {c.description}")

    print("-" * 80)
    print(f"Total: {len(diff.changes)} change(s) | {len(diff.breaking_changes)} breaking | {len(diff.non_breaking_changes)} non-breaking\n")

    if args.pr:
        pr_md = generate_pr_markdown(diff)
        pr_file = Path(args.pr)
        pr_file.write_text(pr_md, encoding="utf-8")
        print(f"📝 Generated Autonomous PR Markdown saved to: '{pr_file}'\n")


def cmd_studio(args: argparse.Namespace) -> None:
    port = args.port or 3000
    host = args.host
    studio_dir = Path(__file__).resolve().parent / "studio"
    if not studio_dir.exists():
        print(f"❌ Studio directory not found at: {studio_dir}")
        return

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(studio_dir), **kw)

        def log_message(self, format, *a):
            # Clean silent logger
            pass

    print("\n⚡ Launching APIGen Studio (Interactive Web UI)...")
    print(f"   URL: http://{host}:{port}")
    print(f"   Directory: {studio_dir}")
    print("   Press Ctrl+C to stop.\n")

    if not args.no_open:
        webbrowser.open(f"http://{host}:{port}")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((host, port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down APIGen Studio.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="apigen",
        description="APIGen: Self-Maintaining Schema-to-API engine generating OpenAPI 3.1, FastAPI, and Cloud Run Terraform.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect and display inferred schema from a data source")
    inspect_parser.add_argument("--data", "-d", required=True, help="Path to input file (.csv, .json, .sqlite)")
    inspect_parser.add_argument("--name", "-n", help="Override resource name")
    inspect_parser.set_defaults(func=cmd_inspect)

    # Generate
    gen_parser = subparsers.add_parser("generate", help="Generate full OpenAPI spec, FastAPI app, and Terraform")
    gen_parser.add_argument("--data", "-d", required=True, help="Path to input file (.csv, .json, .sqlite)")
    gen_parser.add_argument("--name", "-n", help="Override resource name")
    gen_parser.add_argument("--intent", "-i", help="Natural language intent (e.g. 'read-only', 'allow search and filtering')")
    gen_parser.add_argument("--auth", action="store_true", help="Enable API Key authentication (X-API-Key header)")
    gen_parser.add_argument("--mock", type=int, default=0, help="Synthesize N mock records for the schema")
    gen_parser.add_argument("--out", "-o", help="Output directory path")
    gen_parser.set_defaults(func=cmd_generate)

    # Diff (Self-Maintaining API)
    diff_parser = subparsers.add_parser("diff", help="Diff two schemas/datasets to detect breaking drift & generate PRs")
    diff_parser.add_argument("--old", "-a", required=True, help="Path to original data source (.csv, .json, .sqlite)")
    diff_parser.add_argument("--new", "-b", required=True, help="Path to updated data source (.csv, .json, .sqlite)")
    diff_parser.add_argument("--name", "-n", help="Override resource name")
    diff_parser.add_argument("--pr", "-p", help="Output file path to save automated GitHub PR markdown body")
    diff_parser.set_defaults(func=cmd_diff)

    # Studio (Interactive Web UI)
    studio_parser = subparsers.add_parser("studio", help="Launch the interactive in-browser APIGen Studio UI")
    studio_parser.add_argument("--port", "-p", type=int, default=3000, help="Port to bind server (default: 3000)")
    studio_parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1; use 0.0.0.0 to expose)")
    studio_parser.add_argument("--no-open", action="store_true", help="Do not automatically open the browser")
    studio_parser.set_defaults(func=cmd_studio)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

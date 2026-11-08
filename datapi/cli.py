"""
Datapi Command Line Interface (CLI).
Enables rapid schema inspection, end-to-end API generation, schema diffing,
self-maintaining API PR generation, and multi-cloud deployment bundling.
"""

import argparse
import http.server
import socketserver
from typing import Optional
import webbrowser
from pathlib import Path

from datapi.infer import SchemaDef, FieldDef, infer_from_file
from datapi.planner import create_api_plan
from datapi.generator import generate_project
from datapi.diff import SchemaDiff, diff_files
from datapi.patcher import generate_pr_markdown, patch_consumer_directory
from datapi.deployer import (
    generate_fly_config,
    generate_aws_manifests,
    generate_cloudrun_manifests,
    generate_deployment_bundle,
)


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

    print(f"\n🚀 Datapi: Generating API from '{data_path}'...")
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

    print(f"\n🔍 Datapi Diff: Comparing '{old_path}' vs '{new_path}'...")
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


def cmd_patch(args: argparse.Namespace) -> None:
    target_dir = Path(getattr(args, "consumer_dir", None) or getattr(args, "target_dir", None) or ".")
    if not target_dir.exists():
        print(f"❌ Error: Target directory '{target_dir}' does not exist.")
        return

    diff: Optional[SchemaDiff] = None
    diff_arg = getattr(args, "diff", None)
    old_arg = getattr(args, "old", None)
    new_arg = getattr(args, "new", None)

    if diff_arg:
        diff_path = Path(diff_arg)
        if not diff_path.exists():
            print(f"❌ Error: Diff file '{diff_path}' does not exist.")
            return
        try:
            diff = SchemaDiff.from_json(diff_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"❌ Error loading diff from '{diff_path}': {e}")
            return
    elif old_arg and new_arg:
        name = getattr(args, "name", None)
        diff = diff_files(old_arg, new_arg, resource_name=name)
    else:
        print("❌ Error: Must provide either --diff <diff.json> or both --old <orig_file> and --new <updated_file>.")
        return

    apply = getattr(args, "apply", False)
    print(f"\n🔍 Datapi Autonomous Code Patcher: Scanning '{target_dir}' for consumers...")
    patches = patch_consumer_directory(target_dir, diff, apply=apply)

    if not patches:
        print("✨ No changes needed. Consumer files match updated schema.\n")
        return

    print(f"\n⚡ Generated patches for {len(patches)} file(s):\n")
    for file_path, diff_content in patches.items():
        print(f"--- File: {file_path} ---")
        print(diff_content)

    if apply:
        print(f"✅ Successfully applied patches to {len(patches)} file(s) in '{target_dir}'.\n")
    else:
        print(f"ℹ️ Dry-run mode: {len(patches)} file(s) would be modified. Use '--apply' to write changes to disk.\n")


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

    print("\n⚡ Launching Datapi Studio (Interactive Web UI)...")
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
            print("\nShutting down Datapi Studio.")


def cmd_deploy(args: argparse.Namespace) -> None:
    target = getattr(args, "target", "all") or "all"
    name = getattr(args, "name", None)
    data = getattr(args, "data", None)
    auth = getattr(args, "auth", False)
    dry_run = getattr(args, "dry_run", False)
    out_dir = Path(args.out) if getattr(args, "out", None) else Path("./deploy")

    if data:
        schema = infer_from_file(data, resource_name=name)
        plan = create_api_plan(schema, auth_enabled=auth)
        service_name = name or f"{schema.resource_name.lower()}-api"
    else:
        resource_name = name or "datapi-service"
        schema = SchemaDef(
            resource_name=resource_name,
            plural_name=f"{resource_name}s",
            primary_key="id",
            fields=[FieldDef(name="id", python_type="int", openapi_type="integer", is_primary_key=True)],
            sample_records=[],
        )
        plan = create_api_plan(schema, auth_enabled=auth)
        service_name = resource_name

    if dry_run:
        if target == "fly":
            print(generate_fly_config(plan, app_name=service_name))
        elif target == "aws":
            print(generate_aws_manifests(plan, service_name=service_name))
        elif target == "cloudrun":
            print(generate_cloudrun_manifests(plan, service_name=service_name))
        elif target == "all":
            print("# --- fly.toml ---")
            print(generate_fly_config(plan, app_name=service_name))
            print("\n# --- terraform/aws_apprunner.tf ---")
            print(generate_aws_manifests(plan, service_name=service_name))
            print("\n# --- terraform/main.tf (Cloud Run) ---")
            print(generate_cloudrun_manifests(plan, service_name=service_name))
        return

    print(f"\n🚀 Datapi Deploy: Generating deployment manifests for target '{target}'...")
    generated = generate_deployment_bundle(plan, target=target, out_dir=out_dir, service_name=service_name)
    for p in generated:
        print(f"   + {p}")
    print(f"✅ Success! Deployment files written to '{out_dir}'.\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datapi",
        description="Datapi: Raw data in. Production APIs out. Self-Maintaining Schema-to-API engine generating OpenAPI 3.1, FastAPI, and Cloud Run Terraform.",
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

    # Patch (Self-Maintaining Code Migration)
    patch_parser = subparsers.add_parser("patch", help="Auto-patch consumer codebases (.ts, .py) when schemas drift")
    patch_parser.add_argument(
        "--consumer-dir",
        "--target-dir",
        dest="consumer_dir",
        default=".",
        help="Directory containing consumer codebase (.ts, .tsx, .py; default: .)",
    )
    patch_parser.add_argument(
        "--diff",
        "-f",
        help="Path to schema diff JSON file",
    )
    patch_parser.add_argument(
        "--old",
        "-a",
        help="Path to original data file (alternative to --diff)",
    )
    patch_parser.add_argument(
        "--new",
        "-b",
        help="Path to updated data file (alternative to --diff)",
    )
    patch_parser.add_argument(
        "--name",
        "-n",
        help="Override resource name",
    )
    patch_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply patches in-place to consumer files",
    )
    patch_parser.set_defaults(func=cmd_patch)

    # Studio (Interactive Web UI)
    studio_parser = subparsers.add_parser("studio", help="Launch the interactive in-browser Datapi Studio UI")
    studio_parser.add_argument("--port", "-p", type=int, default=3000, help="Port to bind server (default: 3000)")
    studio_parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1; use 0.0.0.0 to expose)")
    studio_parser.add_argument("--no-open", action="store_true", help="Do not automatically open the browser")
    studio_parser.set_defaults(func=cmd_studio)

    # Deploy
    deploy_parser = subparsers.add_parser("deploy", help="Generate deployment bundles for Cloud Run, Fly.io, AWS App Runner, or all targets")
    deploy_parser.add_argument(
        "--target",
        "-t",
        choices=["cloudrun", "fly", "aws", "all"],
        default="all",
        help="Target deployment platform (cloudrun, fly, aws, all; default: all)",
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated configuration to stdout without writing files",
    )
    deploy_parser.add_argument(
        "--out",
        "-o",
        help="Output directory path (default: ./deploy)",
    )
    deploy_parser.add_argument(
        "--data",
        "-d",
        help="Optional path to input file (.csv, .json, .sqlite)",
    )
    deploy_parser.add_argument(
        "--name",
        "-n",
        help="Override resource or service name",
    )
    deploy_parser.add_argument(
        "--auth",
        action="store_true",
        help="Enable API Key authentication in deployment configs",
    )
    deploy_parser.set_defaults(func=cmd_deploy)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

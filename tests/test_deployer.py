"""
Unit tests for datapi.deployer and CLI deploy subcommand.
Tests Fly.io config generation, AWS App Runner Terraform manifests,
deployment bundle generation, and CLI deploy execution.
"""

import contextlib
import io
import json
import tempfile
import tomllib
from pathlib import Path
import unittest

from datapi.infer import SchemaDef, FieldDef, infer_schema_from_records
from datapi.planner import APIPlan, create_api_plan
from datapi.deployer import (
    generate_fly_config,
    generate_aws_manifests,
    generate_cloudrun_manifests,
    generate_deployment_bundle,
)
from datapi.cli import build_parser, main


def _create_sample_plan(auth_enabled: bool = False, resource_name: str = "widget") -> APIPlan:
    schema = SchemaDef(
        resource_name=resource_name,
        plural_name=f"{resource_name}s",
        primary_key="id",
        fields=[
            FieldDef(name="id", python_type="int", openapi_type="integer", is_primary_key=True),
            FieldDef(name="title", python_type="str", openapi_type="string", is_filter_candidate=True),
            FieldDef(name="price", python_type="float", openapi_type="number"),
        ],
        sample_records=[{"id": 1, "title": "Gadget A", "price": 19.99}],
    )
    return create_api_plan(schema, auth_enabled=auth_enabled)


class TestFlyConfig(unittest.TestCase):
    def setUp(self):
        self.plan = _create_sample_plan()

    def test_fly_config_valid_toml_and_keys(self):
        """Verifies valid TOML structure, app name, region, and build block."""
        toml_content = generate_fly_config(self.plan, app_name="datapi-service")
        data = tomllib.loads(toml_content)

        self.assertEqual(data["app"], "datapi-service")
        self.assertEqual(data["primary_region"], "iad")
        self.assertEqual(data["build"]["dockerfile"], "Dockerfile")

    def test_fly_config_port_8000_and_http_service(self):
        """Verifies port 8000, zero-scaling, and HTTPS enforcement."""
        toml_content = generate_fly_config(self.plan)
        data = tomllib.loads(toml_content)

        http_service = data["http_service"]
        self.assertEqual(http_service["internal_port"], 8000)
        self.assertTrue(http_service["force_https"])
        self.assertTrue(http_service["auto_stop_machines"])
        self.assertEqual(http_service["min_machines_running"], 0)

    def test_fly_config_health_check(self):
        """Verifies [[services.http_checks]] hitting /healthz."""
        toml_content = generate_fly_config(self.plan)
        data = tomllib.loads(toml_content)

        self.assertIn("services", data)
        self.assertIn("http_checks", data["services"])
        checks = data["services"]["http_checks"]
        self.assertGreater(len(checks), 0)

        health_check = checks[0]
        self.assertEqual(health_check["path"], "/healthz")
        self.assertEqual(health_check["method"], "get")
        self.assertEqual(health_check["protocol"], "http")

    def test_fly_config_custom_region_and_app_name(self):
        """Verifies configurability of primary_region and app_name."""
        toml_content = generate_fly_config(self.plan, app_name="custom-inventory", primary_region="fra")
        data = tomllib.loads(toml_content)

        self.assertEqual(data["app"], "custom-inventory")
        self.assertEqual(data["primary_region"], "fra")

    def test_fly_config_auth_enabled(self):
        """Verifies auth_enabled keeps valid TOML and documents API key."""
        plan_auth = _create_sample_plan(auth_enabled=True)
        toml_content = generate_fly_config(plan_auth)
        data = tomllib.loads(toml_content)
        self.assertEqual(data["http_service"]["internal_port"], 8000)
        self.assertIn("env", data)


class TestAWSManifests(unittest.TestCase):
    def setUp(self):
        self.plan = _create_sample_plan()

    def test_aws_manifests_apprunner_resource_block(self):
        """Verifies aws_apprunner_service resource block is present."""
        hcl = generate_aws_manifests(self.plan, service_name="datapi-service")
        self.assertIn('resource "aws_apprunner_service"', hcl)
        self.assertIn('service_name = "datapi-service"', hcl)

    def test_aws_manifests_autoscaling_bounds(self):
        """Verifies auto-scaling configuration with min 1 and max 5."""
        hcl = generate_aws_manifests(self.plan)
        self.assertIn('resource "aws_apprunner_auto_scaling_configuration_version"', hcl)
        self.assertIn("min_size                        = 1", hcl)
        self.assertIn("max_size                        = 5", hcl)

    def test_aws_manifests_port_8000(self):
        """Verifies App Runner port is configured to 8000."""
        hcl = generate_aws_manifests(self.plan)
        self.assertIn('port = "8000"', hcl)

    def test_aws_manifests_health_check(self):
        """Verifies health check path /healthz in health_check_configuration."""
        hcl = generate_aws_manifests(self.plan)
        self.assertIn("health_check_configuration {", hcl)
        self.assertIn('path                = "/healthz"', hcl)
        self.assertIn('protocol            = "HTTP"', hcl)

    def test_aws_manifests_custom_service_name_and_auth(self):
        """Verifies custom service naming and auth environment injection."""
        plan_auth = _create_sample_plan(auth_enabled=True, resource_name="order")
        hcl = generate_aws_manifests(plan_auth, service_name="order-api")
        self.assertIn('service_name = "order-api"', hcl)
        self.assertIn('order_api_scaling', hcl)
        self.assertIn('API_KEY', hcl)


class TestDeploymentBundle(unittest.TestCase):
    def setUp(self):
        self.plan = _create_sample_plan()

    def test_bundle_fly_target_only(self):
        """Verifies only fly.toml is generated when target is fly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_deployment_bundle(self.plan, target="fly", out_dir=out_path)

            self.assertEqual(len(files), 1)
            fly_path = out_path / "fly.toml"
            self.assertTrue(fly_path.exists())
            self.assertIn(str(fly_path), files)

            # Ensure terraform dir is not created
            self.assertFalse((out_path / "terraform").exists())

            # Verify valid content
            data = tomllib.loads(fly_path.read_text(encoding="utf-8"))
            self.assertEqual(data["http_service"]["internal_port"], 8000)

    def test_bundle_aws_target_only(self):
        """Verifies terraform/aws_apprunner.tf is generated when target is aws."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_deployment_bundle(self.plan, target="aws", out_dir=out_path)

            self.assertEqual(len(files), 1)
            aws_path = out_path / "terraform" / "aws_apprunner.tf"
            self.assertTrue(aws_path.exists())
            self.assertIn(str(aws_path), files)

            # Ensure fly.toml is not created
            self.assertFalse((out_path / "fly.toml").exists())

            content = aws_path.read_text(encoding="utf-8")
            self.assertIn("aws_apprunner_service", content)

    def test_bundle_cloudrun_target_only(self):
        """Verifies terraform/main.tf is generated when target is cloudrun."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_deployment_bundle(self.plan, target="cloudrun", out_dir=out_path)

            self.assertEqual(len(files), 1)
            cr_path = out_path / "terraform" / "main.tf"
            self.assertTrue(cr_path.exists())
            self.assertIn(str(cr_path), files)

            # Ensure fly.toml is not created
            self.assertFalse((out_path / "fly.toml").exists())

            content = cr_path.read_text(encoding="utf-8")
            self.assertIn("google_cloud_run_v2_service", content)

    def test_bundle_all_targets(self):
        """Verifies all deployment manifests are generated when target is all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            files = generate_deployment_bundle(self.plan, target="all", out_dir=out_path)

            self.assertEqual(len(files), 3)
            self.assertTrue((out_path / "fly.toml").exists())
            self.assertTrue((out_path / "terraform" / "aws_apprunner.tf").exists())
            self.assertTrue((out_path / "terraform" / "main.tf").exists())

    def test_bundle_invalid_target_raises(self):
        """Verifies invalid targets raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                generate_deployment_bundle(self.plan, target="unknown-cloud", out_dir=Path(tmpdir))


class TestCLIDeployCommand(unittest.TestCase):
    def test_cli_deploy_dry_run_fly(self):
        """Verifies dry-run fly output without creating files."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["deploy", "--target", "fly", "--dry-run"])

        output = buf.getvalue()
        self.assertIn('app = "datapi-service"', output)
        self.assertIn("internal_port = 8000", output)
        self.assertIn('path = "/healthz"', output)

        # Confirm valid TOML parse of the dry-run output
        data = tomllib.loads(output)
        self.assertEqual(data["app"], "datapi-service")

    def test_cli_deploy_dry_run_aws(self):
        """Verifies dry-run aws output contains App Runner resources and health check."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["deploy", "--target", "aws", "--dry-run"])

        output = buf.getvalue()
        self.assertIn('resource "aws_apprunner_service"', output)
        self.assertIn('port = "8000"', output)
        self.assertIn("min_size                        = 1", output)
        self.assertIn("max_size                        = 5", output)
        self.assertIn('path                = "/healthz"', output)

    def test_cli_deploy_dry_run_cloudrun(self):
        """Verifies dry-run cloudrun output contains Cloud Run resources."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["deploy", "--target", "cloudrun", "--dry-run"])

        output = buf.getvalue()
        self.assertIn("google_cloud_run_v2_service", output)

    def test_cli_deploy_dry_run_all(self):
        """Verifies dry-run all outputs all target configurations."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["deploy", "--target", "all", "--dry-run"])

        output = buf.getvalue()
        self.assertIn("fly.toml", output)
        self.assertIn("aws_apprunner", output)
        self.assertIn("google_cloud_run_v2_service", output)

    def test_cli_deploy_write_files_to_out(self):
        """Verifies CLI writes deployment bundle to specified --out directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["deploy", "--target", "all", "--out", tmpdir])

            out_path = Path(tmpdir)
            self.assertTrue((out_path / "fly.toml").exists())
            self.assertTrue((out_path / "terraform" / "aws_apprunner.tf").exists())
            self.assertTrue((out_path / "terraform" / "main.tf").exists())

    def test_cli_deploy_with_data_source(self):
        """Verifies CLI infers resource name from data input."""
        records = [
            {"customer_id": 101, "company": "Acme Corp", "active": True},
            {"customer_id": 102, "company": "Beta LLC", "active": False},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_data_path = Path(tmpdir) / "customers.json"
            temp_data_path.write_text(json.dumps(records), encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["deploy", "--data", str(temp_data_path), "--target", "fly", "--dry-run"])

            output = buf.getvalue()
            data = tomllib.loads(output)
            self.assertIn("customer", data["app"].lower())
            self.assertEqual(data["http_service"]["internal_port"], 8000)

    def test_cli_deploy_with_custom_name(self):
        """Verifies CLI uses --name when provided."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["deploy", "--name", "payments-engine", "--target", "fly", "--dry-run"])

        output = buf.getvalue()
        data = tomllib.loads(output)
        self.assertEqual(data["app"], "payments-engine")


if __name__ == "__main__":
    unittest.main()

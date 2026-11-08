"""
Datapi: Raw data in. Production APIs out.
"""

__version__ = "0.1.0"

from datapi.deployer import (
    generate_fly_config,
    generate_aws_manifests,
    generate_cloudrun_manifests,
    generate_deployment_bundle,
)
from datapi.patcher import (
    generate_migration_summary,
    generate_pr_markdown,
    patch_typescript_source,
    patch_python_source,
    patch_consumer_directory,
)

__all__ = [
    "__version__",
    "generate_fly_config",
    "generate_aws_manifests",
    "generate_cloudrun_manifests",
    "generate_deployment_bundle",
    "generate_migration_summary",
    "generate_pr_markdown",
    "patch_typescript_source",
    "patch_python_source",
    "patch_consumer_directory",
]

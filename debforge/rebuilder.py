from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from . import docker_client
from .config import DebforgeConfig
from .exceptions import BuildError
from .network import container_proxy_environment
from .package_list import PackageSpec
from .signing import sign_artifacts, validate_signing_secrets

logger = logging.getLogger(__name__)


def rebuild_packages(
    packages: list[PackageSpec],
    config: DebforgeConfig,
    *,
    rebuild_image: bool = False,
) -> dict[str, object]:
    validate_signing_secrets(
        config.signing_mode,
        config.gpg_private_key_secret,
        config.gpg_passphrase_secret,
    )
    os.makedirs(config.work_dir, exist_ok=True)
    run_dir = tempfile.mkdtemp(prefix="run-", dir=config.work_dir)
    input_path = os.path.join(run_dir, "packages.tsv")
    Path(input_path).write_text(
        "".join(f"{package.name}\t{package.version}\n" for package in packages),
        encoding="utf-8",
    )

    try:
        docker_client.ensure_image(
            config.docker_image,
            config.docker_dockerfile,
            force_rebuild=rebuild_image,
        )
        command = [
            "python3",
            "/usr/local/lib/debforge/build_packages.py",
            "--input",
            "/build/packages.tsv",
            "--work-dir",
            "/build",
            "--architecture",
            config.target_architecture,
            "--mirror",
            config.source_mirror,
            "--suite",
            config.source_suite,
            "--components",
            ",".join(config.source_components),
            "--pockets",
            ",".join(config.source_pockets),
            "--repositories-json",
            json.dumps(config.source_repositories),
            "--build-options",
            config.build_options,
        ]
        container_env = {
            "DEBIAN_FRONTEND": "noninteractive",
            **container_proxy_environment(),
        }
        exit_code, logs = docker_client.run_build_container(
            image=config.docker_image,
            source_dir=run_dir,
            command=command,
            env=container_env,
        )

        result_path = os.path.join(run_dir, "result.json")
        if not os.path.isfile(result_path):
            raise BuildError(
                f"Builder exited with code {exit_code} without result.json.\n"
                + "\n".join(logs.splitlines()[-40:])
            )
        result = json.loads(Path(result_path).read_text(encoding="utf-8"))

        successful = [entry for entry in result["packages"] if entry["success"]]
        artifact_paths = [
            os.path.join(run_dir, "output", filename)
            for entry in successful
            for filename in entry["artifacts"]
        ]
        signing = (
            sign_artifacts(
                artifact_paths,
                config.signing_mode,
                image=config.docker_image,
                workspace=run_dir,
                key_id=config.gpg_key_id,
                private_key_secret=config.gpg_private_key_secret,
                passphrase_secret=config.gpg_passphrase_secret,
            )
            if artifact_paths
            else {
                "mode": config.signing_mode,
                "signed": False,
                "artifacts": [],
            }
        )

        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for artifact_path in artifact_paths:
            destination = output_dir / Path(artifact_path).name
            shutil.copy2(artifact_path, destination)
            copied.append(str(destination))

        manifest = {
            "builder_image": config.docker_image,
            "builder_base": "debian:12.0",
            "architecture": result.get("architecture", config.target_architecture),
            "suite": config.source_suite,
            "mirror": config.source_mirror,
            "signing": signing,
            "packages": result["packages"],
            "artifacts": copied,
        }
        manifest_path = output_dir / "build-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        failures = [entry for entry in result["packages"] if not entry["success"]]
        if exit_code != 0 or failures:
            details = "; ".join(
                f"{entry['name']}={entry['version']}: {entry.get('error', 'build failed')}"
                for entry in failures
            )
            raise BuildError(
                f"{len(failures)} package(s) failed; successful artifacts were preserved in "
                f"{output_dir}: {details}"
            )

        logger.info("Built %d package(s) into %s", len(successful), output_dir)
        return manifest
    finally:
        # Defense in depth if the container is killed before its own cleanup:
        # keep-artifacts must never retain the corporate proxy credential.
        Path(run_dir, "apt-sandbox", "etc", "auth.conf").unlink(missing_ok=True)
        if not config.keep_build_artifacts:
            shutil.rmtree(run_dir, ignore_errors=True)

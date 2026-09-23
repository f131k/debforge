from __future__ import annotations

import json
import logging
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from .config import DebforgeConfig
from .exceptions import BuildError, DownloadError
from .network import load_network_config
from .package_list import PackageSpec
from .steps import build, download, sign_package

logger = logging.getLogger(__name__)


def rebuild_packages(
    packages: list[PackageSpec],
    config: DebforgeConfig,
) -> dict[str, object]:
    """Run the complete rebuild pipeline in the current (builder) container."""
    sign_package.validate_signing_secrets(
        config.gpg_private_key_secret,
        config.gpg_passphrase_secret,
    )
    work_root = Path(config.work_dir)
    work_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=work_root))
    sandbox: download.AptSandbox | None = None

    architecture = (
        download.resolve_native_architecture()
        if config.target_architecture == "native"
        else config.target_architecture
    )
    entries: dict[PackageSpec, dict[str, object]] = {
        package: {
            "name": package.name,
            "version": package.version,
            "success": False,
            "source": None,
            "artifacts": [],
        }
        for package in packages
    }
    signing: dict[str, object] = {"mode": "debsigs", "signed": False, "artifacts": []}

    try:
        sandbox = download.setup_apt_sandbox(
            run_dir / "apt-sandbox",
            packages,
            architecture,
            config,
            load_network_config(),
        )
        download.update_package_indexes(sandbox)

        groups: dict[download.SourceSpec, list[PackageSpec]] = defaultdict(list)
        for package in packages:
            try:
                groups[download.resolve_source(package, architecture, sandbox)].append(package)
            except DownloadError as exc:
                entries[package]["error"] = str(exc)

        native_architecture = build.prepare_build_environment(architecture, sandbox)
        artifact_paths: list[Path] = []
        for source, requested in groups.items():
            logger.info("Building source %s for %d requested package(s)", source.display, len(requested))
            try:
                artifacts = build.build_source(
                    source,
                    requested,
                    run_dir,
                    architecture,
                    native_architecture,
                    sandbox,
                    config.build_options,
                )
                for package in requested:
                    package_artifacts = artifacts.get(package.name, [])
                    entries[package]["source"] = source.display
                    entries[package]["artifacts"] = [path.name for path in package_artifacts]
                    entries[package]["success"] = bool(package_artifacts)
                    artifact_paths.extend(package_artifacts)
                    if not package_artifacts:
                        entries[package]["error"] = "requested binary package was not produced"
            except BuildError as exc:
                for package in requested:
                    entries[package]["source"] = source.display
                    entries[package]["error"] = str(exc)

        unique_artifacts = list(dict.fromkeys(artifact_paths))
        if unique_artifacts:
            signing = sign_package.sign_packages(
                unique_artifacts,
                config.gpg_key_id,
                config.gpg_private_key_secret,
                config.gpg_passphrase_secret,
            )

        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for artifact in unique_artifacts:
            destination = output_dir / artifact.name
            shutil.copy2(artifact, destination)
            copied.append(str(destination))

        package_entries = [entries[package] for package in packages]
        manifest: dict[str, object] = {
            "builder_base": "debian:12.0",
            "architecture": architecture,
            "suite": config.source_suite,
            "mirror": config.source_mirror,
            "signing": signing,
            "packages": package_entries,
            "artifacts": copied,
        }
        (output_dir / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

        failures = [entry for entry in package_entries if not entry["success"]]
        if failures:
            details = "; ".join(
                f"{entry['name']}={entry['version']}: {entry.get('error', 'build failed')}"
                for entry in failures
            )
            raise BuildError(
                f"{len(failures)} package(s) failed; successful signed artifacts were preserved "
                f"in {output_dir}: {details}"
            )
        logger.info("Built and signed %d requested package(s) into %s", len(packages), output_dir)
        return manifest
    finally:
        if sandbox is not None:
            sandbox.remove_credentials()
        if not config.keep_build_artifacts:
            shutil.rmtree(run_dir, ignore_errors=True)

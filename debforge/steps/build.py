from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from ..exceptions import BuildError, DownloadError
from ..package_list import PackageSpec
from .download import AptSandbox, SourceSpec, capture_command, fetch_source, run_command

logger = logging.getLogger(__name__)


def prepare_build_environment(architecture: str, sandbox: AptSandbox) -> str:
    """Prepare the running container for native or cross compilation."""
    native_arch = capture_command(
        ["dpkg", "--print-architecture"], env=sandbox.build_env
    ).strip()
    if architecture != native_arch:
        run_command(["dpkg", "--add-architecture", architecture], env=sandbox.build_env)
        run_command(["apt-get", "update"], env=sandbox.build_env)
        run_command(
            [
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                f"crossbuild-essential-{architecture}",
            ],
            env=sandbox.build_env,
        )
    return native_arch


def build_source(
    source: SourceSpec,
    requested: list[PackageSpec],
    root: Path,
    architecture: str,
    native_architecture: str,
    sandbox: AptSandbox,
    build_options: str,
) -> dict[str, list[Path]]:
    """Download and build one source package directly in the current container."""
    safe_name = re.sub(r"[^a-zA-Z0-9_.+-]", "_", source.display)
    source_root = root / "sources" / safe_name
    try:
        unpacked = fetch_source(source, source_root / "download", sandbox)
        run_command(
            [
                "apt-get",
                "build-dep",
                "-y",
                "--no-install-recommends",
                f"--host-architecture={architecture}",
                source.display,
            ],
            cwd=unpacked,
            env=sandbox.build_env,
        )
    except DownloadError as exc:
        raise BuildError(f"{source.display}: {exc}") from exc

    found: dict[str, list[Path]] = defaultdict(list)
    output_dir = root / "unsigned"
    output_dir.mkdir(exist_ok=True)
    packages_by_version: dict[str, list[PackageSpec]] = defaultdict(list)
    for package in requested:
        packages_by_version[package.version].append(package)

    for binary_version, version_packages in packages_by_version.items():
        variant_parent = source_root / "builds" / _safe_component(binary_version)
        variant_source = variant_parent / unpacked.name
        variant_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(unpacked, variant_source, symlinks=True)
        package_env = dict(
            sandbox.build_env,
            DEB_BUILD_OPTIONS=build_options,
            DEBFULLNAME="debforge",
            DEBEMAIL="debforge@localhost",
        )
        try:
            if binary_version != source.version:
                _set_binary_version(variant_source, binary_version, package_env)
            command = ["dpkg-buildpackage", "--no-sign", "--build=binary"]
            if architecture != native_architecture:
                command.append(f"--host-arch={architecture}")
            run_command(command, cwd=variant_source, env=package_env)
        except DownloadError as exc:
            raise BuildError(f"{source.display} as binary version {binary_version}: {exc}") from exc

        wanted = {
            (package.name.split(":", 1)[0], package.version): package
            for package in version_packages
        }
        for artifact in variant_parent.glob("*.deb"):
            binary_name, version, artifact_arch = _deb_fields(artifact)
            matched_package = wanted.get((binary_name, version))
            if matched_package and artifact_arch in {architecture, "all"}:
                destination = output_dir / artifact.name
                shutil.copy2(artifact, destination)
                found[matched_package.name].append(destination)
    return dict(found)


def _set_binary_version(source_dir: Path, version: str, env: dict[str, str]) -> None:
    """Create a local changelog entry for an exact binNMU/vendor binary version."""
    run_command(
        [
            "dch",
            "--no-conf",
            "--newversion",
            version,
            "--distribution",
            "UNRELEASED",
            "--force-distribution",
            "Rebuild exact installed binary version.",
        ],
        cwd=source_dir,
        env=env,
    )


def _safe_component(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.+-]", "_", value)


def _deb_fields(path: Path) -> tuple[str, str, str]:
    process = subprocess.run(
        [
            "dpkg-deb",
            "--show",
            "--showformat=${Package}\t${Version}\t${Architecture}\n",
            str(path),
        ],
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise BuildError(process.stderr.strip() or f"cannot inspect {path.name}")
    values = process.stdout.rstrip("\n").split("\t")
    if len(values) != 3:
        raise BuildError(f"unexpected dpkg-deb metadata for {path.name}")
    return values[0], values[1], values[2]

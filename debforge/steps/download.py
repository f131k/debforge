from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from ..config import DebforgeConfig
from ..exceptions import DownloadError
from ..network import NetworkConfig, load_network_config
from ..package_list import PackageSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    version: str

    @property
    def display(self) -> str:
        return f"{self.name}={self.version}"


@dataclass(frozen=True)
class AptSandbox:
    metadata_env: dict[str, str]
    build_env: dict[str, str]
    auth_path: Path

    def remove_credentials(self) -> None:
        self.auth_path.unlink(missing_ok=True)


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    logger.info("Running: %s", " ".join(command))
    process = subprocess.run(command, cwd=cwd, env=env, text=True, check=False)
    if process.returncode != 0:
        raise DownloadError(
            f"command exited with status {process.returncode}: {' '.join(command)}"
        )


def capture_command(command: list[str], *, env: dict[str, str]) -> str:
    logger.debug("Running: %s", " ".join(command))
    process = subprocess.run(
        command,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise DownloadError(
            process.stderr.strip()
            or f"command exited with status {process.returncode}: {' '.join(command)}"
        )
    return process.stdout


def resolve_native_architecture() -> str:
    return capture_command(["dpkg", "--print-architecture"], env=dict(os.environ)).strip()


def setup_apt_sandbox(
    root: Path,
    packages: list[PackageSpec],
    architecture: str,
    config: DebforgeConfig,
    network: NetworkConfig | None = None,
) -> AptSandbox:
    """Create an isolated APT configuration without using host/container APT state."""
    network = network or load_network_config()
    etc = root / "etc"
    state = root / "state"
    cache = root / "cache"
    for directory in (etc, state / "lists" / "partial", cache / "archives" / "partial"):
        directory.mkdir(parents=True, exist_ok=True)

    native_arch = resolve_native_architecture()
    architectures = list(dict.fromkeys([native_arch, architecture]))
    sources = etc / "sources.list"
    sources.write_text(
        "\n".join(_source_lines(config, architectures, network)) + "\n",
        encoding="utf-8",
    )

    baseline = state / "baseline-status"
    baseline.write_text(_render_status(packages, architecture), encoding="utf-8")
    auth_path = etc / "auth.conf"

    common = [
        f'Dir::Etc::sourcelist "{sources}";',
        'Dir::Etc::sourceparts "/dev/null";',
        'Dir::Etc::trusted "";',
        'Dir::Etc::trustedparts "/etc/apt/trusted.gpg.d";',
        f'Dir::State "{state}";',
        f'Dir::Cache "{cache}";',
        f'APT::Architecture "{architecture}";',
        "APT::Architectures { " + " ".join(f'\"{arch}\";' for arch in architectures) + " };",
        'APT::Install-Recommends "false";',
        'APT::Install-Suggests "false";',
        'Acquire::Retries "3";',
    ]
    if network.is_corporate:
        assert network.proxy_host is not None and network.proxy_token is not None
        auth_path.write_text(
            f"machine {network.proxy_host} login token password {network.proxy_token}\n",
            encoding="utf-8",
        )
        auth_path.chmod(0o600)
        common.extend(
            [
                f'Dir::Etc::netrc "{auth_path}";',
                'Acquire::AllowInsecureRepositories "true";',
                'Acquire::AllowDowngradeToInsecureRepositories "true";',
                f'Acquire::https::{network.proxy_host}::Verify-Peer "false";',
                f'Acquire::https::{network.proxy_host}::Verify-Host "false";',
            ]
        )
        logger.info("Corporate APT proxy enabled (%s)", network.proxy_host)

    metadata_conf = etc / "metadata.conf"
    metadata_conf.write_text(
        "\n".join([*common, f'Dir::State::status "{baseline}";', ""]),
        encoding="utf-8",
    )
    build_conf = etc / "build.conf"
    build_conf.write_text(
        "\n".join([*common, 'Dir::State::status "/var/lib/dpkg/status";', ""]),
        encoding="utf-8",
    )
    base_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    return AptSandbox(
        metadata_env=dict(base_env, APT_CONFIG=str(metadata_conf)),
        build_env=dict(base_env, APT_CONFIG=str(build_conf)),
        auth_path=auth_path,
    )


def update_package_indexes(sandbox: AptSandbox) -> None:
    run_command(["apt-get", "update"], env=sandbox.metadata_env)


def resolve_source(
    package: PackageSpec,
    architecture: str,
    sandbox: AptSandbox,
) -> SourceSpec:
    qualified_name = package.name if ":" in package.name else f"{package.name}:{architecture}"
    output = capture_command(
        ["apt-cache", "show", f"{qualified_name}={package.version}"],
        env=sandbox.metadata_env,
    )
    paragraph = output.split("\n\n", 1)[0]
    fields: dict[str, str] = {}
    for line in paragraph.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value
    if fields.get("Version") != package.version:
        raise DownloadError(f"APT returned no exact version for {package.display}")

    source_value = fields.get("Source", package.name.split(":", 1)[0])
    match = re.fullmatch(r"([^ ]+)(?: \(([^)]+)\))?", source_value)
    if not match:
        raise DownloadError(f"cannot parse Source field {source_value!r}")
    return SourceSpec(match.group(1), match.group(2) or package.version)


def fetch_source(source: SourceSpec, destination: Path, sandbox: AptSandbox) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading source package %s", source.display)
    run_command(
        ["apt-get", "source", source.display],
        cwd=destination,
        env=sandbox.metadata_env,
    )
    candidates = [path.parent.parent for path in destination.glob("*/debian/changelog")]
    if len(candidates) != 1:
        raise DownloadError(
            f"expected one unpacked source directory for {source.display}, found {len(candidates)}"
        )
    return candidates[0]


def _render_status(packages: list[PackageSpec], architecture: str) -> str:
    return "\n".join(
        f"Package: {package.name.split(':', 1)[0]}\n"
        "Status: install ok installed\n"
        f"Architecture: {architecture}\n"
        f"Version: {package.version}\n"
        for package in packages
    )


def _source_lines(
    config: DebforgeConfig,
    architectures: list[str],
    network: NetworkConfig,
) -> list[str]:
    lines: list[str] = []
    if config.source_repositories:
        for repository in config.source_repositories:
            suites = [str(item) for item in cast(list[object], repository["suites"])]
            is_security = any(suite.endswith("-security") for suite in suites)
            mirror = network.mirror_url(
                str(repository["mirror"]).rstrip("/"), security=is_security
            )
            components = " ".join(
                str(item) for item in cast(list[object], repository["components"])
            )
            signed_by = repository.get("signed_by")
            insecure = urlsplit(mirror).hostname == network.proxy_host
            binary_options = [f"arch={','.join(architectures)}"]
            source_options: list[str] = []
            if signed_by:
                binary_options.append(f"signed-by={signed_by}")
                source_options.append(f"signed-by={signed_by}")
            if insecure:
                trust = [
                    "trusted=yes",
                    "allow-insecure=yes",
                    "allow-downgrade-to-insecure=yes",
                ]
                binary_options.extend(trust)
                source_options.extend(trust)
            source_option_text = f" [{','.join(source_options)}]" if source_options else ""
            for suite in suites:
                lines.extend(
                    [
                        f"deb [{','.join(binary_options)}] {mirror} {suite} {components}",
                        f"deb-src{source_option_text} {mirror} {suite} {components}",
                    ]
                )
        return lines

    component_text = " ".join(config.source_components)
    for pocket in config.source_pockets:
        suite = config.source_suite + pocket
        mirror = network.mirror_url(config.source_mirror)
        insecure = urlsplit(mirror).hostname == network.proxy_host
        architecture_option = f"arch={','.join(architectures)}"
        trust = (
            ["trusted=yes", "allow-insecure=yes", "allow-downgrade-to-insecure=yes"]
            if insecure
            else []
        )
        lines.extend(
            [
                (
                    f"deb [{','.join([architecture_option, *trust])}] "
                    f"{mirror} {suite} {component_text}"
                ),
                (
                    f"deb-src{' [' + ','.join(trust) + ']' if trust else ''} "
                    f"{mirror} {suite} {component_text}"
                ),
            ]
        )
    return lines

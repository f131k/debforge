from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROXY_HOST_ENV = "DEBSEC_PROXY_HOST"
PROXY_TOKEN_ENV = "DEBSEC_PROXY_TOKEN"
DEFAULT_PROXY_HOST = "proxy.host"
CORPORATE_DEBIAN_PATH = "/repo/extras/debian_mirror/debian"
CORPORATE_SECURITY_PATH = "/repo/extras/debian_mirror/debian-security"
DEBIAN_MIRROR_HOSTS = {
    "deb.debian.org",
    "security.debian.org",
    "ftp.debian.org",
    "archive.debian.org",
}


@dataclass(frozen=True)
class Package:
    name: str
    version: str


@dataclass(frozen=True)
class Source:
    name: str
    version: str


@dataclass(frozen=True)
class NetworkConfig:
    proxy_host: str | None = None
    proxy_token: str | None = None

    @property
    def is_corporate(self) -> bool:
        return self.proxy_token is not None

    def mirror_url(self, url: str, *, security: bool = False) -> str:
        if not self.is_corporate:
            return url
        parsed = urlsplit(url)
        if parsed.hostname == self.proxy_host:
            return url
        hostname = parsed.hostname or ""
        if hostname not in DEBIAN_MIRROR_HOSTS and not hostname.endswith(".debian.org"):
            return url
        path = CORPORATE_SECURITY_PATH if security else CORPORATE_DEBIAN_PATH
        return f"https://{self.proxy_host}{path}"


def load_network_config(environ: dict[str, str] | None = None) -> NetworkConfig:
    source = os.environ if environ is None else environ
    token = source.get(PROXY_TOKEN_ENV)
    if not token:
        return NetworkConfig()
    host = source.get(PROXY_HOST_ENV, DEFAULT_PROXY_HOST).strip()
    if not host or any(character in host for character in "\r\n/ "):
        raise ValueError(f"{PROXY_HOST_ENV} must contain a bare hostname")
    if any(character in token for character in "\r\n"):
        raise ValueError(f"{PROXY_TOKEN_ENV} cannot contain a newline")
    return NetworkConfig(proxy_host=host, proxy_token=token)


class CommandError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    print("+ " + " ".join(command), flush=True)
    process = subprocess.run(command, cwd=cwd, env=env, text=True, check=False)
    if process.returncode != 0:
        raise CommandError(f"command exited with status {process.returncode}: {' '.join(command)}")
    return ""


def capture(command: list[str], *, env: dict[str, str]) -> str:
    print("+ " + " ".join(command), flush=True)
    process = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise CommandError(process.stderr.strip() or f"command exited with status {process.returncode}")
    return process.stdout


def read_packages(path: Path) -> list[Package]:
    packages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            name, version = line.split("\t", 1)
            packages.append(Package(name, version))
    return packages


def render_status(packages: list[Package], architecture: str) -> str:
    return "\n".join(
        f"Package: {pkg.name.split(':', 1)[0]}\n"
        "Status: install ok installed\n"
        f"Architecture: {architecture}\n"
        f"Version: {pkg.version}\n"
        for pkg in packages
    )


def setup_apt_sandbox(
    root: Path,
    packages: list[Package],
    architecture: str,
    mirror: str,
    suite: str,
    components: list[str],
    pockets: list[str],
    repositories: list[dict[str, object]],
    network: NetworkConfig | None = None,
) -> tuple[dict[str, str], dict[str, str], Path]:
    network = network or load_network_config()
    etc = root / "etc"
    state = root / "state"
    cache = root / "cache"
    for directory in (etc, state / "lists" / "partial", cache / "archives" / "partial"):
        directory.mkdir(parents=True, exist_ok=True)

    native_arch = capture(["dpkg", "--print-architecture"], env=dict(os.environ)).strip()
    architectures = list(dict.fromkeys([native_arch, architecture]))
    component_text = " ".join(components)
    sources = etc / "sources.list"
    source_lines = []
    if repositories:
        for repository in repositories:
            suites = [str(item) for item in repository["suites"]]
            is_security = any(suite_name.endswith("-security") for suite_name in suites)
            repo_mirror = network.mirror_url(
                str(repository["mirror"]).rstrip("/"), security=is_security
            )
            repo_uses_proxy = urlsplit(repo_mirror).hostname == network.proxy_host
            repo_components = " ".join(str(item) for item in repository["components"])
            signed_by = repository.get("signed_by")
            binary_options = [f"arch={','.join(architectures)}"]
            source_options = []
            if signed_by:
                binary_options.append(f"signed-by={signed_by}")
                source_options.append(f"signed-by={signed_by}")
            if repo_uses_proxy:
                insecure_options = [
                    "trusted=yes",
                    "allow-insecure=yes",
                    "allow-downgrade-to-insecure=yes",
                ]
                binary_options.extend(insecure_options)
                source_options.extend(insecure_options)
            binary_option_text = ",".join(binary_options)
            source_option_text = f" [{','.join(source_options)}]" if source_options else ""
            for suite_name in suites:
                source_lines.extend(
                    [
                        (
                            f"deb [{binary_option_text}] {repo_mirror} "
                            f"{suite_name} {repo_components}"
                        ),
                        (
                            f"deb-src{source_option_text} {repo_mirror} "
                            f"{suite_name} {repo_components}"
                        ),
                    ]
                )
    else:
        for pocket in pockets:
            suite_name = suite + pocket
            if mirror == "auto":
                mirrors_by_arch = {
                    arch: (
                        "http://archive.ubuntu.com/ubuntu"
                        if arch in {"amd64", "i386"}
                        else "http://ports.ubuntu.com/ubuntu-ports"
                    )
                    for arch in architectures
                }
                if network.is_corporate:
                    mirrors_by_arch = {
                        arch: network.mirror_url(arch_mirror)
                        for arch, arch_mirror in mirrors_by_arch.items()
                    }
                proxy_options = ""
                if network.is_corporate:
                    proxy_options = (
                        ",trusted=yes,allow-insecure=yes,allow-downgrade-to-insecure=yes"
                    )
                for arch, arch_mirror in mirrors_by_arch.items():
                    source_lines.append(
                        f"deb [arch={arch}{proxy_options}] "
                        f"{arch_mirror} {suite_name} {component_text}"
                    )
                source_options = ""
                if network.is_corporate:
                    source_options = (
                        " [trusted=yes,allow-insecure=yes,"
                        "allow-downgrade-to-insecure=yes]"
                    )
                source_lines.append(
                    f"deb-src{source_options} {mirrors_by_arch[architecture]} "
                    f"{suite_name} {component_text}"
                )
            else:
                mirror = network.mirror_url(mirror)
                arch_csv = ",".join(architectures)
                source_options = []
                if urlsplit(mirror).hostname == network.proxy_host:
                    source_options = [
                        "trusted=yes",
                        "allow-insecure=yes",
                        "allow-downgrade-to-insecure=yes",
                    ]
                source_option_text = f" [{','.join(source_options)}]" if source_options else ""
                binary_option_text = ",".join([f"arch={arch_csv}", *source_options])
                source_lines.extend(
                    [
                        f"deb [{binary_option_text}] {mirror} {suite_name} {component_text}",
                        f"deb-src{source_option_text} {mirror} {suite_name} {component_text}",
                    ]
                )
    sources.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    baseline = state / "baseline-status"
    baseline.write_text(render_status(packages, architecture), encoding="utf-8")

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
        auth_conf = etc / "auth.conf"
        auth_conf.write_text(
            f"machine {network.proxy_host} login token password {network.proxy_token}\n",
            encoding="utf-8",
        )
        auth_conf.chmod(0o600)
        common.extend(
            [
                f'Dir::Etc::netrc "{auth_conf}";',
                'Acquire::AllowInsecureRepositories "true";',
                'Acquire::AllowDowngradeToInsecureRepositories "true";',
                f'Acquire::https::{network.proxy_host}::Verify-Peer "false";',
                f'Acquire::https::{network.proxy_host}::Verify-Host "false";',
            ]
        )
        print(f"Corporate APT proxy enabled ({network.proxy_host})", flush=True)
    metadata_conf = etc / "metadata.conf"
    metadata_conf.write_text(
        "\n".join(common + [f'Dir::State::status "{baseline}";', ""]), encoding="utf-8"
    )
    build_conf = etc / "build.conf"
    build_conf.write_text(
        "\n".join(common + ['Dir::State::status "/var/lib/dpkg/status";', ""]),
        encoding="utf-8",
    )

    metadata_env = dict(os.environ, APT_CONFIG=str(metadata_conf), DEBIAN_FRONTEND="noninteractive")
    build_env = dict(os.environ, APT_CONFIG=str(build_conf), DEBIAN_FRONTEND="noninteractive")
    return metadata_env, build_env, sources


def resolve_source(package: Package, architecture: str, env: dict[str, str]) -> Source:
    name = package.name if ":" in package.name else f"{package.name}:{architecture}"
    output = capture(["apt-cache", "show", f"{name}={package.version}"], env=env)
    paragraph = output.split("\n\n", 1)[0]
    fields = {}
    for line in paragraph.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value
    if fields.get("Version") != package.version:
        raise CommandError(f"APT returned no exact version for {package.name}={package.version}")
    source_value = fields.get("Source", package.name.split(":", 1)[0])
    match = re.fullmatch(r"([^ ]+)(?: \(([^)]+)\))?", source_value)
    if not match:
        raise CommandError(f"cannot parse Source field {source_value!r}")
    return Source(match.group(1), match.group(2) or package.version)


def find_source_dir(directory: Path) -> Path:
    candidates = [path.parent.parent for path in directory.glob("*/debian/changelog")]
    if len(candidates) != 1:
        raise CommandError(f"expected one unpacked source directory, found {len(candidates)}")
    return candidates[0]


def deb_fields(path: Path) -> tuple[str, str, str]:
    output = subprocess.check_output(
        [
            "dpkg-deb",
            "--show",
            "--showformat=${Package}\t${Version}\t${Architecture}\n",
            str(path),
        ],
        text=True,
    )
    values = output.rstrip("\n").split("\t")
    if len(values) != 3:
        raise CommandError(f"unexpected dpkg-deb metadata for {path.name}")
    return values[0], values[1], values[2]


def build_source_group(
    source: Source,
    requested: list[Package],
    root: Path,
    architecture: str,
    metadata_env: dict[str, str],
    build_env: dict[str, str],
    build_options: str,
) -> dict[str, list[str]]:
    safe_name = re.sub(r"[^a-zA-Z0-9_.+-]", "_", f"{source.name}-{source.version}")
    source_root = root / "sources" / safe_name
    source_root.mkdir(parents=True, exist_ok=True)
    run(["apt-get", "source", f"{source.name}={source.version}"], cwd=source_root, env=metadata_env)
    unpacked = find_source_dir(source_root)

    native_arch = capture(["dpkg", "--print-architecture"], env=build_env).strip()
    if architecture != native_arch:
        run(["dpkg", "--add-architecture", architecture], env=build_env)
        run(
            ["apt-get", "install", "-y", "--no-install-recommends", f"crossbuild-essential-{architecture}"],
            env=build_env,
        )
    run(
        [
            "apt-get",
            "build-dep",
            "-y",
            "--no-install-recommends",
            f"--host-architecture={architecture}",
            f"{source.name}={source.version}",
        ],
        cwd=unpacked,
        env=build_env,
    )
    package_env = dict(build_env, DEB_BUILD_OPTIONS=build_options)
    command = ["dpkg-buildpackage", "--no-sign", "--build=binary"]
    if architecture != native_arch:
        command.append(f"--host-arch={architecture}")
    run(command, cwd=unpacked, env=package_env)

    wanted = {(pkg.name.split(":", 1)[0], pkg.version): pkg for pkg in requested}
    found: dict[str, list[str]] = defaultdict(list)
    output_dir = root / "output"
    output_dir.mkdir(exist_ok=True)
    for artifact in source_root.glob("*.deb"):
        binary_name, version, artifact_arch = deb_fields(artifact)
        package = wanted.get((binary_name, version))
        if package and artifact_arch in (architecture, "all"):
            destination = output_dir / artifact.name
            shutil.copy2(artifact, destination)
            found[package.name].append(destination.name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--mirror", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--components", required=True)
    parser.add_argument("--pockets", required=True)
    parser.add_argument("--repositories-json", default="[]")
    parser.add_argument("--build-options", default="nocheck")
    args = parser.parse_args()

    packages = read_packages(args.input)
    architecture = args.architecture
    if architecture == "native":
        architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()

    result = {"architecture": architecture, "packages": []}
    metadata_env, build_env, _sources_file = setup_apt_sandbox(
        args.work_dir / "apt-sandbox",
        packages,
        architecture,
        args.mirror,
        args.suite,
        args.components.split(","),
        args.pockets.split(","),
        json.loads(args.repositories_json),
    )
    try:
        run(["apt-get", "update"], env=metadata_env)
        groups: dict[Source, list[Package]] = defaultdict(list)
        unresolved: list[tuple[Package, str]] = []
        for package in packages:
            try:
                groups[resolve_source(package, architecture, metadata_env)].append(package)
            except Exception as exc:  # noqa: BLE001 - report this package and continue the batch
                unresolved.append((package, str(exc)))

        entries: dict[Package, dict[str, object]] = {
            package: {
                "name": package.name,
                "version": package.version,
                "success": False,
                "source": None,
                "artifacts": [],
            }
            for package in packages
        }
        for package, error in unresolved:
            entries[package]["error"] = error

        for source, requested in groups.items():
            try:
                artifacts = build_source_group(
                    source,
                    requested,
                    args.work_dir,
                    architecture,
                    metadata_env,
                    build_env,
                    args.build_options,
                )
                for package in requested:
                    entries[package]["source"] = f"{source.name}={source.version}"
                    entries[package]["artifacts"] = artifacts.get(package.name, [])
                    entries[package]["success"] = bool(artifacts.get(package.name))
                    if not entries[package]["success"]:
                        entries[package]["error"] = "requested binary package was not produced"
            except Exception as exc:  # noqa: BLE001 - report this source group and continue
                for package in requested:
                    entries[package]["source"] = f"{source.name}={source.version}"
                    entries[package]["error"] = str(exc)

        result["packages"] = [entries[package] for package in packages]
    except Exception as exc:  # noqa: BLE001 - always emit a machine-readable result
        result["fatal_error"] = str(exc)
        for package in packages:
            result["packages"].append(
                {
                    "name": package.name,
                    "version": package.version,
                    "success": False,
                    "source": None,
                    "artifacts": [],
                    "error": str(exc),
                }
            )
    finally:
        # The token is needed only while APT runs. Do not retain it when
        # --keep-artifacts preserves the rest of the build workspace.
        (args.work_dir / "apt-sandbox" / "etc" / "auth.conf").unlink(missing_ok=True)
        (args.work_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    return 0 if all(entry["success"] for entry in result["packages"]) else 1


if __name__ == "__main__":
    sys.exit(main())

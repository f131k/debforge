from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .exceptions import ConfigError

_DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/debforge/config.yaml")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS: dict = {
    "docker_image": "debforge-builder:latest",
    "docker_dockerfile": str(_PROJECT_ROOT / "docker" / "Dockerfile.builder"),
    "work_dir": str(_PROJECT_ROOT / ".debforge-work"),
    "output_dir": str(_PROJECT_ROOT / "artifacts"),
    "target_architecture": "native",
    "source_mirror": "http://deb.debian.org/debian",
    "source_suite": "bookworm",
    "source_components": ["main", "contrib", "non-free", "non-free-firmware"],
    "source_pockets": ["", "-updates"],
    "source_repositories": [
        {
            "mirror": "http://deb.debian.org/debian",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm", "bookworm-updates"],
            "components": ["main", "contrib", "non-free", "non-free-firmware"],
        },
        {
            "mirror": "http://security.debian.org/debian-security",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm-security"],
            "components": ["main", "contrib", "non-free", "non-free-firmware"],
        },
    ],
    "build_options": "nocheck",
    "signing_mode": "debsigs",
    "gpg_key_id": "",
    "gpg_private_key_secret": "/run/secrets/debforge-gpg-private-key",
    "gpg_passphrase_secret": "/run/secrets/debforge-gpg-passphrase",
    "binary_signing_key": None,
    "repo_backend": "aptly",
    "aptly": {
        "repo_name": "local-builds",
        "publish_endpoint": "filesystem:debforge:",
        "snapshot_prefix": "debforge",
    },
    "reprepro": {
        "repo_path": "",
        "codename": "bookworm",
        "allow_duplicates": False,
    },
    "log_level": "INFO",
    "log_file": None,
    "keep_build_artifacts": False,
    "skip_unimplemented_stubs": True,
    "debian_mirror": None,
    "debian_suite": "bookworm",
}


@dataclass
class DebforgeConfig:
    docker_image: str
    docker_dockerfile: str
    work_dir: str
    gpg_key_id: str
    gpg_private_key_secret: str
    gpg_passphrase_secret: str
    binary_signing_key: str | None
    repo_backend: str
    aptly_repo_name: str
    aptly_publish_endpoint: str
    aptly_snapshot_prefix: str
    reprepro_repo_path: str
    reprepro_codename: str
    reprepro_allow_duplicates: bool
    log_level: str
    log_file: str | None
    keep_build_artifacts: bool
    skip_unimplemented_stubs: bool
    debian_mirror: str | None
    debian_suite: str
    output_dir: str = "artifacts"
    target_architecture: str = "native"
    source_mirror: str = "http://deb.debian.org/debian"
    source_suite: str = "bookworm"
    source_components: tuple[str, ...] = ("main", "contrib", "non-free", "non-free-firmware")
    source_pockets: tuple[str, ...] = ("", "-updates")
    source_repositories: tuple[dict[str, object], ...] = ()
    build_options: str = "nocheck"
    signing_mode: str = "debsigs"


def load_config(config_path: str | None, overrides: dict) -> DebforgeConfig:
    path = config_path or _DEFAULT_CONFIG_PATH
    base = dict(_DEFAULTS)

    if os.path.exists(path):
        with open(path) as f:
            file_cfg = yaml.safe_load(f) or {}
        base = _deep_merge(base, file_cfg)

    base = _apply_overrides(base, overrides)
    _validate(base)
    return _build_dataclass(base)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _apply_overrides(base: dict, overrides: dict) -> dict:
    mapping = {
        "gpg_key_id": "gpg_key_id",
        "binary_signing_key": "binary_signing_key",
        "docker_image": "docker_image",
        "repo_backend": "repo_backend",
        "work_dir": "work_dir",
        "output_dir": "output_dir",
        "target_architecture": "target_architecture",
        "source_mirror": "source_mirror",
        "source_suite": "source_suite",
        "log_level": "log_level",
        "log_file": "log_file",
        "keep_build_artifacts": "keep_build_artifacts",
    }
    for cli_key, cfg_key in mapping.items():
        if overrides.get(cli_key) is not None:
            base[cfg_key] = overrides[cli_key]
    return base


def _validate(cfg: dict) -> None:
    if cfg["repo_backend"] not in ("aptly", "reprepro"):
        raise ConfigError(f"repo_backend must be 'aptly' or 'reprepro', got: {cfg['repo_backend']!r}")
    if not cfg.get("target_architecture"):
        raise ConfigError("target_architecture cannot be empty")
    if not cfg.get("source_mirror") or not cfg.get("source_suite"):
        raise ConfigError("source_mirror and source_suite are required")
    if cfg.get("signing_mode") != "debsigs":
        raise ConfigError("only mandatory signing_mode='debsigs' is supported")
    for field in ("gpg_private_key_secret", "gpg_passphrase_secret"):
        value = Path(cfg.get(field, ""))
        if not value.is_absolute() or value.parent != Path("/run/secrets"):
            raise ConfigError(f"{field} must point to a file directly under /run/secrets")
    if cfg["repo_backend"] == "reprepro":
        rr = cfg.get("reprepro", {})
        if not rr.get("repo_path"):
            raise ConfigError("reprepro.repo_path is required when repo_backend=reprepro")
        if not rr.get("codename"):
            raise ConfigError("reprepro.codename is required when repo_backend=reprepro")
    if cfg["repo_backend"] == "aptly":
        ap = cfg.get("aptly", {})
        if not ap.get("repo_name"):
            raise ConfigError("aptly.repo_name is required when repo_backend=aptly")


def _build_dataclass(cfg: dict) -> DebforgeConfig:
    ap = cfg.get("aptly", {})
    rr = cfg.get("reprepro", {})
    return DebforgeConfig(
        docker_image=cfg["docker_image"],
        docker_dockerfile=_absolute_path(cfg["docker_dockerfile"]),
        work_dir=_absolute_path(cfg["work_dir"]),
        gpg_key_id=cfg["gpg_key_id"],
        gpg_private_key_secret=cfg["gpg_private_key_secret"],
        gpg_passphrase_secret=cfg["gpg_passphrase_secret"],
        binary_signing_key=cfg.get("binary_signing_key"),
        repo_backend=cfg["repo_backend"],
        aptly_repo_name=ap.get("repo_name", "local-builds"),
        aptly_publish_endpoint=ap.get("publish_endpoint", "filesystem:debforge:"),
        aptly_snapshot_prefix=ap.get("snapshot_prefix", "debforge"),
        reprepro_repo_path=rr.get("repo_path", ""),
        reprepro_codename=rr.get("codename", "bookworm"),
        reprepro_allow_duplicates=rr.get("allow_duplicates", False),
        log_level=cfg.get("log_level", "INFO"),
        log_file=cfg.get("log_file"),
        keep_build_artifacts=cfg.get("keep_build_artifacts", False),
        skip_unimplemented_stubs=cfg.get("skip_unimplemented_stubs", True),
        debian_mirror=cfg.get("debian_mirror"),
        debian_suite=cfg.get("debian_suite", "bookworm"),
        output_dir=_absolute_path(cfg.get("output_dir", "artifacts")),
        target_architecture=cfg.get("target_architecture", "native"),
        source_mirror=cfg.get("source_mirror", "http://deb.debian.org/debian").rstrip("/"),
        source_suite=cfg.get("source_suite", "bookworm"),
        source_components=tuple(cfg.get("source_components", ["main"])),
        source_pockets=tuple(cfg.get("source_pockets", [""])),
        source_repositories=tuple(cfg.get("source_repositories", [])),
        build_options=cfg.get("build_options", "nocheck"),
        signing_mode=cfg.get("signing_mode", "debsigs"),
    )


def _absolute_path(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value))

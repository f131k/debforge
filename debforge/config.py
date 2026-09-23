from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from .exceptions import ConfigError

_DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/debforge/config.yaml")

_DEFAULTS: dict[str, object] = {
    "work_dir": "/work",
    "output_dir": "/output",
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
    "log_level": "INFO",
    "log_file": None,
    "keep_build_artifacts": False,
}


@dataclass
class DebforgeConfig:
    work_dir: str
    output_dir: str
    target_architecture: str
    source_mirror: str
    source_suite: str
    source_components: tuple[str, ...]
    source_pockets: tuple[str, ...]
    source_repositories: tuple[dict[str, object], ...]
    build_options: str
    signing_mode: str
    gpg_key_id: str
    gpg_private_key_secret: str
    gpg_passphrase_secret: str
    log_level: str
    log_file: str | None
    keep_build_artifacts: bool


def load_config(config_path: str | None, overrides: dict[str, object]) -> DebforgeConfig:
    base = dict(_DEFAULTS)
    path = config_path or _DEFAULT_CONFIG_PATH
    if os.path.exists(path):
        with open(path, encoding="utf-8") as stream:
            file_config = yaml.safe_load(stream) or {}
        if not isinstance(file_config, dict):
            raise ConfigError(f"configuration root must be a mapping: {path}")
        base = _deep_merge(base, file_config)
    for key, value in overrides.items():
        if value is not None and key in _DEFAULTS:
            base[key] = value
    _validate(base)
    return _build_dataclass(base)


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _validate(config: dict[str, object]) -> None:
    if not config.get("target_architecture"):
        raise ConfigError("target_architecture cannot be empty")
    if not config.get("source_mirror") or not config.get("source_suite"):
        raise ConfigError("source_mirror and source_suite are required")
    if config.get("signing_mode") != "debsigs":
        raise ConfigError("only mandatory signing_mode='debsigs' is supported")
    for field in ("gpg_private_key_secret", "gpg_passphrase_secret"):
        value = Path(str(config.get(field, "")))
        if not value.is_absolute() or value.parent != Path("/run/secrets"):
            raise ConfigError(f"{field} must point to a file directly under /run/secrets")


def _build_dataclass(config: dict[str, object]) -> DebforgeConfig:
    source_components = cast(list[object], config["source_components"])
    source_pockets = cast(list[object], config["source_pockets"])
    source_repositories = cast(list[dict[str, object]], config.get("source_repositories", []))
    return DebforgeConfig(
        work_dir=_absolute_path(str(config["work_dir"])),
        output_dir=_absolute_path(str(config["output_dir"])),
        target_architecture=str(config["target_architecture"]),
        source_mirror=str(config["source_mirror"]).rstrip("/"),
        source_suite=str(config["source_suite"]),
        source_components=tuple(str(item) for item in source_components),
        source_pockets=tuple(str(item) for item in source_pockets),
        source_repositories=tuple(source_repositories),
        build_options=str(config.get("build_options", "nocheck")),
        signing_mode=str(config.get("signing_mode", "debsigs")),
        gpg_key_id=str(config.get("gpg_key_id", "")),
        gpg_private_key_secret=str(config["gpg_private_key_secret"]),
        gpg_passphrase_secret=str(config["gpg_passphrase_secret"]),
        log_level=str(config.get("log_level", "INFO")),
        log_file=str(config["log_file"]) if config.get("log_file") else None,
        keep_build_artifacts=bool(config.get("keep_build_artifacts", False)),
    )


def _absolute_path(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value))

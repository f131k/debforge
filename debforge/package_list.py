from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .exceptions import ConfigError

_PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?$")


@dataclass(frozen=True)
class PackageSpec:
    name: str
    version: str

    @property
    def display(self) -> str:
        return f"{self.name}={self.version}"


def parse_package_file(path: str) -> list[PackageSpec]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read package list {path!r}: {exc}") from exc
    return parse_package_text(text, source=path)


def parse_package_text(text: str, source: str = "<input>") -> list[PackageSpec]:
    packages: list[PackageSpec] = []
    versions_by_name: dict[str, str] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue

        parts = raw_line.split("\t")
        if len(parts) != 2:
            raise ConfigError(
                f"{source}:{line_number}: expected Package<TAB>Version, got {raw_line!r}"
            )
        name, version = (part.strip() for part in parts)
        if not _PACKAGE_RE.fullmatch(name):
            raise ConfigError(f"{source}:{line_number}: invalid package name {name!r}")
        if not version or any(char.isspace() or ord(char) < 32 for char in version):
            raise ConfigError(f"{source}:{line_number}: invalid package version {version!r}")

        previous = versions_by_name.get(name)
        if previous is not None:
            if previous != version:
                raise ConfigError(
                    f"{source}:{line_number}: package {name!r} has conflicting versions "
                    f"{previous!r} and {version!r}"
                )
            continue

        versions_by_name[name] = version
        packages.append(PackageSpec(name=name, version=version))

    if not packages:
        raise ConfigError(f"Package list {source!r} is empty")
    return packages


def parse_inline_specs(value: str) -> list[PackageSpec]:
    lines: list[str] = []
    for item in value.split():
        if "=" not in item:
            raise ConfigError(
                f"Inline package {item!r} has no version; use NAME=VERSION or --packages-file"
            )
        name, version = item.split("=", 1)
        lines.append(f"{name}\t{version}")
    return parse_package_text("\n".join(lines), source="--packages")

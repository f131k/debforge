from __future__ import annotations

import argparse
import dataclasses
import sys

from .config import load_config
from .exceptions import ConfigError, DebforgeError
from .logging_setup import configure_logging
from .package_list import PackageSpec, parse_inline_specs, parse_package_file
from .pipeline import rebuild_packages


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    log_level = args.log_level or "INFO"
    log_file = getattr(args, "log_file", None)
    configure_logging(log_level, log_file)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(2)

    try:
        args.func(args)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(2)
    except DebforgeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debforge",
        description="Build and sign Debian packages from source inside the current container.",
    )
    parser.add_argument("--config", "-c", metavar="FILE", help="Path to YAML config file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--log-file", metavar="FILE", help="Write logs to file in addition to stderr")

    subparsers = parser.add_subparsers(title="subcommands")

    # build subcommand
    build_p = subparsers.add_parser("build", help="Run the full build pipeline")
    _add_package_args(build_p)
    _add_common_overrides(build_p)
    build_p.add_argument(
        "--keep-artifacts",
        action="store_true",
        default=None,
        help="Keep temporary sources and APT sandbox after completion",
    )
    build_p.add_argument("--output-dir", metavar="DIR", help="Directory for rebuilt .deb files")
    build_p.add_argument(
        "--architecture", metavar="ARCH", help="Target architecture (native, arm64, amd64, ...)"
    )
    build_p.add_argument("--mirror", metavar="URL", help="APT source mirror used by the sandbox")
    build_p.add_argument("--suite", metavar="NAME", help="APT source suite used by the sandbox")
    build_p.add_argument("--dry-run", action="store_true", help="Log actions without executing")
    build_p.set_defaults(func=_cmd_build)

    # config subcommand
    config_p = subparsers.add_parser("config", help="Print resolved effective configuration and exit")
    _add_common_overrides(config_p)
    config_p.set_defaults(func=_cmd_config)

    return parser


def _add_package_args(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--packages", "-p", metavar="NAMES",
        help="Space-separated NAME=VERSION specifications",
    )
    group.add_argument(
        "--packages-file", "-f", metavar="FILE",
        help="dpkg-query file with Package<TAB>Version on each line",
    )


def _add_common_overrides(p: argparse.ArgumentParser) -> None:
    p.add_argument("--gpg-key", metavar="FINGERPRINT", help="GPG key fingerprint for signing")
    p.add_argument("--work-dir", metavar="DIR", help="Working directory for build artifacts")


def _parse_package_list(args: argparse.Namespace) -> list[PackageSpec]:
    if args.packages:
        return parse_inline_specs(args.packages)
    return parse_package_file(args.packages_file)


def _build_overrides(args: argparse.Namespace) -> dict[str, object]:
    return {
        "gpg_key_id": getattr(args, "gpg_key", None),
        "work_dir": getattr(args, "work_dir", None),
        "output_dir": getattr(args, "output_dir", None),
        "target_architecture": getattr(args, "architecture", None),
        "source_mirror": getattr(args, "mirror", None),
        "source_suite": getattr(args, "suite", None),
        "log_level": getattr(args, "log_level", None),
        "log_file": getattr(args, "log_file", None),
        "keep_build_artifacts": getattr(args, "keep_artifacts", None),
    }


def _cmd_build(args: argparse.Namespace) -> None:
    packages = _parse_package_list(args)
    config = load_config(args.config, _build_overrides(args))

    if args.dry_run:
        import logging
        logging.getLogger("debforge").info(
            "DRY RUN — would build packages: %s", ", ".join(p.display for p in packages)
        )
        return

    rebuild_packages(packages, config)


def _cmd_config(args: argparse.Namespace) -> None:
    config = load_config(args.config, _build_overrides(args))
    import json
    print(json.dumps(dataclasses.asdict(config), indent=2))

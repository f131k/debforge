from __future__ import annotations

import argparse
import dataclasses
import sys

from .config import load_config
from .exceptions import ConfigError, DebforgeError
from .logging_setup import configure_logging
from .package_list import PackageSpec, parse_inline_specs, parse_package_file
from .rebuilder import rebuild_packages


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
        description="Build Debian packages from source with signing and publishing.",
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
    build_p.add_argument(
        "--rebuild-image", action="store_true", help="Rebuild the Debian 12.0 builder image"
    )
    build_p.add_argument("--dry-run", action="store_true", help="Log actions without executing")
    build_p.set_defaults(func=_cmd_build)

    # publish subcommand
    publish_p = subparsers.add_parser("publish", help="Publish pre-built .deb files (skips build steps)")
    publish_p.add_argument(
        "--deb-files", "-d", required=True, metavar="PATHS",
        help="Space-separated paths to .deb files to publish",
    )
    _add_common_overrides(publish_p)
    publish_p.set_defaults(func=_cmd_publish)

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
    p.add_argument("--binary-signing-key", metavar="KEY", help="Binary signing key path/identifier")
    p.add_argument("--docker-image", metavar="IMAGE", help="Docker image for build container")
    p.add_argument("--repo-backend", choices=["aptly", "reprepro"], help="Apt repository backend")
    p.add_argument("--work-dir", metavar="DIR", help="Working directory for build artifacts")


def _parse_package_list(args: argparse.Namespace) -> list[PackageSpec]:
    if args.packages:
        return parse_inline_specs(args.packages)
    return parse_package_file(args.packages_file)


def _build_overrides(args: argparse.Namespace) -> dict[str, object]:
    return {
        "gpg_key_id": getattr(args, "gpg_key", None),
        "binary_signing_key": getattr(args, "binary_signing_key", None),
        "docker_image": getattr(args, "docker_image", None),
        "repo_backend": getattr(args, "repo_backend", None),
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

    rebuild_packages(packages, config, rebuild_image=args.rebuild_image)


def _cmd_publish(args: argparse.Namespace) -> None:
    from .pipeline import PackageContext
    from .steps import publish as publish_step

    deb_files = args.deb_files.split()
    config = load_config(args.config, _build_overrides(args))

    import os
    for deb_path in deb_files:
        if not os.path.exists(deb_path):
            raise DebforgeError(f"File not found: {deb_path!r}")

    pkg_name = "manual"
    ctx = PackageContext(
        name=pkg_name,
        work_dir=config.work_dir,
        config=config,
        deb_paths=deb_files,
    )

    try:
        publish_step.add_to_repo(ctx)
    except DebforgeError:
        sys.exit(1)


def _cmd_config(args: argparse.Namespace) -> None:
    config = load_config(args.config, _build_overrides(args))
    import json
    print(json.dumps(dataclasses.asdict(config), indent=2))

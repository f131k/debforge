from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

from .config import DebforgeConfig
from .exceptions import DebforgeError
from .steps import build, download, publish, security_scan, sign_binaries, sign_package

logger = logging.getLogger(__name__)


@dataclass
class PackageContext:
    name: str
    work_dir: str
    config: DebforgeConfig
    dsc_path: str | None = None
    deb_paths: list[str] = field(default_factory=list)


def run_packages(packages: list[str], config: DebforgeConfig) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for package in packages:
        logger.info("=== Processing package: %s ===", package)
        try:
            run_single_package(package, config)
            results[package] = True
        except DebforgeError as e:
            logger.error("[%s] Pipeline failed: %s", package, e)
            results[package] = False
        except Exception:
            logger.exception("[%s] Unexpected error", package)
            results[package] = False

    _print_summary(results)
    return results


def run_single_package(package: str, config: DebforgeConfig) -> None:
    pkg_work_dir = os.path.join(config.work_dir, package)
    os.makedirs(pkg_work_dir, exist_ok=True)

    ctx = PackageContext(name=package, work_dir=pkg_work_dir, config=config)

    try:
        download.fetch_source(ctx)
        security_scan.scan(ctx)
        build.build_in_docker(ctx)
        _run_step_stub(ctx, sign_binaries.sign, "binary signing")
        sign_package.sign_deb(ctx)
        publish.add_to_repo(ctx)
    finally:
        if not config.keep_build_artifacts:
            _cleanup(pkg_work_dir)


def _run_step_stub(ctx: PackageContext, step_fn, step_name: str) -> None:
    try:
        step_fn(ctx)
    except NotImplementedError as e:
        if ctx.config.skip_unimplemented_stubs:
            logger.warning("[%s] Skipping unimplemented step '%s': %s", ctx.name, step_name, e)
        else:
            raise DebforgeError(
                f"[{ctx.name}] Step '{step_name}' is not implemented. "
                "Set skip_unimplemented_stubs: true in config to skip."
            ) from e


def _cleanup(work_dir: str) -> None:
    if os.path.exists(work_dir):
        logger.debug("Cleaning up build artifacts: %s", work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)


def _print_summary(results: dict[str, bool]) -> None:
    succeeded = [p for p, ok in results.items() if ok]
    failed = [p for p, ok in results.items() if not ok]

    logger.info("=== Build Summary ===")
    logger.info("Total: %d  Success: %d  Failed: %d", len(results), len(succeeded), len(failed))

    for pkg in succeeded:
        logger.info("  OK  %s", pkg)
    for pkg in failed:
        logger.error("  FAIL  %s", pkg)

from __future__ import annotations

import glob
import logging
import os
import subprocess

from ..exceptions import DownloadError

logger = logging.getLogger(__name__)


def fetch_source(ctx) -> None:
    os.makedirs(ctx.work_dir, exist_ok=True)
    logger.info("[%s] Downloading source package", ctx.name)

    try:
        _run_apt_get_source(ctx.name, ctx.work_dir, ctx.config)
    except DownloadError as e:
        logger.warning("[%s] apt-get source failed (%s), no fallback available", ctx.name, e)
        raise

    ctx.dsc_path = _find_dsc_file(ctx.work_dir)
    logger.info("[%s] Source package downloaded: %s", ctx.name, ctx.dsc_path)

    # Print package name and version to stdout
    try:
        # Try to get package version using dpkg-query
        cmd = ["dpkg-query", "-W", "-f=${Version}", ctx.name]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        print(f"{ctx.name} {version}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback if we can't get version info
        print(f"{ctx.name} unknown-version")


def _find_dsc_file(directory: str) -> str:
    matches = glob.glob(os.path.join(directory, "**", "*.dsc"), recursive=True)
    if not matches:
        # Also check parent directory — apt-get source places files in cwd
        matches = glob.glob(os.path.join(directory, "*.dsc"))
    if len(matches) == 0:
        raise DownloadError(f"No .dsc file found in {directory!r}")
    if len(matches) > 1:
        logger.debug("Multiple .dsc files found, using first: %s", matches[0])
    return matches[0]


def _run_apt_get_source(package: str, dest_dir: str, config) -> None:
    cmd = ["apt-get", "source", "--download-only", package]

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    if config.debian_mirror:
        # Write a temporary sources.list entry for the specified mirror
        logger.debug("[%s] Using mirror: %s %s", package, config.debian_mirror, config.debian_suite)
        # apt-get source respects -o Dir::Etc::sourcelist but simpler to just trust system config
        # and let the user configure their sources.list. Log a hint.
        logger.debug(
            "Hint: ensure %s %s is in /etc/apt/sources.list (deb-src line required)",
            config.debian_mirror,
            config.debian_suite,
        )

    logger.debug("[%s] Running: %s (cwd=%s)", package, " ".join(cmd), dest_dir)
    proc = subprocess.run(
        cmd,
        cwd=dest_dir,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )

    if proc.returncode != 0:
        raise DownloadError(
            f"apt-get source failed for {package!r} (exit {proc.returncode}):\n{proc.stderr}"
        )

    logger.debug("[%s] apt-get source stdout: %s", package, proc.stdout)


def _run_dget(dsc_url: str, dest_dir: str) -> subprocess.CompletedProcess:
    cmd = ["dget", "-x", "--allow-unauthenticated", dsc_url]
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), dest_dir)
    proc = subprocess.run(
        cmd,
        cwd=dest_dir,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise DownloadError(
            f"dget failed for {dsc_url!r} (exit {proc.returncode}):\n{proc.stderr}"
        )
    return proc

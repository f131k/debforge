from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime

from ..exceptions import PublishError

logger = logging.getLogger(__name__)


def add_to_repo(ctx) -> None:
    backend = ctx.config.repo_backend
    logger.info("[%s] Publishing to %s repository", ctx.name, backend)

    if backend == "aptly":
        _add_via_aptly(ctx)
    elif backend == "reprepro":
        _add_via_reprepro(ctx)
    else:
        raise PublishError(f"Unknown repo backend: {backend!r}")

    logger.info("[%s] Published successfully", ctx.name)


def _add_via_aptly(ctx) -> None:
    repo_name = ctx.config.aptly_repo_name
    endpoint = ctx.config.aptly_publish_endpoint
    prefix = ctx.config.aptly_snapshot_prefix
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    snapshot_name = f"{prefix}-{ctx.name}-{timestamp}"

    for deb_path in ctx.deb_paths:
        logger.debug("[%s] Adding %s to aptly repo %s", ctx.name, deb_path, repo_name)
        _run_cmd(["aptly", "repo", "add", repo_name, deb_path])

    _run_cmd(["aptly", "snapshot", "create", snapshot_name, "from", "repo", repo_name])
    logger.info("[%s] Created aptly snapshot: %s", ctx.name, snapshot_name)

    if _aptly_endpoint_published(endpoint):
        # Endpoint already published — switch to new snapshot
        codename = ctx.config.reprepro_codename  # reuse debian_suite equivalent
        _run_cmd(["aptly", "publish", "switch", codename, endpoint, snapshot_name])
    else:
        _run_cmd(["aptly", "publish", "snapshot", snapshot_name, endpoint])

    logger.info("[%s] aptly endpoint %s updated", ctx.name, endpoint)


def _aptly_endpoint_published(endpoint: str) -> bool:
    proc = subprocess.run(
        ["aptly", "publish", "list", "-raw"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return False
    return endpoint in proc.stdout


def _add_via_reprepro(ctx) -> None:
    repo_path = ctx.config.reprepro_repo_path
    codename = ctx.config.reprepro_codename

    for deb_path in ctx.deb_paths:
        logger.debug("[%s] Adding %s via reprepro (codename=%s)", ctx.name, deb_path, codename)
        proc = subprocess.run(
            ["reprepro", "-b", repo_path, "includedeb", codename, deb_path],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr
            if "already registered" in stderr and ctx.config.reprepro_allow_duplicates:
                logger.warning(
                    "[%s] Package already in reprepro repo (allow_duplicates=true, skipping): %s",
                    ctx.name,
                    deb_path,
                )
                continue
            raise PublishError(
                f"reprepro failed for {deb_path!r} (exit {proc.returncode}):\n{stderr}"
            )
        logger.debug("reprepro stdout: %s", proc.stdout)


def _run_cmd(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    logger.debug("Running: %s", " ".join(args))
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise PublishError(
            f"Command failed (exit {proc.returncode}): {' '.join(args)}\n"
            f"stderr: {proc.stderr}"
        )
    logger.debug("stdout: %s", proc.stdout)
    return proc

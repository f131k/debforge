from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def scan(ctx) -> None:
    """
    STUB — security scanning placeholder.

    TODO: Integrate static analysis tools (lintian, trivy, custom scanners).
    TODO: Accept a list of scanner plugin paths from config.
    TODO: CRITICAL findings → abort pipeline; HIGH → warn and continue.
    """
    # Stub output to stdout with package name and version
    try:
        # Try to get package version using dpkg-query
        cmd = ["dpkg-query", "-W", "-f=${Version}", ctx.name]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        print(f"{ctx.name} {version}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback if we can't get version info
        print(f"{ctx.name} unknown-version")

    logger.warning(
        "[%s] Security scanning is not implemented — skipping. "
        "Do not use in production without a real scanner.",
        ctx.name,
    )

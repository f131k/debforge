from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def sign(ctx) -> None:
    """
    STUB — ELF binary signing placeholder.

    TODO: For each .deb in ctx.deb_paths:
          - Extract the archive
          - Find and sign ELF binaries using ctx.config.binary_signing_key
          - Repack the archive
    TODO: Integrate with hardware HSM or a code-signing service.
    TODO: Add config option to specify which binaries to sign (glob patterns).
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

    raise NotImplementedError(
        f"[{ctx.name}] Binary signing is not yet implemented. "
        "Set skip_unimplemented_stubs: true in config to skip this step."
    )

from __future__ import annotations

import glob
import logging
import os
import subprocess

from ..exceptions import SigningError

logger = logging.getLogger(__name__)


def sign_deb(ctx) -> None:
    logger.info("[%s] Signing package with GPG key %s", ctx.name, ctx.config.gpg_key_id)

    changes_file = _find_changes_file(ctx.work_dir)
    _run_debsign(changes_file, ctx.config.gpg_key_id)
    _verify_signature(changes_file, ctx.config.gpg_key_id)

    logger.info("[%s] Package signed successfully: %s", ctx.name, changes_file)


def _find_changes_file(directory: str) -> str:
    matches = glob.glob(os.path.join(directory, "*.changes"))
    if len(matches) == 0:
        raise SigningError(f"No .changes file found in {directory!r}")
    if len(matches) > 1:
        logger.debug("Multiple .changes files found, using first: %s", matches[0])
    return matches[0]


def _run_debsign(changes_file: str, key_id: str) -> None:
    env = os.environ.copy()
    # Ensure GPG has a TTY reference even in non-interactive runs
    env.setdefault("GPG_TTY", "/dev/tty")

    cmd = ["debsign", "--re-sign", "-k", key_id, changes_file]
    logger.debug("Running: %s", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )

    if proc.returncode != 0:
        raise SigningError(
            f"debsign failed for {changes_file!r} (exit {proc.returncode}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )

    logger.debug("debsign stdout: %s", proc.stdout)


def _verify_signature(changes_file: str, key_id: str) -> None:
    proc = subprocess.run(
        ["gpg", "--verify", changes_file],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise SigningError(
            f"GPG signature verification failed for {changes_file!r}:\n{proc.stderr}"
        )
    logger.debug("Signature verified for %s", changes_file)

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO

from ..exceptions import SigningError

logger = logging.getLogger(__name__)


def validate_signing_secrets(private_key_secret: str, passphrase_secret: str) -> None:
    private_key = _require_secret(private_key_secret, "OpenPGP private key")
    passphrase = _require_secret(passphrase_secret, "OpenPGP passphrase")
    if private_key == passphrase:
        raise SigningError("Private key and passphrase must be separate secret files")


def sign_packages(
    artifacts: list[Path],
    key_selector: str,
    private_key_secret: str,
    passphrase_secret: str,
) -> dict[str, object]:
    """Embed and verify debsigs origin signatures in the current container."""
    private_key = _require_secret(private_key_secret, "OpenPGP private key")
    passphrase = _require_secret(passphrase_secret, "OpenPGP passphrase")
    if private_key == passphrase:
        raise SigningError("Private key and passphrase must be separate secret files")
    if not artifacts:
        raise SigningError("no package artifacts were provided")
    for artifact in artifacts:
        if not artifact.is_file() or artifact.suffix != ".deb":
            raise SigningError(f"invalid package artifact: {artifact}")

    temporary_root = Path(tempfile.mkdtemp(prefix="debforge-signing-"))
    gnupg_home = temporary_root / "gnupg"
    wrapper_dir = temporary_root / "bin"
    gnupg_home.mkdir(mode=0o700)
    wrapper_dir.mkdir(mode=0o700)
    _write_gpg_wrapper(wrapper_dir, passphrase)
    env = dict(
        os.environ,
        GNUPGHOME=str(gnupg_home),
        PATH=f"{wrapper_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
    )

    try:
        _run(
            [
                "/usr/bin/gpg",
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                str(passphrase),
                "--import",
                str(private_key),
            ],
            env=env,
        )
        list_command = ["/usr/bin/gpg", "--batch", "--with-colons", "--list-secret-keys"]
        if key_selector:
            list_command.append(key_selector)
        listing = _run(list_command, env=env).stdout
        assert isinstance(listing, str)
        primary_fingerprint, signing_fingerprint, signing_key_id = _select_signing_key(listing)
        policies_root, keyrings_root = _write_verification_policy(
            temporary_root,
            primary_fingerprint,
            signing_key_id,
            env,
        )

        signed: list[dict[str, object]] = []
        for artifact in artifacts:
            _run(
                [
                    "debsigs",
                    "--sign=origin",
                    f"--default-key={signing_fingerprint}!",
                    str(artifact),
                ],
                env=env,
            )
            _run(
                [
                    "debsig-verify",
                    "--debug",
                    "--policies-dir",
                    str(policies_root),
                    "--keyrings-dir",
                    str(keyrings_root),
                    str(artifact),
                ],
                env=env,
            )
            signed.append(
                {"artifact": artifact.name, "sha256": _sha256(artifact), "verified": True}
            )

        logger.info("Signed and verified %d package(s) with debsigs", len(artifacts))
        return {
            "mode": "debsigs",
            "signed": True,
            "signature_type": "origin",
            "key_fingerprint": signing_fingerprint,
            "key_id": signing_key_id,
            "artifacts": signed,
        }
    finally:
        subprocess.run(
            ["gpgconf", "--kill", "gpg-agent"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        shutil.rmtree(temporary_root, ignore_errors=True)


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    stdout: BinaryIO | None = None,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    logger.debug("Running: %s", " ".join(command))
    process = subprocess.run(
        command,
        env=env,
        text=stdout is None,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        stderr = (
            process.stderr.decode(errors="replace")
            if isinstance(process.stderr, bytes)
            else process.stderr
        )
        captured_stdout = (
            process.stdout.decode(errors="replace")
            if isinstance(process.stdout, bytes)
            else process.stdout
        )
        details = "\n".join(
            part.strip() for part in (captured_stdout, stderr) if part and part.strip()
        )
        raise SigningError(
            f"command exited with status {process.returncode}: {' '.join(command)}: {details}"
        )
    return process


def _require_secret(path: str, description: str) -> Path:
    secret = Path(path)
    if not secret.is_absolute() or secret.parent != Path("/run/secrets"):
        raise SigningError(f"{description} must be supplied from /run/secrets")
    if not secret.is_file():
        raise SigningError(f"{description} secret not found: {secret}")
    if secret.stat().st_size == 0:
        raise SigningError(f"{description} secret is empty: {secret}")
    return secret.resolve()


def _select_signing_key(listing: str) -> tuple[str, str, str]:
    primary_fingerprint = ""
    candidates: list[tuple[str, str]] = []
    pending: tuple[str, str] | None = None
    for line in listing.splitlines():
        fields = line.split(":")
        if fields[0] in {"sec", "ssb"}:
            pending = (fields[4], fields[11] if len(fields) > 11 else "")
            continue
        if fields[0] != "fpr" or pending is None:
            continue
        fingerprint = fields[9]
        key_id, capabilities = pending
        if not primary_fingerprint:
            primary_fingerprint = fingerprint
        if "s" in capabilities.lower():
            candidates.append((fingerprint, key_id))
        pending = None
    if not primary_fingerprint:
        raise SigningError("the secret contains no OpenPGP secret key")
    if not candidates:
        raise SigningError("the imported OpenPGP key has no signing-capable key")
    signing_fingerprint, signing_key_id = candidates[0]
    return primary_fingerprint, signing_fingerprint, signing_key_id.upper()


def _write_gpg_wrapper(directory: Path, passphrase: Path) -> Path:
    wrapper = directory / "gpg"
    wrapper.write_text(
        "#!/bin/sh\n"
        "exec /usr/bin/gpg --batch --pinentry-mode loopback --digest-algo SHA256 "
        f"--passphrase-file {passphrase} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return wrapper


def _write_verification_policy(
    root: Path,
    primary_fingerprint: str,
    signing_key_id: str,
    env: dict[str, str],
) -> tuple[Path, Path]:
    policies_root = root / "policies"
    keyrings_root = root / "keyrings"
    policy_dir = policies_root / signing_key_id
    keyring_dir = keyrings_root / signing_key_id
    policy_dir.mkdir(parents=True)
    keyring_dir.mkdir(parents=True)
    policy = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE Policy SYSTEM "https://www.debian.org/debsig/1.0/policy.dtd">\n'
        '<Policy xmlns="https://www.debian.org/debsig/1.0/">\n'
        f'  <Origin Name="debforge" id="{signing_key_id}" '
        'Description="debforge package signing key"/>\n'
        "  <Selection>\n"
        f'    <Required Type="origin" File="debforge.gpg" id="{signing_key_id}"/>\n'
        "  </Selection>\n"
        '  <Verification MinOptional="0">\n'
        f'    <Required Type="origin" File="debforge.gpg" id="{signing_key_id}"/>\n'
        "  </Verification>\n"
        "</Policy>\n"
    )
    (policy_dir / "debforge.pol").write_text(policy, encoding="utf-8")
    keyring_path = keyring_dir / "debforge.gpg"
    with keyring_path.open("wb") as keyring:
        _run(["/usr/bin/gpg", "--batch", "--export", primary_fingerprint], env=env, stdout=keyring)
    if keyring_path.stat().st_size == 0:
        raise SigningError("failed to export the OpenPGP public key")
    return policies_root, keyrings_root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

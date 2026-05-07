from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PRIVATE_KEY_SECRET = Path("/run/secrets/debforge-gpg-private-key")
PASSPHRASE_SECRET = Path("/run/secrets/debforge-gpg-passphrase")


class SigningError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    env: dict[str, str],
    stdout=None,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    process = subprocess.run(
        command,
        env=env,
        text=stdout is None,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        stderr = process.stderr.decode(errors="replace") if isinstance(process.stderr, bytes) else process.stderr
        captured_stdout = (
            process.stdout.decode(errors="replace")
            if isinstance(process.stdout, bytes)
            else process.stdout
        )
        details = "\n".join(
            part.strip() for part in (captured_stdout, stderr) if part and part.strip()
        )
        raise SigningError(
            f"command exited with status {process.returncode}: {' '.join(command)}: "
            f"{details}"
        )
    return process


def require_secret(path: Path, description: str) -> None:
    if not path.is_file():
        raise SigningError(f"missing {description}: {path}")
    if path.stat().st_size == 0:
        raise SigningError(f"empty {description}: {path}")


def select_signing_key(listing: str) -> tuple[str, str, str]:
    primary_fingerprint = ""
    candidates: list[tuple[str, str]] = []
    pending: tuple[str, str] | None = None

    for line in listing.splitlines():
        fields = line.split(":")
        record_type = fields[0]
        if record_type in {"sec", "ssb"}:
            capabilities = fields[11] if len(fields) > 11 else ""
            key_id = fields[4] if len(fields) > 4 else ""
            pending = (key_id, capabilities)
            continue
        if record_type != "fpr" or pending is None:
            continue

        fingerprint = fields[9] if len(fields) > 9 else ""
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


def write_gpg_wrapper(directory: Path) -> Path:
    wrapper = directory / "gpg"
    wrapper.write_text(
        "#!/bin/sh\n"
        "exec /usr/bin/gpg --batch --pinentry-mode loopback --digest-algo SHA256 "
        f"--passphrase-file {PASSPHRASE_SECRET} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return wrapper


def write_verification_policy(
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
        run(
            ["/usr/bin/gpg", "--batch", "--export", primary_fingerprint],
            env=env,
            stdout=keyring,
        )
    if keyring_path.stat().st_size == 0:
        raise SigningError("failed to export the OpenPGP public key")
    return policies_root, keyrings_root


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sign_packages(artifacts: list[Path], key_selector: str | None) -> dict[str, object]:
    require_secret(PRIVATE_KEY_SECRET, "OpenPGP private key secret")
    require_secret(PASSPHRASE_SECRET, "OpenPGP passphrase secret")
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
    write_gpg_wrapper(wrapper_dir)
    env = dict(
        os.environ,
        GNUPGHOME=str(gnupg_home),
        PATH=f"{wrapper_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
    )

    try:
        run(
            [
                "/usr/bin/gpg",
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                str(PASSPHRASE_SECRET),
                "--import",
                str(PRIVATE_KEY_SECRET),
            ],
            env=env,
        )
        list_command = ["/usr/bin/gpg", "--batch", "--with-colons", "--list-secret-keys"]
        if key_selector:
            list_command.append(key_selector)
        listing = run(list_command, env=env).stdout
        assert isinstance(listing, str)
        primary_fingerprint, signing_fingerprint, signing_key_id = select_signing_key(listing)
        policies_root, keyrings_root = write_verification_policy(
            temporary_root,
            primary_fingerprint,
            signing_key_id,
            env,
        )

        signed = []
        for artifact in artifacts:
            run(
                [
                    "debsigs",
                    "--sign=origin",
                    f"--default-key={signing_fingerprint}!",
                    str(artifact),
                ],
                env=env,
            )
            run(
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
                {
                    "artifact": artifact.name,
                    "sha256": sha256(artifact),
                    "verified": True,
                }
            )

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--key-id")
    args = parser.parse_args()

    try:
        raw_paths = json.loads(args.input.read_text(encoding="utf-8"))
        artifacts = [Path(path) for path in raw_paths]
        result = sign_packages(artifacts, args.key_id)
        args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001 - signer must return one concise failure
        print(f"Signing failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

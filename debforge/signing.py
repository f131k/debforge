from __future__ import annotations

import json
import logging
from pathlib import Path

from . import docker_client
from .exceptions import SigningError

logger = logging.getLogger(__name__)

PRIVATE_KEY_CONTAINER_PATH = "/run/secrets/debforge-gpg-private-key"
PASSPHRASE_CONTAINER_PATH = "/run/secrets/debforge-gpg-passphrase"


def validate_signing_secrets(
    mode: str,
    private_key_secret: str,
    passphrase_secret: str,
) -> None:
    """Fail before a long package build if mandatory signing cannot run."""
    if mode == "stub":
        return
    if mode != "debsigs":
        raise SigningError(f"Unsupported signing mode: {mode!r}")
    private_key_path = _require_secret(private_key_secret, "OpenPGP private key")
    passphrase_path = _require_secret(passphrase_secret, "OpenPGP passphrase")
    if private_key_path == passphrase_path:
        raise SigningError("Private key and passphrase must be separate secret files")


def sign_artifacts(
    artifact_paths: list[str],
    mode: str,
    *,
    image: str | None = None,
    workspace: str | None = None,
    key_id: str = "",
    private_key_secret: str = PRIVATE_KEY_CONTAINER_PATH,
    passphrase_secret: str = PASSPHRASE_CONTAINER_PATH,
) -> dict[str, object]:
    """Run the mandatory package-signing stage.

    ``debsigs`` runs in a separate container so package build scripts never
    receive the private key. Secret values are supplied only as read-only
    files mounted below ``/run/secrets``.
    """
    if not artifact_paths:
        raise SigningError("Signing stage received no package artifacts")
    missing = [path for path in artifact_paths if not Path(path).is_file()]
    if missing:
        raise SigningError(f"Signing stage cannot find artifacts: {', '.join(missing)}")
    if mode == "stub":
        logger.warning(
            "Signing stage is running in stub mode: %d package(s) remain unsigned",
            len(artifact_paths),
        )
        return {"mode": "stub", "signed": False, "artifacts": len(artifact_paths)}
    if mode != "debsigs":
        raise SigningError(f"Unsupported signing mode: {mode!r}")
    if not image or not workspace:
        raise SigningError("debsigs signing requires a signer image and workspace")

    workspace_path = Path(workspace).resolve()
    private_key_path = _require_secret(private_key_secret, "OpenPGP private key")
    passphrase_path = _require_secret(passphrase_secret, "OpenPGP passphrase")
    if private_key_path == passphrase_path:
        raise SigningError("Private key and passphrase must be separate secret files")

    container_artifacts = []
    for artifact_path in artifact_paths:
        artifact = Path(artifact_path).resolve()
        try:
            relative = artifact.relative_to(workspace_path)
        except ValueError as exc:
            raise SigningError(f"Artifact is outside signing workspace: {artifact}") from exc
        container_artifacts.append(str(Path("/build") / relative))

    input_path = workspace_path / "signing-input.json"
    result_path = workspace_path / "signing-result.json"
    input_path.write_text(json.dumps(container_artifacts) + "\n", encoding="utf-8")
    result_path.unlink(missing_ok=True)
    command = [
        "python3",
        "/usr/local/lib/debforge/sign_packages.py",
        "--input",
        "/build/signing-input.json",
        "--result",
        "/build/signing-result.json",
    ]
    if key_id:
        command.extend(["--key-id", key_id])

    try:
        exit_code, logs = docker_client.run_build_container(
            image=image,
            source_dir=str(workspace_path),
            command=command,
            env={"GNUPGHOME": "/tmp/debforge-gnupg"},
            extra_volumes={
                str(private_key_path): {"bind": PRIVATE_KEY_CONTAINER_PATH, "mode": "ro"},
                str(passphrase_path): {"bind": PASSPHRASE_CONTAINER_PATH, "mode": "ro"},
            },
        )
        if exit_code != 0 or not result_path.is_file():
            tail = "\n".join(logs.splitlines()[-30:])
            raise SigningError(f"debsigs signer failed with exit code {exit_code}:\n{tail}")

        result = json.loads(result_path.read_text(encoding="utf-8"))
        signed_artifacts = result.get("artifacts", [])
        if result.get("signed") is not True or len(signed_artifacts) != len(artifact_paths):
            raise SigningError("debsigs signer returned an incomplete result")
        if not all(entry.get("verified") is True for entry in signed_artifacts):
            raise SigningError("one or more debsigs signatures were not verified")

        logger.info(
            "Signed and verified %d package(s) with debsigs key %s",
            len(artifact_paths),
            result.get("key_fingerprint"),
        )
        return result
    finally:
        input_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


def _require_secret(path: str, description: str) -> Path:
    secret = Path(path)
    if not secret.is_absolute() or secret.parent != Path("/run/secrets"):
        raise SigningError(f"{description} must be supplied from /run/secrets")
    if not secret.is_file():
        raise SigningError(f"{description} secret not found: {secret}")
    if secret.stat().st_size == 0:
        raise SigningError(f"{description} secret is empty: {secret}")
    return secret.resolve()

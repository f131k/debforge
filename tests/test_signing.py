import json
from pathlib import Path

import pytest

from debforge.exceptions import SigningError
from debforge.signing import sign_artifacts


def test_stub_signing_is_explicitly_unsigned(tmp_path):
    package = tmp_path / "hello_1_arm64.deb"
    package.write_bytes(b"deb")

    result = sign_artifacts([str(package)], "stub")

    assert result == {"mode": "stub", "signed": False, "artifacts": 1}


def test_unknown_signing_mode_is_rejected(tmp_path):
    package = tmp_path / "hello_1_arm64.deb"
    package.write_bytes(b"deb")
    with pytest.raises(SigningError, match="Unsupported"):
        sign_artifacts([str(package)], "gpg")


def test_debsigs_requires_signer_configuration(tmp_path):
    package = tmp_path / "hello_1_arm64.deb"
    package.write_bytes(b"deb")
    with pytest.raises(SigningError, match="requires a signer image and workspace"):
        sign_artifacts([str(package)], "debsigs")


def test_debsigs_runs_isolated_signer_with_read_only_secrets(tmp_path, mocker):
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    package = output / "hello_1_arm64.deb"
    package.write_bytes(b"deb")
    private_key = tmp_path / "private.key"
    passphrase = tmp_path / "passphrase"
    private_key.write_text("private")
    passphrase.write_text("password")

    secret_lookup = mocker.patch(
        "debforge.signing._require_secret",
        side_effect=[private_key, passphrase],
    )

    def fake_signer(**kwargs):
        result = {
            "mode": "debsigs",
            "signed": True,
            "signature_type": "origin",
            "key_fingerprint": "A" * 40,
            "key_id": "A" * 16,
            "artifacts": [
                {"artifact": package.name, "sha256": "0" * 64, "verified": True}
            ],
        }
        (Path(kwargs["source_dir"]) / "signing-result.json").write_text(json.dumps(result))
        return 0, ""

    run_container = mocker.patch(
        "debforge.signing.docker_client.run_build_container",
        side_effect=fake_signer,
    )
    result = sign_artifacts(
        [str(package)],
        "debsigs",
        image="debforge-builder:latest",
        workspace=str(workspace),
    )

    assert result["signed"] is True
    assert result["artifacts"][0]["verified"] is True
    secret_lookup.assert_has_calls(
        [
            mocker.call("/run/secrets/debforge-gpg-private-key", "OpenPGP private key"),
            mocker.call("/run/secrets/debforge-gpg-passphrase", "OpenPGP passphrase"),
        ]
    )
    volumes = run_container.call_args.kwargs["extra_volumes"]
    assert volumes[str(private_key)]["mode"] == "ro"
    assert volumes[str(passphrase)]["mode"] == "ro"
    assert not (workspace / "signing-input.json").exists()
    assert not (workspace / "signing-result.json").exists()

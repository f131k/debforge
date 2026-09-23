from __future__ import annotations

import pytest

from debforge.exceptions import SigningError
from debforge.steps.sign_package import _select_signing_key, sign_packages


def test_select_signing_key_prefers_signing_capability():
    listing = (
        "sec:u:2048:1:1234567890ABCDEF:0:0:::::sc:\n"
        "fpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:\n"
    )
    assert _select_signing_key(listing) == (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "1234567890ABCDEF",
    )


def test_signing_rejects_missing_run_secret(tmp_path):
    artifact = tmp_path / "hello.deb"
    artifact.write_bytes(b"deb")
    with pytest.raises(SigningError, match="must be supplied from /run/secrets"):
        sign_packages([artifact], "", str(tmp_path / "key"), str(tmp_path / "passphrase"))

import textwrap

import pytest

from debforge.config import load_config
from debforge.exceptions import ConfigError


def test_load_minimal_valid_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent("""\
        gpg_key_id: "ABCDEF"
        target_architecture: "arm64"
    """))
    config = load_config(str(cfg_file), {})
    assert config.gpg_key_id == "ABCDEF"
    assert config.target_architecture == "arm64"


def test_build_config_uses_debsigs_without_explicit_key_selector(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("repo_backend: aptly\n")
    config = load_config(str(cfg_file), {})
    assert config.gpg_key_id == ""
    assert config.signing_mode == "debsigs"
    assert config.gpg_private_key_secret == "/run/secrets/debforge-gpg-private-key"
    assert config.gpg_passphrase_secret == "/run/secrets/debforge-gpg-passphrase"


def test_debsigs_secrets_must_be_under_run_secrets(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("gpg_private_key_secret: /tmp/private.key\n")
    with pytest.raises(ConfigError, match="directly under /run/secrets"):
        load_config(str(cfg_file), {})


def test_stub_signing_cannot_be_selected_in_project_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("signing_mode: stub\n")
    with pytest.raises(ConfigError, match="mandatory signing_mode='debsigs'"):
        load_config(str(cfg_file), {})


def test_cli_override_takes_precedence(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("gpg_key_id: FROMFILE\n")
    config = load_config(str(cfg_file), {"gpg_key_id": "FROMCLI"})
    assert config.gpg_key_id == "FROMCLI"


def test_missing_config_file_uses_defaults_with_overrides():
    config = load_config(
        "/nonexistent/path/config.yaml",
        {"gpg_key_id": "MYKEY"},
    )
    assert config.gpg_key_id == "MYKEY"
    assert config.source_suite == "bookworm"
    assert config.target_architecture == "native"

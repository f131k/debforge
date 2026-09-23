import pytest

from debforge.config import DebforgeConfig


@pytest.fixture
def base_config(tmp_path):
    return DebforgeConfig(
        work_dir=str(tmp_path / "work"),
        output_dir=str(tmp_path / "output"),
        target_architecture="native",
        source_mirror="http://deb.debian.org/debian",
        source_suite="bookworm",
        source_components=("main",),
        source_pockets=("",),
        source_repositories=(),
        build_options="nocheck",
        signing_mode="debsigs",
        gpg_key_id="TESTKEY1234567890",
        gpg_private_key_secret="/run/secrets/debforge-gpg-private-key",
        gpg_passphrase_secret="/run/secrets/debforge-gpg-passphrase",
        log_level="DEBUG",
        log_file=None,
        keep_build_artifacts=True,
    )

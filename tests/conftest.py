import os

import pytest

from debforge.config import DebforgeConfig
from debforge.pipeline import PackageContext


@pytest.fixture
def base_config(tmp_path):
    return DebforgeConfig(
        docker_image="debforge-builder:latest",
        docker_dockerfile=str(tmp_path / "Dockerfile.builder"),
        work_dir=str(tmp_path / "work"),
        gpg_key_id="TESTKEY1234567890",
        gpg_private_key_secret="/run/secrets/debforge-gpg-private-key",
        gpg_passphrase_secret="/run/secrets/debforge-gpg-passphrase",
        binary_signing_key=None,
        repo_backend="aptly",
        aptly_repo_name="local-builds",
        aptly_publish_endpoint="filesystem:debforge:",
        aptly_snapshot_prefix="debforge",
        reprepro_repo_path="/srv/apt/local",
        reprepro_codename="bookworm",
        reprepro_allow_duplicates=False,
        log_level="DEBUG",
        log_file=None,
        keep_build_artifacts=True,
        skip_unimplemented_stubs=True,
        debian_mirror=None,
        debian_suite="bookworm",
        signing_mode="stub",
    )


@pytest.fixture
def pkg_ctx(base_config, tmp_path):
    work_dir = str(tmp_path / "work" / "hello")
    os.makedirs(work_dir, exist_ok=True)
    return PackageContext(name="hello", work_dir=work_dir, config=base_config)

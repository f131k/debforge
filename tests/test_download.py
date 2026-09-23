from __future__ import annotations

import stat

import pytest

from debforge.exceptions import DownloadError
from debforge.network import NetworkConfig
from debforge.package_list import PackageSpec
from debforge.steps.download import AptSandbox, SourceSpec, resolve_source, setup_apt_sandbox


def test_setup_apt_sandbox_uses_corporate_mirrors(base_config, tmp_path, mocker):
    base_config.source_repositories = (
        {
            "mirror": "http://deb.debian.org/debian",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm"],
            "components": ["main"],
        },
        {
            "mirror": "http://security.debian.org/debian-security",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm-security"],
            "components": ["main"],
        },
    )
    mocker.patch("debforge.steps.download.resolve_native_architecture", return_value="amd64")
    network = NetworkConfig(proxy_host="proxy.example", proxy_token="top-secret")

    sandbox = setup_apt_sandbox(
        tmp_path,
        [PackageSpec("hello", "2.10-3")],
        "amd64",
        base_config,
        network,
    )

    sources = (tmp_path / "etc" / "sources.list").read_text()
    assert "https://proxy.example/repo/extras/debian_mirror/debian bookworm" in sources
    assert "https://proxy.example/repo/extras/debian_mirror/debian-security" in sources
    assert "trusted=yes" in sources
    assert sandbox.auth_path.read_text() == (
        "machine proxy.example login token password top-secret\n"
    )
    assert stat.S_IMODE(sandbox.auth_path.stat().st_mode) == 0o600
    assert "top-secret" not in (tmp_path / "etc" / "metadata.conf").read_text()


def test_resolve_source_preserves_exact_source_version(mocker):
    sandbox = AptSandbox({}, {}, sandbox_auth_path := mocker.MagicMock())
    mocker.patch(
        "debforge.steps.download.capture_command",
        return_value="Package: libfoo\nVersion: 1:2.0-3\nSource: foo (1:2.0-3)\n",
    )
    result = resolve_source(PackageSpec("libfoo", "1:2.0-3"), "arm64", sandbox)
    assert result == SourceSpec("foo", "1:2.0-3")
    assert sandbox.auth_path is sandbox_auth_path


def test_resolve_source_rejects_non_exact_version(mocker):
    sandbox = AptSandbox({}, {}, mocker.MagicMock())
    mocker.patch(
        "debforge.steps.download.capture_command",
        return_value="Package: hello\nVersion: 2.10-2\n",
    )
    with pytest.raises(DownloadError, match="no exact version"):
        resolve_source(PackageSpec("hello", "2.10-3"), "amd64", sandbox)

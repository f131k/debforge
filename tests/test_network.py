from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

from debforge.exceptions import ConfigError
from debforge.network import container_proxy_environment
from debforge.package_list import PackageSpec
from debforge.rebuilder import rebuild_packages


def _load_builder_module():
    path = Path(__file__).parent.parent / "docker" / "build_packages.py"
    spec = importlib.util.spec_from_file_location("debforge_builder_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_proxy_environment_is_disabled_without_token():
    assert container_proxy_environment({}) == {}


def test_proxy_environment_uses_debsec_names_and_default_host():
    assert container_proxy_environment({"DEBSEC_PROXY_TOKEN": "secret"}) == {
        "DEBSEC_PROXY_HOST": "proxy.host",
        "DEBSEC_PROXY_TOKEN": "secret",
    }


def test_proxy_environment_rejects_host_injection():
    with pytest.raises(ConfigError, match="bare hostname"):
        container_proxy_environment(
            {"DEBSEC_PROXY_TOKEN": "secret", "DEBSEC_PROXY_HOST": "https://proxy"}
        )


def test_builder_configures_corporate_apt_auth_and_mirrors(tmp_path, monkeypatch):
    builder = _load_builder_module()
    monkeypatch.setattr(builder, "capture", lambda *_args, **_kwargs: "arm64\n")
    network = builder.load_network_config(
        {"DEBSEC_PROXY_TOKEN": "top-secret", "DEBSEC_PROXY_HOST": "proxy.example"}
    )
    repositories = [
        {
            "mirror": "http://deb.debian.org/debian",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm", "bookworm-updates"],
            "components": ["main"],
        },
        {
            "mirror": "http://security.debian.org/debian-security",
            "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
            "suites": ["bookworm-security"],
            "components": ["main"],
        },
    ]

    builder.setup_apt_sandbox(
        tmp_path,
        [],
        "arm64",
        "http://deb.debian.org/debian",
        "bookworm",
        ["main"],
        [""],
        repositories,
        network,
    )

    sources = (tmp_path / "etc" / "sources.list").read_text()
    assert "https://proxy.example/repo/extras/debian_mirror/debian bookworm" in sources
    assert (
        "https://proxy.example/repo/extras/debian_mirror/debian-security bookworm-security"
        in sources
    )
    assert "trusted=yes" in sources

    auth_conf = tmp_path / "etc" / "auth.conf"
    assert auth_conf.read_text() == (
        "machine proxy.example login token password top-secret\n"
    )
    assert stat.S_IMODE(auth_conf.stat().st_mode) == 0o600

    apt_conf = (tmp_path / "etc" / "metadata.conf").read_text()
    assert f'Dir::Etc::netrc "{auth_conf}";' in apt_conf
    assert 'Acquire::https::proxy.example::Verify-Peer "false";' in apt_conf
    assert "top-secret" not in apt_conf


def test_custom_repository_on_proxy_host_is_not_rewritten():
    builder = _load_builder_module()
    network = builder.load_network_config(
        {"DEBSEC_PROXY_TOKEN": "secret", "DEBSEC_PROXY_HOST": "proxy.example"}
    )
    url = "https://proxy.example/repo/private/debian"
    assert network.mirror_url(url) == url


def test_rebuilder_forwards_proxy_environment(
    base_config, tmp_path, monkeypatch, mocker
):
    base_config.work_dir = str(tmp_path / "work")
    base_config.output_dir = str(tmp_path / "output")
    captured = {}

    def fake_run_build_container(**kwargs):
        captured.update(kwargs["env"])
        result = {
            "architecture": "arm64",
            "packages": [
                {
                    "name": "hello",
                    "version": "1.0",
                    "success": True,
                    "source": "hello=1.0",
                    "artifacts": [],
                }
            ],
        }
        Path(kwargs["source_dir"], "result.json").write_text(json.dumps(result))
        return 0, ""

    monkeypatch.setenv("DEBSEC_PROXY_TOKEN", "secret")
    monkeypatch.setenv("DEBSEC_PROXY_HOST", "proxy.example")
    mocker.patch("debforge.rebuilder.docker_client.ensure_image")
    mocker.patch(
        "debforge.rebuilder.docker_client.run_build_container",
        side_effect=fake_run_build_container,
    )

    rebuild_packages([PackageSpec("hello", "1.0")], base_config)

    assert captured["DEBSEC_PROXY_TOKEN"] == "secret"
    assert captured["DEBSEC_PROXY_HOST"] == "proxy.example"

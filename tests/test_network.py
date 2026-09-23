from __future__ import annotations

import pytest

from debforge.exceptions import ConfigError
from debforge.network import load_network_config


def test_proxy_is_disabled_without_token():
    assert load_network_config({}).is_corporate is False


def test_proxy_uses_debsec_environment_names():
    network = load_network_config(
        {"DEBSEC_PROXY_TOKEN": "secret", "DEBSEC_PROXY_HOST": "proxy.example"}
    )
    assert network.proxy_host == "proxy.example"
    assert network.proxy_token == "secret"


def test_proxy_rejects_host_injection():
    with pytest.raises(ConfigError, match="bare hostname"):
        load_network_config(
            {"DEBSEC_PROXY_TOKEN": "secret", "DEBSEC_PROXY_HOST": "https://proxy"}
        )


def test_repository_already_on_proxy_is_not_rewritten():
    network = load_network_config(
        {"DEBSEC_PROXY_TOKEN": "secret", "DEBSEC_PROXY_HOST": "proxy.example"}
    )
    url = "https://proxy.example/repo/private/debian"
    assert network.mirror_url(url) == url

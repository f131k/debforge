from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .exceptions import ConfigError

PROXY_HOST_ENV = "DEBSEC_PROXY_HOST"
PROXY_TOKEN_ENV = "DEBSEC_PROXY_TOKEN"
DEFAULT_PROXY_HOST = "proxy.host"
CORPORATE_DEBIAN_PATH = "/repo/extras/debian_mirror/debian"
CORPORATE_SECURITY_PATH = "/repo/extras/debian_mirror/debian-security"
DEBIAN_MIRROR_HOSTS = {
    "deb.debian.org",
    "security.debian.org",
    "ftp.debian.org",
    "archive.debian.org",
}


@dataclass(frozen=True)
class NetworkConfig:
    proxy_host: str | None = None
    proxy_token: str | None = None

    @property
    def is_corporate(self) -> bool:
        return self.proxy_token is not None

    def mirror_url(self, url: str, *, security: bool = False) -> str:
        """Map public Debian mirrors to the corporate repository endpoint."""
        if not self.is_corporate:
            return url
        parsed = urlsplit(url)
        if parsed.hostname == self.proxy_host:
            return url
        hostname = parsed.hostname or ""
        if hostname not in DEBIAN_MIRROR_HOSTS and not hostname.endswith(".debian.org"):
            return url
        path = CORPORATE_SECURITY_PATH if security else CORPORATE_DEBIAN_PATH
        return f"https://{self.proxy_host}{path}"


def load_network_config(environ: Mapping[str, str] | None = None) -> NetworkConfig:
    """Read the same corporate proxy variables as debsec."""
    source = os.environ if environ is None else environ
    token = source.get(PROXY_TOKEN_ENV)
    if not token:
        return NetworkConfig()

    host = source.get(PROXY_HOST_ENV, DEFAULT_PROXY_HOST).strip()
    if not host:
        raise ConfigError(f"{PROXY_HOST_ENV} cannot be empty when {PROXY_TOKEN_ENV} is set")
    if any(character in host for character in "\r\n/ "):
        raise ConfigError(f"{PROXY_HOST_ENV} must contain a bare hostname")
    if any(character in token for character in "\r\n"):
        raise ConfigError(f"{PROXY_TOKEN_ENV} cannot contain a newline")
    return NetworkConfig(proxy_host=host, proxy_token=token)

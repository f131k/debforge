from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .exceptions import ConfigError

logger = logging.getLogger(__name__)

PROXY_HOST_ENV = "DEBSEC_PROXY_HOST"
PROXY_TOKEN_ENV = "DEBSEC_PROXY_TOKEN"
DEFAULT_PROXY_HOST = "proxy.host"


def container_proxy_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the corporate proxy variables that may enter a build container.

    The token deliberately has no CLI or YAML equivalent: keeping it in the
    environment prevents it from appearing in command lines and manifests.
    An absent/empty token means direct network access, matching debsec.
    """
    source = os.environ if environ is None else environ
    token = source.get(PROXY_TOKEN_ENV)
    if not token:
        return {}

    host = source.get(PROXY_HOST_ENV, DEFAULT_PROXY_HOST).strip()
    if not host:
        raise ConfigError(f"{PROXY_HOST_ENV} cannot be empty when {PROXY_TOKEN_ENV} is set")
    if any(character in host for character in "\r\n/ "):
        raise ConfigError(f"{PROXY_HOST_ENV} must contain a bare hostname")
    if any(character in token for character in "\r\n"):
        raise ConfigError(f"{PROXY_TOKEN_ENV} cannot contain a newline")

    logger.info("Corporate APT proxy enabled (%s)", host)
    return {PROXY_HOST_ENV: host, PROXY_TOKEN_ENV: token}

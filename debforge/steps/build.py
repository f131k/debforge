from __future__ import annotations

import glob
import logging
import os

from .. import docker_client
from ..exceptions import BuildError
from ..network import container_proxy_environment

logger = logging.getLogger(__name__)


def build_in_docker(ctx) -> None:
    logger.info("[%s] Building package in Docker container", ctx.name)

    docker_client.ensure_image(ctx.config.docker_image, ctx.config.docker_dockerfile)

    source_dir = _find_source_dir(ctx)
    artifacts_dir = ctx.work_dir  # dpkg-buildpackage places .deb one level up from source tree

    # Build runs with root inside container so apt-get build-dep works.
    # dpkg-buildpackage -us -uc: skip signing (done on host after container exit).
    # -b: binary-only build (no source package output).
    cmd = _build_command(source_dir)

    exit_code, logs = docker_client.run_build_container(
        image=ctx.config.docker_image,
        source_dir=artifacts_dir,
        command=cmd,
        env={
            "DEBIAN_FRONTEND": "noninteractive",
            "DEB_BUILD_OPTIONS": "nocheck",
            **container_proxy_environment(),
        },
    )

    if exit_code != 0:
        raise BuildError(
            f"[{ctx.name}] dpkg-buildpackage failed (exit {exit_code}).\n"
            f"Last log lines:\n" + "\n".join(logs.splitlines()[-30:])
        )

    ctx.deb_paths = _collect_deb_artifacts(artifacts_dir)
    logger.info("[%s] Build successful: %s", ctx.name, ctx.deb_paths)


def _find_source_dir(ctx) -> str:
    if ctx.dsc_path:
        # Source dir is typically unpacked alongside the .dsc by dpkg-source
        candidates = [
            d for d in os.listdir(ctx.work_dir)
            if os.path.isdir(os.path.join(ctx.work_dir, d))
        ]
        if candidates:
            return os.path.join(ctx.work_dir, candidates[0])
    raise BuildError(f"[{ctx.name}] Cannot locate unpacked source directory in {ctx.work_dir!r}")


def _collect_deb_artifacts(directory: str) -> list[str]:
    debs = glob.glob(os.path.join(directory, "*.deb"))
    if not debs:
        raise BuildError(f"No .deb files found in {directory!r} after build")
    return debs


def _build_command(source_package_dir: str) -> list[str]:
    # /build/<source_dir> is the path inside the container (work_dir is mounted at /build)
    source_basename = os.path.basename(source_package_dir)
    inner_path = f"/build/{source_basename}"
    return [
        "/bin/bash", "-c",
        f"cd {inner_path} && apt-get build-dep -y . && dpkg-buildpackage -us -uc -b",
    ]

from __future__ import annotations

import logging
import os
import tarfile
import tempfile

import docker.errors

import docker

from .exceptions import DockerError

logger = logging.getLogger(__name__)


def _client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except docker.errors.DockerException as e:
        raise DockerError(f"Cannot connect to Docker daemon: {e}") from e


def ensure_image(
    image_name: str,
    dockerfile_path: str | None = None,
    *,
    force_rebuild: bool = False,
) -> None:
    client = _client()
    if not force_rebuild:
        try:
            client.images.get(image_name)
            logger.debug("Docker image %s already present", image_name)
            return
        except docker.errors.ImageNotFound:
            pass

    if not dockerfile_path or not os.path.exists(dockerfile_path):
        raise DockerError(
            f"Image {image_name!r} not found locally and no Dockerfile available at {dockerfile_path!r}. "
            f"Build it manually: docker build -t {image_name} <path>"
        )

    logger.info("Building Docker image %s from %s", image_name, dockerfile_path)
    try:
        _, logs = client.images.build(
            path=os.path.dirname(dockerfile_path),
            dockerfile=os.path.basename(dockerfile_path),
            tag=image_name,
            rm=True,
        )
        for entry in logs:
            if "stream" in entry:
                logger.debug("docker build: %s", entry["stream"].rstrip())
    except docker.errors.BuildError as e:
        raise DockerError(f"Failed to build image {image_name!r}: {e}") from e


def run_build_container(
    image: str,
    source_dir: str,
    command: list[str],
    env: dict[str, str] | None = None,
    remove_on_success: bool = True,
    extra_volumes: dict[str, dict[str, str]] | None = None,
) -> tuple[int, str]:
    client = _client()
    logger.info("Starting build container (image=%s)", image)
    logger.debug("Container command: %s", " ".join(command))

    volumes = {source_dir: {"bind": "/build", "mode": "rw"}}
    if extra_volumes:
        volumes.update(extra_volumes)

    try:
        container = client.containers.run(
            image=image,
            command=command,
            volumes=volumes,
            environment=env or {},
            detach=True,
            user="root",  # needed for apt-get build-dep inside container
        )
    except docker.errors.ImageNotFound as e:
        raise DockerError(f"Image {image!r} not found: {e}") from e
    except docker.errors.APIError as e:
        raise DockerError(f"Failed to start container: {e}") from e

    log_lines: list[str] = []
    try:
        for chunk in container.logs(stream=True, follow=True):
            line = chunk.decode("utf-8", errors="replace").rstrip()
            logger.debug("container: %s", line)
            log_lines.append(line)

        result = container.wait()
        exit_code: int = result["StatusCode"]

        if exit_code == 0 and remove_on_success:
            container.remove()
        elif exit_code != 0:
            logger.error("Container exited with code %d", exit_code)
            container.remove(force=True)
    except BaseException:
        # The proxy token is passed through the container environment. Never
        # leave an inspectable container behind after Ctrl+C or another abort.
        try:
            container.remove(force=True)
        except docker.errors.DockerException:
            logger.exception("Failed to remove interrupted build container")
        raise

    return exit_code, "\n".join(log_lines)


def copy_from_container(container_id: str, src_path: str, dest_dir: str) -> list[str]:
    client = _client()
    try:
        container = client.containers.get(container_id)
        archive_stream, _ = container.get_archive(src_path)
    except docker.errors.NotFound as e:
        raise DockerError(f"Container or path not found: {e}") from e

    copied: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        for chunk in archive_stream:
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        with tarfile.open(tmp_path) as tar:
            tar.extractall(dest_dir)
            copied = [os.path.join(dest_dir, m.name) for m in tar.getmembers() if m.isfile()]
    finally:
        os.unlink(tmp_path)

    return copied

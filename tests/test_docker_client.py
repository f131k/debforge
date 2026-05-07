from __future__ import annotations

import pytest

from debforge import docker_client


def test_interrupted_build_container_is_force_removed(tmp_path, mocker):
    container = mocker.Mock()
    container.logs.side_effect = KeyboardInterrupt
    client = mocker.Mock()
    client.containers.run.return_value = container
    mocker.patch("debforge.docker_client._client", return_value=client)

    with pytest.raises(KeyboardInterrupt):
        docker_client.run_build_container(
            image="builder",
            source_dir=str(tmp_path),
            command=["build"],
            env={"DEBSEC_PROXY_TOKEN": "secret"},
        )

    container.remove.assert_called_once_with(force=True)

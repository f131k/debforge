import os

import pytest

from debforge.exceptions import BuildError
from debforge.steps.build import _build_command, _collect_deb_artifacts


def test_collect_deb_artifacts_success(tmp_path):
    deb = tmp_path / "hello_1.0_amd64.deb"
    deb.write_bytes(b"")
    result = _collect_deb_artifacts(str(tmp_path))
    assert str(deb) in result


def test_collect_deb_artifacts_empty(tmp_path):
    with pytest.raises(BuildError, match="No .deb files"):
        _collect_deb_artifacts(str(tmp_path))


def test_build_command_structure():
    cmd = _build_command("/work/hello-1.0")
    assert "/bin/bash" in cmd
    assert "-c" in cmd
    script = cmd[-1]
    assert "hello-1.0" in script
    assert "dpkg-buildpackage" in script
    assert "-us" in script
    assert "-uc" in script
    assert "apt-get build-dep" in script


def test_build_in_docker_raises_on_failure(pkg_ctx, mocker):
    mocker.patch("debforge.steps.build.docker_client.ensure_image")

    # Fake source dir — also set dsc_path so _find_source_dir finds it
    source_dir = os.path.join(pkg_ctx.work_dir, "hello-1.0")
    os.makedirs(source_dir)
    pkg_ctx.dsc_path = os.path.join(pkg_ctx.work_dir, "hello_1.0.dsc")

    mocker.patch(
        "debforge.steps.build.docker_client.run_build_container",
        return_value=(1, "Build error output"),
    )

    from debforge.steps.build import build_in_docker
    with pytest.raises(BuildError, match="dpkg-buildpackage failed"):
        build_in_docker(pkg_ctx)

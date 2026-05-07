import os
import subprocess

import pytest

from debforge.exceptions import DownloadError
from debforge.steps.download import _find_dsc_file, fetch_source


def test_find_dsc_file_success(tmp_path):
    dsc = tmp_path / "hello_1.0.dsc"
    dsc.write_text("Format: 3.0\n")
    result = _find_dsc_file(str(tmp_path))
    assert result == str(dsc)


def test_find_dsc_file_not_found(tmp_path):
    with pytest.raises(DownloadError, match="No .dsc file"):
        _find_dsc_file(str(tmp_path))


def test_find_dsc_file_returns_first_when_multiple(tmp_path):
    (tmp_path / "a_1.0.dsc").write_text("")
    (tmp_path / "b_2.0.dsc").write_text("")
    result = _find_dsc_file(str(tmp_path))
    assert result.endswith(".dsc")


def test_fetch_source_calls_apt_get(pkg_ctx, mocker):
    mock_run = mocker.patch("debforge.steps.download.subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    # Place a fake .dsc so _find_dsc_file succeeds
    dsc_path = os.path.join(pkg_ctx.work_dir, "hello_1.0.dsc")
    with open(dsc_path, "w") as f:
        f.write("Format: 3.0\n")

    fetch_source(pkg_ctx)

    # Should have two calls: apt-get source and dpkg-query
    assert mock_run.call_count == 2
    call_args1 = mock_run.call_args_list[0][0][0]
    assert "apt-get" in call_args1
    assert "source" in call_args1
    assert pkg_ctx.name in call_args1
    assert pkg_ctx.dsc_path == dsc_path

    call_args2 = mock_run.call_args_list[1][0][0]
    assert "dpkg-query" in call_args2
    assert pkg_ctx.name in call_args2


def test_fetch_source_raises_on_apt_failure(pkg_ctx, mocker):
    mock_run = mocker.patch("debforge.steps.download.subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="E: Unable to find a source package"
    )

    with pytest.raises(DownloadError, match="apt-get source failed"):
        fetch_source(pkg_ctx)

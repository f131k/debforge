import subprocess

import pytest

from debforge.exceptions import PublishError
from debforge.steps.publish import _add_via_reprepro, _run_cmd, add_to_repo


def test_run_cmd_raises_on_failure(mocker):
    mocker.patch(
        "debforge.steps.publish.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="something went wrong"
        ),
    )
    with pytest.raises(PublishError, match="Command failed"):
        _run_cmd(["aptly", "repo", "add", "test", "/path/to/pkg.deb"])


def test_add_to_repo_unknown_backend(pkg_ctx):
    pkg_ctx.config.repo_backend = "unknown"
    with pytest.raises(PublishError, match="Unknown repo backend"):
        add_to_repo(pkg_ctx)


def test_reprepro_duplicate_raises_when_not_allowed(pkg_ctx, tmp_path, mocker):
    deb = tmp_path / "hello_1.0_amd64.deb"
    deb.write_bytes(b"")
    pkg_ctx.deb_paths = [str(deb)]
    pkg_ctx.config.reprepro_allow_duplicates = False

    mocker.patch(
        "debforge.steps.publish.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="already registered with different files"
        ),
    )

    with pytest.raises(PublishError):
        _add_via_reprepro(pkg_ctx)


def test_reprepro_duplicate_warns_when_allowed(pkg_ctx, tmp_path, mocker):
    deb = tmp_path / "hello_1.0_amd64.deb"
    deb.write_bytes(b"")
    pkg_ctx.deb_paths = [str(deb)]
    pkg_ctx.config.reprepro_allow_duplicates = True
    pkg_ctx.config.reprepro_repo_path = str(tmp_path)

    mocker.patch(
        "debforge.steps.publish.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="already registered with different files"
        ),
    )

    # Should not raise
    _add_via_reprepro(pkg_ctx)


def test_aptly_flow_calls_expected_commands(pkg_ctx, tmp_path, mocker):
    deb = tmp_path / "hello_1.0_amd64.deb"
    deb.write_bytes(b"")
    pkg_ctx.deb_paths = [str(deb)]
    pkg_ctx.config.repo_backend = "aptly"

    run_calls = []

    def fake_run_cmd(args, cwd=None):
        run_calls.append(args)

    mocker.patch("debforge.steps.publish._run_cmd", side_effect=fake_run_cmd)
    mocker.patch("debforge.steps.publish._aptly_endpoint_published", return_value=False)

    add_to_repo(pkg_ctx)

    commands = [" ".join(c) for c in run_calls]
    assert any("aptly repo add" in c for c in commands)
    assert any("aptly snapshot create" in c for c in commands)
    assert any("aptly publish snapshot" in c for c in commands)

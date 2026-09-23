from __future__ import annotations

from pathlib import Path

from debforge.package_list import PackageSpec
from debforge.steps.build import build_source, prepare_build_environment
from debforge.steps.download import AptSandbox, SourceSpec


def test_prepare_cross_build_environment_runs_inside_current_process(mocker):
    sandbox = AptSandbox({}, {"APT_CONFIG": "/work/build.conf"}, Path("/tmp/auth"))
    capture = mocker.patch("debforge.steps.build.capture_command", return_value="amd64\n")
    run = mocker.patch("debforge.steps.build.run_command")

    native = prepare_build_environment("arm64", sandbox)

    assert native == "amd64"
    capture.assert_called_once()
    assert mocker.call(["dpkg", "--add-architecture", "arm64"], env=sandbox.build_env) in run.mock_calls
    assert any("crossbuild-essential-arm64" in call.args[0] for call in run.mock_calls)


def test_build_source_calls_dpkg_buildpackage_directly(tmp_path, mocker):
    sandbox = AptSandbox({}, {"APT_CONFIG": "/work/build.conf"}, tmp_path / "auth")
    unpacked = tmp_path / "source"
    unpacked.mkdir()
    mocker.patch("debforge.steps.build.fetch_source", return_value=unpacked)
    run = mocker.patch("debforge.steps.build.run_command")
    mocker.patch("debforge.steps.build.Path.glob", return_value=[])

    result = build_source(
        SourceSpec("hello", "2.10-3"),
        [PackageSpec("hello", "2.10-3")],
        tmp_path,
        "amd64",
        "amd64",
        sandbox,
        "nocheck",
    )

    assert result == {}
    commands = [call.args[0] for call in run.mock_calls]
    assert any(command[0:2] == ["apt-get", "build-dep"] for command in commands)
    assert ["dpkg-buildpackage", "--no-sign", "--build=binary"] in commands


def test_build_source_recreates_exact_bin_nmu_version(tmp_path, mocker):
    sandbox = AptSandbox({}, {}, tmp_path / "auth")
    unpacked = tmp_path / "downloaded"
    unpacked.mkdir()
    mocker.patch("debforge.steps.build.fetch_source", return_value=unpacked)
    run = mocker.patch("debforge.steps.build.run_command")
    mocker.patch("debforge.steps.build.Path.glob", return_value=[])

    build_source(
        SourceSpec("foo", "1.0-1"),
        [PackageSpec("libfoo", "1.0-1+b1")],
        tmp_path,
        "amd64",
        "amd64",
        sandbox,
        "nocheck",
    )

    commands = [call.args[0] for call in run.mock_calls]
    assert any(
        command[0] == "dch" and command[command.index("--newversion") + 1] == "1.0-1+b1"
        for command in commands
    )

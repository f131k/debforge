from __future__ import annotations

from pathlib import Path

from debforge.package_list import PackageSpec
from debforge.pipeline import rebuild_packages
from debforge.steps.download import AptSandbox, SourceSpec


def test_pipeline_uses_existing_steps_directly(base_config, tmp_path, mocker):
    base_config.work_dir = str(tmp_path / "work")
    base_config.output_dir = str(tmp_path / "output")
    artifact = tmp_path / "hello_2.10-3_amd64.deb"
    artifact.write_bytes(b"deb")
    sandbox = AptSandbox({}, {}, tmp_path / "auth.conf")

    validate = mocker.patch("debforge.pipeline.sign_package.validate_signing_secrets")
    mocker.patch("debforge.pipeline.download.resolve_native_architecture", return_value="amd64")
    setup = mocker.patch("debforge.pipeline.download.setup_apt_sandbox", return_value=sandbox)
    update = mocker.patch("debforge.pipeline.download.update_package_indexes")
    resolve = mocker.patch(
        "debforge.pipeline.download.resolve_source", return_value=SourceSpec("hello", "2.10-3")
    )
    prepare = mocker.patch(
        "debforge.pipeline.build.prepare_build_environment", return_value="amd64"
    )
    build = mocker.patch(
        "debforge.pipeline.build.build_source", return_value={"hello": [artifact]}
    )
    sign = mocker.patch(
        "debforge.pipeline.sign_package.sign_packages",
        return_value={"mode": "debsigs", "signed": True, "artifacts": []},
    )

    result = rebuild_packages([PackageSpec("hello", "2.10-3")], base_config)

    assert result["packages"][0]["success"] is True
    assert Path(base_config.output_dir, artifact.name).is_file()
    validate.assert_called_once()
    setup.assert_called_once()
    update.assert_called_once()
    resolve.assert_called_once()
    prepare.assert_called_once()
    build.assert_called_once()
    sign.assert_called_once()

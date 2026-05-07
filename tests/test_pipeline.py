import pytest

from debforge.exceptions import DebforgeError
from debforge.pipeline import PackageContext, _run_step_stub, run_packages


def _make_ctx(config):
    return PackageContext(name="testpkg", work_dir="/tmp/test", config=config)


def test_run_step_stub_skips_when_configured(base_config):
    base_config.skip_unimplemented_stubs = True
    ctx = _make_ctx(base_config)

    def raises_not_impl(c):
        raise NotImplementedError("not implemented")

    # Should not raise
    _run_step_stub(ctx, raises_not_impl, "test step")


def test_run_step_stub_raises_when_not_skipping(base_config):
    base_config.skip_unimplemented_stubs = False
    ctx = _make_ctx(base_config)

    def raises_not_impl(c):
        raise NotImplementedError("not implemented")

    with pytest.raises(DebforgeError, match="not implemented"):
        _run_step_stub(ctx, raises_not_impl, "test step")


def test_run_packages_returns_false_on_failure(base_config, mocker):
    mocker.patch("debforge.pipeline.run_single_package", side_effect=DebforgeError("boom"))
    results = run_packages(["hello"], base_config)
    assert results == {"hello": False}


def test_run_packages_returns_true_on_success(base_config, mocker):
    mocker.patch("debforge.pipeline.run_single_package", return_value=None)
    results = run_packages(["hello"], base_config)
    assert results == {"hello": True}


def test_run_packages_mixed_results(base_config, mocker):
    def side_effect(pkg, cfg):
        if pkg == "fail-pkg":
            raise DebforgeError("fail")

    mocker.patch("debforge.pipeline.run_single_package", side_effect=side_effect)
    results = run_packages(["hello", "fail-pkg"], base_config)
    assert results["hello"] is True
    assert results["fail-pkg"] is False

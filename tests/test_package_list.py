import pytest

from debforge.exceptions import ConfigError
from debforge.package_list import parse_inline_specs, parse_package_text


def test_parse_dpkg_query_output_preserves_exact_versions():
    result = parse_package_text("libc6\t2.40-1ubuntu3.1\nlinux-libc-dev\t6.14.0-29.29\n")

    assert [(item.name, item.version) for item in result] == [
        ("libc6", "2.40-1ubuntu3.1"),
        ("linux-libc-dev", "6.14.0-29.29"),
    ]


def test_parse_accepts_arch_qualified_package_and_epoch():
    result = parse_package_text("libssl3t64:arm64\t3.4.1-1ubuntu2\nfoo\t1:2.0-3\n")

    assert result[0].name == "libssl3t64:arm64"
    assert result[1].version == "1:2.0-3"


def test_parse_rejects_space_delimited_input():
    with pytest.raises(ConfigError, match="Package<TAB>Version"):
        parse_package_text("hello 2.10-3\n")


def test_parse_deduplicates_identical_rows_and_rejects_conflicts():
    assert len(parse_package_text("hello\t1\nhello\t1\n")) == 1
    with pytest.raises(ConfigError, match="conflicting versions"):
        parse_package_text("hello\t1\nhello\t2\n")


def test_inline_specs_require_versions():
    with pytest.raises(ConfigError, match="has no version"):
        parse_inline_specs("hello")

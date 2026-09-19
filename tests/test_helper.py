from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from airwallet_export.errors import UnsupportedError
from airwallet_export.helper import (
    MacOSHelperBuilder,
    default_helper_config,
    default_helper_source,
)

UPSTREAM_SOURCE_SHA256 = "2d1423ee37aa77b5434c59fb11a8de69915e8d321b33eea2b0285bcffcbafd34"


def test_helper_builds_and_signs_lazily(tmp_path: Path) -> None:
    source = tmp_path / "airtraffic_host.m"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    output = tmp_path / "bin" / "airtraffic_host"
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == "xcrun":
            Path(command[command.index("-o") + 1]).write_bytes(b"helper")
        return subprocess.CompletedProcess(command, 0, "", "")

    builder = MacOSHelperBuilder(source=source, output=output, runner=runner)
    first = builder.ensure()
    second = builder.ensure()

    assert first == output
    assert second == output
    assert output.read_bytes() == b"helper"
    assert [call[0] for call in calls] == ["xcrun", "codesign"]
    assert str(source) in calls[0]
    expected_build_hash = hashlib.sha256(
        source.read_bytes() + b"\0" + default_helper_config().read_bytes()
    ).hexdigest()
    assert (output.parent / "airtraffic_host.sha256").read_text().strip() == (
        expected_build_hash
    )
    compile_call = calls[0]
    assert compile_call[compile_call.index("-include") + 1] == str(
        default_helper_config()
    )


def test_helper_rebuilds_when_source_hash_changes(tmp_path: Path) -> None:
    source = tmp_path / "airtraffic_host.m"
    source.write_text("v1", encoding="utf-8")
    output = tmp_path / "airtraffic_host"
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == "xcrun":
            Path(command[command.index("-o") + 1]).write_bytes(b"helper")
        return subprocess.CompletedProcess(command, 0, "", "")

    builder = MacOSHelperBuilder(source=source, output=output, runner=runner)
    builder.ensure()
    source.write_text("v2", encoding="utf-8")
    builder.ensure()

    assert [call[0] for call in calls] == ["xcrun", "codesign", "xcrun", "codesign"]


def test_helper_reports_unsupported_outside_macos(tmp_path: Path) -> None:
    source = tmp_path / "airtraffic_host.m"
    source.write_text("source", encoding="utf-8")
    builder = MacOSHelperBuilder(
        source=source,
        output=tmp_path / "helper",
        platform_name="win32",
    )

    assert builder.diagnostics()["supported"] is False


def test_airlift_submodule_helper_matches_the_recorded_upstream_commit() -> None:
    assert hashlib.sha256(default_helper_source().read_bytes()).hexdigest() == (
        UPSTREAM_SOURCE_SHA256
    )
    assert (default_helper_source().parents[1] / "LICENSE").is_file()


def test_missing_required_compiler_is_an_unsupported_dependency(tmp_path: Path) -> None:
    source = tmp_path / "airtraffic_host.m"
    source.write_text("source", encoding="utf-8")

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    builder = MacOSHelperBuilder(
        source=source,
        output=tmp_path / "helper",
        runner=runner,
    )

    with pytest.raises(UnsupportedError, match="required macOS tool is unavailable"):
        builder.ensure()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS host test")
def test_airlift_submodule_helper_really_builds_signs_and_reports_usage(
    tmp_path: Path,
) -> None:
    builder = MacOSHelperBuilder(
        source=default_helper_source(),
        output=tmp_path / "airtraffic_host",
    )

    helper = builder.ensure()
    completed = subprocess.run(
        [str(helper)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    result = json.loads(completed.stdout.strip())

    assert builder.verify_signature()
    assert completed.returncode == 64
    assert result["ok"] is False
    assert "usage: airtraffic_host" in result["error"]

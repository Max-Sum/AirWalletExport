from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .atomic import atomic_write_bytes
from .errors import OperationError, UnsupportedError

Runner = Callable[..., subprocess.CompletedProcess[str]]


def default_helper_source() -> Path:
    return (
        Path(__file__).resolve().parent
        / "vendor"
        / "airlift"
        / "Sources"
        / "airtraffic_host.m"
    )


def default_helper_config() -> Path:
    return Path(__file__).resolve().parent / "native" / "airtraffic_config.h"


def default_application_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AirWallet Export"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AirWallet Export"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "airwallet-export"


class MacOSHelperBuilder:
    def __init__(
        self,
        *,
        source: Path | None = None,
        config: Path | None = None,
        output: Path | None = None,
        runner: Runner = subprocess.run,
        platform_name: str | None = None,
    ) -> None:
        self.source = Path(source or default_helper_source())
        self.config = Path(config or default_helper_config())
        self.output = Path(
            output or default_application_data_dir() / "bin" / "airtraffic_host"
        )
        self.runner = runner
        self.platform_name = platform_name or sys.platform

    @property
    def metadata_path(self) -> Path:
        return self.output.with_name(f"{self.output.name}.sha256")

    def _source_hash(self) -> str:
        try:
            return hashlib.sha256(self.source.read_bytes()).hexdigest()
        except OSError as error:
            raise OperationError(f"could not read Airlift helper source: {error}") from error

    def _build_hash(self) -> str:
        try:
            source = self.source.read_bytes()
            config = self.config.read_bytes()
        except OSError as error:
            raise OperationError(f"could not read Airlift helper build input: {error}") from error
        return hashlib.sha256(source + b"\0" + config).hexdigest()

    def _is_current(self, source_hash: str) -> bool:
        if not self.output.is_file() or not self.metadata_path.is_file():
            return False
        try:
            return self.metadata_path.read_text(encoding="ascii").strip() == source_hash
        except OSError:
            return False

    def ensure(self) -> Path:
        if self.platform_name != "darwin":
            raise UnsupportedError("macOS Airlift helper is only supported on macOS")
        build_hash = self._build_hash()
        if self._is_current(build_hash):
            return self.output

        self.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.output.name}.",
            suffix=".tmp",
            dir=self.output.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        temporary.unlink(missing_ok=True)
        try:
            compile_command = [
                "xcrun",
                "clang",
                "-fobjc-arc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-include",
                str(self.config),
                "-framework",
                "Foundation",
                "-framework",
                "CoreFoundation",
                "/System/Library/PrivateFrameworks/AirTrafficHost.framework/AirTrafficHost",
                str(self.source),
                "-o",
                str(temporary),
            ]
            self._run(compile_command)
            self._run(["codesign", "--force", "--sign", "-", str(temporary)])
            os.replace(temporary, self.output)
            atomic_write_bytes(self.metadata_path, f"{build_hash}\n".encode("ascii"))
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return self.output

    def _run(self, command: list[str]) -> None:
        try:
            completed = self.runner(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            raise UnsupportedError(
                f"required macOS tool is unavailable: {command[0]}: {error}"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OperationError(
                f"{command[0]} failed with exit code {completed.returncode}: {detail}"
            )

    def verify_signature(self) -> bool:
        if not self.output.is_file():
            return False
        try:
            completed = self.runner(
                ["codesign", "--verify", "--verbose=2", str(self.output)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            return False
        return completed.returncode == 0

    def diagnostics(self) -> dict[str, Any]:
        supported = self.platform_name == "darwin"
        result: dict[str, Any] = {
            "supported": supported,
            "source": str(self.source),
            "output": str(self.output),
        }
        if supported:
            result["source_sha256"] = self._source_hash()
            result["build_sha256"] = self._build_hash()
            result["built"] = self.output.is_file()
            result["signature_valid"] = self.verify_signature()
        return result

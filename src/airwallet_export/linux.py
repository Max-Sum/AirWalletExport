from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from .errors import UnsupportedError
from .models import CapabilityResult, CardObservation, Device, ExportArtifact
from .recovery import RecoveryStore, RecoveryTransaction

LINUX_MESSAGE = "Linux is unsupported because no native ATC/Grappa client is available"


class LinuxTransport:
    async def list_devices(self) -> list[Device]:
        raise UnsupportedError(LINUX_MESSAGE)

    async def probe(self, device: Device) -> CapabilityResult:
        raise UnsupportedError(LINUX_MESSAGE)

    async def scan(
        self,
        device: Device,
        duration: float | None,
        stop_event: asyncio.Event | None,
        on_observation: Callable[[CardObservation], None] | None = None,
    ) -> list[CardObservation]:
        raise UnsupportedError(LINUX_MESSAGE)

    async def export_background(
        self,
        device: Device,
        card_hash: str,
        asset: str,
        output_path: Path,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> ExportArtifact:
        raise UnsupportedError(LINUX_MESSAGE)

    async def recover(
        self,
        device: Device,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> bool:
        raise UnsupportedError(LINUX_MESSAGE)

    def diagnostics(self) -> dict[str, object]:
        return {
            "transport": "linux",
            "supported": False,
            "experimental": False,
            "detail": LINUX_MESSAGE,
        }

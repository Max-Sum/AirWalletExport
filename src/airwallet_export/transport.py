from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import CapabilityResult, CardObservation, Device, ExportArtifact
from .recovery import RecoveryStore, RecoveryTransaction


@runtime_checkable
class Transport(Protocol):
    async def list_devices(self) -> list[Device]: ...

    async def probe(self, device: Device) -> CapabilityResult: ...

    async def scan(
        self,
        device: Device,
        duration: float | None,
        stop_event: asyncio.Event | None,
        on_observation: Callable[[CardObservation], None] | None = None,
    ) -> list[CardObservation]: ...

    async def export_background(
        self,
        device: Device,
        card_hash: str,
        asset: str,
        output_path: Path,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> ExportArtifact: ...

    async def recover(
        self,
        device: Device,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> bool: ...

    def diagnostics(self) -> dict[str, object]: ...

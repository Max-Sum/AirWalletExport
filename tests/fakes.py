from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from airwallet_export.atomic import atomic_write_new_bytes
from airwallet_export.errors import (
    MissingResource,
    OperationError,
    RecoveryRequiredError,
    UnsupportedError,
)
from airwallet_export.models import CapabilityResult, CardObservation, Device, ExportArtifact
from airwallet_export.recovery import RecoveryState, RecoveryStore, RecoveryTransaction

PNG = b"\x89PNG\r\n\x1a\ncard-background"
PDF = b"%PDF-1.7\ncard-background\n"


@dataclass
class FakeTransport:
    devices: list[Device] = field(default_factory=list)
    observations: list[CardObservation] = field(default_factory=list)
    assets: dict[tuple[str, str], bytes] = field(default_factory=dict)
    failure: tuple[str, str | None] | None = None
    list_error: Exception | None = None
    recover_error: Exception | None = None
    probe_result: CapabilityResult | None = None
    scan_interrupt: bool = False

    async def list_devices(self) -> list[Device]:
        if self.list_error:
            raise self.list_error
        return list(self.devices)

    async def probe(self, device: Device) -> CapabilityResult:
        return self.probe_result or CapabilityResult(
            ok=True,
            checks={"afc": True, "airtraffic": True},
        )

    async def scan(
        self,
        device: Device,
        duration: float | None,
        stop_event: asyncio.Event | None,
        on_observation: Callable[[CardObservation], None] | None = None,
    ) -> list[CardObservation]:
        await asyncio.sleep(0)
        for observation in self.observations:
            if on_observation is not None:
                on_observation(observation)
        if self.scan_interrupt:
            raise KeyboardInterrupt
        if stop_event is not None:
            stop_event.set()
        return list(self.observations)

    async def export_background(
        self,
        device: Device,
        card_hash: str,
        asset: str,
        output_path: Path,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> ExportArtifact:
        key = (card_hash, asset)
        if key not in self.assets:
            raise MissingResource(asset)

        if self.failure and self.failure[0] == "disconnect_before" and (
            self.failure[1] in (None, asset)
        ):
            store.remove(transaction.id)
            raise OperationError("Device disconnected before the Card Background move")

        store.transition(transaction.id, RecoveryState.STAGED)
        store.transition(transaction.id, RecoveryState.MOVED)

        data = self.assets[key]
        if self.failure and self.failure[0] == "invalid" and self.failure[1] in (None, asset):
            store.transition(transaction.id, RecoveryState.RESTORED)
            store.transition(transaction.id, RecoveryState.COMPLETE)
            raise OperationError(f"invalid Card Background signature: {asset}")

        if self.failure and self.failure[0] == "disconnect_after" and (
            self.failure[1] in (None, asset)
        ):
            raise RecoveryRequiredError(
                "Device disconnected after the Card Background move",
                transaction_id=transaction.id,
            )

        atomic_write_new_bytes(output_path, data)
        store.transition(transaction.id, RecoveryState.EXPORTED)
        store.transition(transaction.id, RecoveryState.RESTORED)
        store.transition(transaction.id, RecoveryState.COMPLETE)
        return ExportArtifact(
            card_id=transaction.card_hash,
            card_hash=card_hash,
            asset=asset,
            path=str(output_path.resolve()),
            bytes_written=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def recover(
        self,
        device: Device,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> bool:
        if self.recover_error:
            raise self.recover_error
        if transaction.state in (RecoveryState.PLANNED, RecoveryState.STAGED):
            store.remove(transaction.id)
            return True
        if transaction.state in (RecoveryState.MOVED, RecoveryState.EXPORTED):
            store.transition(transaction.id, RecoveryState.RESTORED)
        if store.get(transaction.id) is not None:
            store.transition(transaction.id, RecoveryState.COMPLETE)
        return True

    def diagnostics(self) -> dict[str, object]:
        return {"transport": "fake", "supported": True}


@dataclass
class ExperimentalTransport:
    async def list_devices(self) -> list[Device]:
        return []

    async def probe(self, device: Device) -> CapabilityResult:
        raise UnsupportedError("Windows backend is experimental")

    async def scan(
        self,
        device: Device,
        duration: float | None,
        stop_event: asyncio.Event | None,
        on_observation: Callable[[CardObservation], None] | None = None,
    ) -> list[CardObservation]:
        raise UnsupportedError("Windows backend is experimental")

    async def export_background(
        self,
        device: Device,
        card_hash: str,
        asset: str,
        output_path: Path,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> ExportArtifact:
        raise UnsupportedError("Windows backend is experimental")

    async def recover(
        self,
        device: Device,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> bool:
        raise UnsupportedError("Windows backend is experimental")

    def diagnostics(self) -> dict[str, object]:
        return {"transport": "windows", "supported": False, "experimental": True}

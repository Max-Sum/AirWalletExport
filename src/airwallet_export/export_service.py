from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import MissingResource, OperationError, RecoveryRequiredError
from .models import Card, Device
from .naming import CARD_BACKGROUND_ASSETS, output_filename, unique_output_path
from .recovery import RecoveryStore
from .transport import Transport


@dataclass(frozen=True)
class ExportSummary:
    device: Device
    output: str
    exported: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "device": self.device.to_dict(),
            "output": self.output,
            "exported": self.exported,
            "missing": self.missing,
            "recovery_required": False,
        }


async def recover_pending(
    transport: Transport,
    store: RecoveryStore,
    device: Device,
) -> int:
    foreign = [
        transaction
        for transaction in store.pending()
        if transaction.device_udid != device.udid
    ]
    if foreign:
        transaction = foreign[0]
        raise RecoveryRequiredError(
            f"unresolved Recovery Transaction belongs to another Device: "
            f"{transaction.device_udid}",
            transaction_id=transaction.id,
        )
    recovered = 0
    for transaction in store.pending(device.udid):
        try:
            capability = await transport.probe(device)
            if not capability.ok:
                detail = f": {capability.detail}" if capability.detail else ""
                raise RecoveryRequiredError(
                    f"Capability Probe failed before recovery{detail}",
                    transaction_id=transaction.id,
                )
            success = await transport.recover(device, transaction, store)
        except RecoveryRequiredError:
            raise
        except Exception as error:
            raise RecoveryRequiredError(
                f"could not complete Recovery Transaction {transaction.id}: {error}",
                transaction_id=transaction.id,
            ) from error
        if not success or store.get(transaction.id) is not None:
            raise RecoveryRequiredError(
                f"Recovery Transaction {transaction.id} remains unresolved",
                transaction_id=transaction.id,
            )
        recovered += 1
    return recovered


class ExportService:
    def __init__(self, transport: Transport, store: RecoveryStore) -> None:
        self.transport = transport
        self.store = store

    async def ensure_recovered(self, device: Device) -> int:
        return await recover_pending(self.transport, self.store, device)

    async def export(
        self,
        device: Device,
        cards: list[Card],
        output_directory: Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ExportSummary:
        await self.ensure_recovered(device)
        capability = await self.transport.probe(device)
        if not capability.ok:
            detail = f": {capability.detail}" if capability.detail else ""
            raise OperationError(f"Capability Probe failed{detail}")
        output = Path(output_directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        exported: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []

        for index, card in enumerate(cards, start=1):
            if on_progress is not None:
                on_progress(index, len(cards))
            for asset in CARD_BACKGROUND_ASSETS:
                filename = output_filename(card.card_id, asset)
                destination = unique_output_path(output, filename)
                token = secrets.token_hex(10)
                transaction = self.store.begin(
                    device_udid=device.udid,
                    card_hash=card.card_hash,
                    asset=asset,
                    output_path=destination,
                    source_path=(
                        f"/var/mobile/Library/Passes/Cards/{card.card_hash}.pkpass"
                    ),
                    generated={
                        "source": f"airlift-src-{token}",
                        "link": f"airlift-link-{token}",
                        "recovered": f"airlift-recovered-{token}",
                    },
                )
                try:
                    artifact = await self.transport.export_background(
                        device,
                        card.card_hash,
                        asset,
                        destination,
                        transaction,
                        self.store,
                    )
                except MissingResource:
                    self.store.remove(transaction.id)
                    missing.append(
                        {
                            "card_id": card.card_id,
                            "card_hash": card.card_hash,
                            "asset": asset,
                        }
                    )
                    continue
                except RecoveryRequiredError:
                    raise
                except Exception:
                    if self.store.get(transaction.id) is not None:
                        raise
                    raise

                if self.store.get(transaction.id) is not None:
                    raise RecoveryRequiredError(
                        f"export did not complete Recovery Transaction {transaction.id}",
                        transaction_id=transaction.id,
                    )
                item = artifact.to_dict()
                item["card_id"] = card.card_id
                exported.append(item)

        return ExportSummary(device=device, output=str(output), exported=exported, missing=missing)

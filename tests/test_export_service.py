from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from airwallet_export.errors import OperationError, RecoveryRequiredError
from airwallet_export.export_service import ExportService, recover_pending
from airwallet_export.models import CapabilityResult, Card, Device
from airwallet_export.naming import CARD_BACKGROUND_ASSETS
from airwallet_export.recovery import RecoveryState, RecoveryStore

from .fakes import PNG, FakeTransport


def device() -> Device:
    return Device(
        udid="test-device-udid",
        name="Test iPhone",
        product="iPhone16,1",
        version="18.7.8",
        build="22H352",
        connection="USB",
    )


def card() -> Card:
    return Card(
        card_hash="AbC123xyz789456QrsTu",
        label="Travel",
        card_id="travel-abc123xy",
        first_seen="now",
        last_seen="now",
    )


def test_export_writes_all_available_variants_in_contract_order(tmp_path: Path) -> None:
    transport = FakeTransport(devices=[device()])
    for index, asset in enumerate(CARD_BACKGROUND_ASSETS):
        transport.assets[(card().card_hash, asset)] = PNG + bytes([index])

    service = ExportService(transport, RecoveryStore(tmp_path / "recovery"))
    summary = asyncio.run(service.export(device(), [card()], tmp_path / "exports"))

    assert summary.ok
    assert [item["asset"] for item in summary.exported] == list(CARD_BACKGROUND_ASSETS)
    assert [Path(item["path"]).name for item in summary.exported] == [
        "travel-abc123xy@3x.png",
        "travel-abc123xy@2x.png",
        "travel-abc123xy.png",
        "travel-abc123xy.pdf",
    ]
    assert summary.missing == []
    assert len(list((tmp_path / "exports").iterdir())) == 4


def test_export_skips_missing_variants_without_stopping_other_assets(tmp_path: Path) -> None:
    transport = FakeTransport(devices=[device()])
    transport.assets[(card().card_hash, "cardBackgroundCombined@2x.png")] = PNG

    service = ExportService(transport, RecoveryStore(tmp_path / "recovery"))
    summary = asyncio.run(service.export(device(), [card()], tmp_path / "exports"))

    assert len(summary.exported) == 1
    assert [item["asset"] for item in summary.missing] == [
        "cardBackgroundCombined@3x.png",
        "cardBackgroundCombined.png",
        "cardBackgroundCombined.pdf",
    ]
    assert not (tmp_path / "recovery").exists() or not any(
        (tmp_path / "recovery").iterdir()
    )


def test_export_collision_uses_numeric_suffix(tmp_path: Path) -> None:
    transport = FakeTransport(devices=[device()])
    transport.assets[(card().card_hash, "cardBackgroundCombined@2x.png")] = PNG
    output = tmp_path / "exports"
    output.mkdir()
    (output / "travel-abc123xy@2x.png").write_bytes(b"existing")

    service = ExportService(transport, RecoveryStore(tmp_path / "recovery"))
    summary = asyncio.run(service.export(device(), [card()], output))

    assert Path(summary.exported[0]["path"]).name == "travel-abc123xy@2x (1).png"
    assert (output / "travel-abc123xy@2x.png").read_bytes() == b"existing"


def test_invalid_bytes_stop_batch_and_leave_no_unresolved_transaction(tmp_path: Path) -> None:
    transport = FakeTransport(
        devices=[device()],
        assets={
            (card().card_hash, "cardBackgroundCombined@3x.png"): b"not-a-png",
            (card().card_hash, "cardBackgroundCombined@2x.png"): PNG,
        },
        failure=("invalid", "cardBackgroundCombined@3x.png"),
    )
    store = RecoveryStore(tmp_path / "recovery")
    service = ExportService(transport, store)

    with pytest.raises(OperationError, match="invalid Card Background signature"):
        asyncio.run(service.export(device(), [card()], tmp_path / "exports"))

    assert store.pending(device().udid) == []
    assert not (tmp_path / "exports" / "travel-abc123xy@2x.png").exists()


def test_disconnect_after_move_requires_recovery_then_recover_cleans_it(tmp_path: Path) -> None:
    transport = FakeTransport(
        devices=[device()],
        assets={(card().card_hash, "cardBackgroundCombined@3x.png"): PNG},
        failure=("disconnect_after", "cardBackgroundCombined@3x.png"),
    )
    store = RecoveryStore(tmp_path / "recovery")
    service = ExportService(transport, store)

    with pytest.raises(RecoveryRequiredError):
        asyncio.run(service.export(device(), [card()], tmp_path / "exports"))

    pending = store.pending(device().udid)
    assert len(pending) == 1
    assert pending[0].state in (RecoveryState.MOVED, RecoveryState.EXPORTED)

    assert asyncio.run(recover_pending(transport, store, device())) == 1
    assert store.pending(device().udid) == []


def test_disconnect_before_move_does_not_require_recovery(tmp_path: Path) -> None:
    transport = FakeTransport(
        devices=[device()],
        assets={(card().card_hash, "cardBackgroundCombined@3x.png"): PNG},
        failure=("disconnect_before", "cardBackgroundCombined@3x.png"),
    )
    store = RecoveryStore(tmp_path / "recovery")

    with pytest.raises(OperationError, match="disconnected before"):
        asyncio.run(
            ExportService(transport, store).export(
                device(), [card()], tmp_path / "exports"
            )
        )

    assert store.pending(device().udid) == []


def test_capability_probe_failure_stops_before_transaction_or_move(tmp_path: Path) -> None:
    transport = FakeTransport(
        devices=[device()],
        assets={(card().card_hash, "cardBackgroundCombined@3x.png"): PNG},
        probe_result=CapabilityResult(
            ok=False,
            checks={"helper": True, "afc": False},
            detail="AFC unavailable",
        ),
    )
    store = RecoveryStore(tmp_path / "recovery")

    with pytest.raises(OperationError, match="Capability Probe failed"):
        asyncio.run(
            ExportService(transport, store).export(
                device(), [card()], tmp_path / "exports"
            )
        )

    assert store.pending() == []
    assert not (tmp_path / "exports").exists()


def test_unresolved_transaction_for_another_device_blocks_export(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    other = Device(
        udid="other-device",
        name="Other iPhone",
        product="iPhone17,1",
        version="19.0",
        build="23A1",
    )
    store.begin(
        device_udid=other.udid,
        card_hash=card().card_hash,
        asset="cardBackgroundCombined@3x.png",
        output_path=tmp_path / "other.png",
        source_path="/var/mobile/Library/Passes/Cards/other.pkpass",
        generated={"source": "source", "link": "link", "recovered": "recovered"},
    )
    transport = FakeTransport(
        devices=[device()],
        assets={(card().card_hash, "cardBackgroundCombined@3x.png"): PNG},
    )

    with pytest.raises(RecoveryRequiredError, match="another Device"):
        asyncio.run(
            ExportService(transport, store).export(
                device(), [card()], tmp_path / "exports"
            )
        )


def test_recovery_also_requires_a_successful_capability_probe(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = store.begin(
        device_udid=device().udid,
        card_hash=card().card_hash,
        asset="cardBackgroundCombined@3x.png",
        output_path=tmp_path / "card.png",
        source_path="/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass",
        generated={"source": "source", "link": "link", "recovered": "recovered"},
    )
    transport = FakeTransport(
        probe_result=CapabilityResult(
            ok=False,
            checks={"afc": False},
            detail="AFC unavailable",
        )
    )

    with pytest.raises(RecoveryRequiredError, match="Capability Probe failed before recovery"):
        asyncio.run(recover_pending(transport, store, device()))

    assert store.get(transaction.id) is not None

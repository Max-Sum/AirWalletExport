from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from airwallet_export.errors import OperationError
from airwallet_export.export_service import recover_pending
from airwallet_export.models import Device
from airwallet_export.recovery import RecoveryState, RecoveryStore, RecoveryTransaction

from .fakes import FakeTransport


def begin_transaction(store: RecoveryStore) -> RecoveryTransaction:
    return store.begin(
        device_udid="test-device-udid",
        card_hash="AbC123xyz789456QrsTu",
        asset="cardBackgroundCombined@2x.png",
        output_path=Path("/tmp/exports/card@2x.png"),
        source_path="/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass",
        generated={
            "source": "airlift-src-token",
            "link": "airlift-link-token",
            "recovered": "airlift-recovered-token",
        },
    )


def test_begin_writes_planned_transaction_before_device_work(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery")

    transaction = begin_transaction(store)

    path = store.root / transaction.id / "transaction.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert transaction.state is RecoveryState.PLANNED
    assert value["state"] == "planned"
    assert value["card_hash"] == "AbC123xyz789456QrsTu"
    assert value["asset"] == "cardBackgroundCombined@2x.png"
    assert value["generated"]["recovered"] == "airlift-recovered-token"


def test_transitions_are_durable_and_reject_skips(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = begin_transaction(store)

    with pytest.raises(OperationError, match="invalid recovery transition"):
        store.transition(transaction.id, RecoveryState.MOVED)

    for state in (
        RecoveryState.STAGED,
        RecoveryState.MOVED,
        RecoveryState.EXPORTED,
        RecoveryState.RESTORED,
    ):
        transaction = store.transition(transaction.id, state)
        assert transaction.state is state

    transaction = store.transition(transaction.id, RecoveryState.COMPLETE)
    assert store.get(transaction.id) is None
    assert not (store.root / transaction.id).exists()


def test_books_snapshot_round_trips_without_embedding_bytes_in_metadata(
    tmp_path: Path,
) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = begin_transaction(store)
    files = {
        "Books/Books.plist": b"books-data",
        "Books/Sync/Books.plist": None,
        "Books/Sync/Upload.plist": b"upload-data",
    }
    directories = {"Books": True, "Books/Sync": True, "Books/Sync/Database": False}

    store.write_books_snapshot(transaction.id, files=files, directories=directories)
    snapshot = store.load_books_snapshot(transaction.id)

    assert snapshot.files == files
    assert snapshot.directories == directories
    metadata = (store.root / transaction.id / "snapshot" / "manifest.json").read_text(
        encoding="utf-8"
    )
    assert "books-data" not in metadata
    assert "upload-data" not in metadata


def test_pending_transactions_survive_restart_and_filter_by_device(tmp_path: Path) -> None:
    root = tmp_path / "recovery"
    store = RecoveryStore(root)
    transaction = begin_transaction(store)
    other = store.begin(
        device_udid="other-device",
        card_hash="Def456xyz789456QrsTu",
        asset="cardBackgroundCombined.pdf",
        output_path=tmp_path / "other.pdf",
        source_path="/var/mobile/Library/Passes/Cards/Def456xyz789456QrsTu.pkpass",
        generated={},
    )

    restarted = RecoveryStore(root)

    assert restarted.get(transaction.id) is not None
    assert [item.id for item in restarted.pending("other-device", include_complete=False)] == [
        other.id
    ]


def test_corrupt_transaction_is_preserved_and_reported(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = begin_transaction(store)
    transaction_dir = store.root / transaction.id
    (transaction_dir / "transaction.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(OperationError, match="invalid Recovery Transaction"):
        store.pending()

    assert transaction_dir.exists()


@pytest.mark.parametrize(
    "interrupted_state",
    [
        RecoveryState.PLANNED,
        RecoveryState.STAGED,
        RecoveryState.MOVED,
        RecoveryState.EXPORTED,
        RecoveryState.RESTORED,
    ],
)
def test_recovery_completes_from_every_interrupted_state(
    tmp_path: Path,
    interrupted_state: RecoveryState,
) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = begin_transaction(store)
    if interrupted_state is not RecoveryState.PLANNED:
        state_order = [
            RecoveryState.STAGED,
            RecoveryState.MOVED,
            RecoveryState.EXPORTED,
            RecoveryState.RESTORED,
        ]
        for state in state_order:
            transaction = store.transition(transaction.id, state)
            if state is interrupted_state:
                break

    device = Device(
        udid=transaction.device_udid,
        name="Test iPhone",
        product="iPhone16,1",
        version="18.7.8",
        build="22H352",
    )

    assert asyncio.run(recover_pending(FakeTransport(), store, device)) == 1
    assert store.get(transaction.id) is None

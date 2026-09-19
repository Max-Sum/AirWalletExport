from __future__ import annotations

import json
from pathlib import Path

from airwallet_export.catalog import Catalog
from airwallet_export.models import CardObservation, Device


def make_device() -> Device:
    return Device(
        udid="test-device-udid",
        name="Test iPhone",
        product="iPhone16,1",
        version="18.7.8",
        build="22H352",
        connection="USB",
    )


def test_catalog_round_trip_preserves_device_and_observation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    catalog = Catalog(path)
    catalog.observe(
        make_device(),
        [CardObservation(card_hash="AbC123xyz789456QrsT", label="Travel Card")],
        observed_at="2026-09-20T01:02:03Z",
    )
    catalog.save()

    loaded = Catalog(path)
    loaded.load()
    cards = loaded.cards_for_device(make_device().udid)

    assert len(cards) == 1
    assert cards[0].card_hash == "AbC123xyz789456QrsT"
    assert cards[0].label == "Travel Card"
    assert cards[0].card_id == "travel-card-abc123xy"
    assert cards[0].first_seen == "2026-09-20T01:02:03Z"
    assert cards[0].last_seen == "2026-09-20T01:02:03Z"
    assert loaded.device(make_device().udid) == make_device()


def test_duplicate_observation_updates_last_seen_and_keeps_label(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.json")
    card_hash = "AbC123xyz789456QrsT"
    catalog.observe(
        make_device(),
        [CardObservation(card_hash=card_hash, label="Personal")],
        observed_at="2026-09-20T01:00:00Z",
    )
    catalog.observe(
        make_device(),
        [CardObservation(card_hash=card_hash)],
        observed_at="2026-09-20T02:00:00Z",
    )

    card = catalog.cards_for_device(make_device().udid)[0]
    assert card.label == "Personal"
    assert card.first_seen == "2026-09-20T01:00:00Z"
    assert card.last_seen == "2026-09-20T02:00:00Z"


def test_catalog_file_contains_no_raw_log_or_bytes(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    catalog = Catalog(path)
    catalog.observe(
        make_device(),
        [CardObservation(card_hash="AbC123xyz789456QrsT", label="Travel")],
        observed_at="2026-09-20T01:02:03Z",
    )
    catalog.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(data)
    assert "raw" not in encoded.lower()
    assert "signature" not in encoded.lower()
    assert "pan" not in encoded.lower()
    assert set(data) == {"version", "devices"}


def test_catalog_filters_cards_by_device(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.json")
    other = Device(
        udid="other-device",
        name="Other",
        product="iPhone17,1",
        version="19.0",
        build="23A1",
        connection="USB",
    )
    catalog.observe(make_device(), [CardObservation("AbC123xyz789456QrsT")], "now")
    catalog.observe(other, [CardObservation("Def456xyz789456QrsT")], "now")

    assert [card.card_hash for card in catalog.cards_for_device(other.udid)] == [
        "Def456xyz789456QrsT"
    ]

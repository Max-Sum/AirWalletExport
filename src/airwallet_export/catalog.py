from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import OperationError
from .models import Card, CardObservation, Device
from .naming import card_id

CATALOG_VERSION = 1


class Catalog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self._devices: dict[str, dict[str, Any]] = {}

    def load(self) -> Catalog:
        if not self.path.exists():
            self._devices = {}
            return self
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OperationError(f"could not read Catalog: {error}") from error
        if not isinstance(value, dict) or value.get("version") != CATALOG_VERSION:
            raise OperationError("unsupported Catalog version")
        devices = value.get("devices")
        if not isinstance(devices, dict):
            raise OperationError("invalid Catalog data")
        self._devices = {
            str(udid): entry
            for udid, entry in devices.items()
            if isinstance(entry, dict)
        }
        return self

    def save(self) -> None:
        payload = {"version": CATALOG_VERSION, "devices": self._devices}
        atomic_write_json(self.path, payload)

    def observe(
        self,
        device: Device,
        observations: list[CardObservation],
        observed_at: str,
    ) -> None:
        entry = self._devices.setdefault(device.udid, {"device": {}, "cards": {}})
        entry["device"] = device.to_dict()
        cards = entry.setdefault("cards", {})
        if not isinstance(cards, dict):
            raise OperationError("invalid Catalog Card data")

        for observation in observations:
            current = cards.get(observation.card_hash)
            if not isinstance(current, dict):
                current = {}
            label = observation.label or current.get("label")
            cards[observation.card_hash] = {
                "card_hash": observation.card_hash,
                "label": label,
                "card_id": card_id(str(label) if label else None, observation.card_hash),
                "first_seen": str(current.get("first_seen") or observed_at),
                "last_seen": observed_at,
            }

    def device(self, udid: str) -> Device | None:
        entry = self._devices.get(udid)
        if not isinstance(entry, dict) or not isinstance(entry.get("device"), dict):
            return None
        return Device.from_dict(entry["device"])

    def devices(self) -> list[Device]:
        result: list[Device] = []
        for entry in self._devices.values():
            value = entry.get("device") if isinstance(entry, dict) else None
            if isinstance(value, dict):
                result.append(Device.from_dict(value))
        return sorted(result, key=lambda item: (item.name.casefold(), item.udid))

    def cards_for_device(self, udid: str) -> list[Card]:
        entry = self._devices.get(udid)
        if not isinstance(entry, dict) or not isinstance(entry.get("cards"), dict):
            return []
        cards = [
            Card.from_dict(value)
            for value in entry["cards"].values()
            if isinstance(value, dict)
        ]
        return sorted(cards, key=lambda item: (item.card_id.casefold(), item.card_hash))

    def all_cards(self) -> list[tuple[Device, Card]]:
        result: list[tuple[Device, Card]] = []
        for device in self.devices():
            result.extend((device, card) for card in self.cards_for_device(device.udid))
        return result

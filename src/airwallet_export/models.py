from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Device:
    udid: str
    name: str
    product: str
    version: str
    build: str
    connection: str = "USB"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Device:
        return cls(
            udid=str(value["udid"]),
            name=str(value.get("name") or value["product"]),
            product=str(value["product"]),
            version=str(value.get("version") or "unknown"),
            build=str(value.get("build") or "unknown"),
            connection=str(value.get("connection") or "USB"),
        )


@dataclass(frozen=True)
class CardObservation:
    card_hash: str
    label: str | None = None


@dataclass(frozen=True)
class Card:
    card_hash: str
    label: str | None
    card_id: str
    first_seen: str
    last_seen: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Card:
        return cls(
            card_hash=str(value["card_hash"]),
            label=str(value["label"]) if value.get("label") else None,
            card_id=str(value["card_id"]),
            first_seen=str(value["first_seen"]),
            last_seen=str(value["last_seen"]),
        )


@dataclass(frozen=True)
class CapabilityResult:
    ok: bool
    checks: dict[str, bool]
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "checks": self.checks, "detail": self.detail}


@dataclass(frozen=True)
class ExportArtifact:
    card_id: str
    card_hash: str
    asset: str
    path: str
    bytes_written: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "card_id": self.card_id,
            "card_hash": self.card_hash,
            "asset": self.asset,
            "path": self.path,
            "bytes": self.bytes_written,
            "sha256": self.sha256,
        }

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .atomic import atomic_write_bytes, atomic_write_json
from .errors import OperationError


class RecoveryState(StrEnum):
    PLANNED = "planned"
    STAGED = "staged"
    MOVED = "moved"
    EXPORTED = "exported"
    RESTORED = "restored"
    COMPLETE = "complete"


TRANSITIONS = {
    RecoveryState.PLANNED: frozenset({RecoveryState.STAGED}),
    RecoveryState.STAGED: frozenset({RecoveryState.MOVED}),
    RecoveryState.MOVED: frozenset({RecoveryState.EXPORTED, RecoveryState.RESTORED}),
    RecoveryState.EXPORTED: frozenset({RecoveryState.RESTORED}),
    RecoveryState.RESTORED: frozenset({RecoveryState.COMPLETE}),
    RecoveryState.COMPLETE: frozenset(),
}


@dataclass(frozen=True)
class RecoveryTransaction:
    id: str
    device_udid: str
    card_hash: str
    asset: str
    output_path: str
    source_path: str
    state: RecoveryState
    created_at: str
    updated_at: str
    generated: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RecoveryTransaction:
        return cls(
            id=str(value["id"]),
            device_udid=str(value["device_udid"]),
            card_hash=str(value["card_hash"]),
            asset=str(value["asset"]),
            output_path=str(value["output_path"]),
            source_path=str(value["source_path"]),
            state=RecoveryState(str(value["state"])),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            generated={
                str(key): str(item)
                for key, item in value.get("generated", {}).items()
                if isinstance(item, str)
            },
        )


@dataclass(frozen=True)
class BooksSnapshot:
    files: dict[str, bytes | None]
    directories: dict[str, bool]


class RecoveryStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def begin(
        self,
        *,
        device_udid: str,
        card_hash: str,
        asset: str,
        output_path: Path,
        source_path: str,
        generated: dict[str, str],
    ) -> RecoveryTransaction:
        timestamp = self._now()
        transaction = RecoveryTransaction(
            id=uuid.uuid4().hex,
            device_udid=device_udid,
            card_hash=card_hash,
            asset=asset,
            output_path=str(output_path.resolve()),
            source_path=source_path,
            state=RecoveryState.PLANNED,
            created_at=timestamp,
            updated_at=timestamp,
            generated=dict(generated),
        )
        transaction_dir = self.root / transaction.id
        transaction_dir.mkdir(parents=True, exist_ok=False)
        self._write_transaction(transaction)
        return transaction

    def _transaction_path(self, transaction_id: str) -> Path:
        valid_characters = set("0123456789abcdef")
        if not transaction_id or any(
            character not in valid_characters for character in transaction_id
        ):
            raise OperationError("invalid Recovery Transaction identifier")
        return self.root / transaction_id / "transaction.json"

    def _write_transaction(self, transaction: RecoveryTransaction) -> None:
        atomic_write_json(self._transaction_path(transaction.id), transaction.to_dict())

    def get(self, transaction_id: str) -> RecoveryTransaction | None:
        path = self._transaction_path(transaction_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("transaction is not an object")
            return RecoveryTransaction.from_dict(value)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise OperationError(
                f"invalid Recovery Transaction {transaction_id}: {error}"
            ) from error

    def pending(
        self,
        device_udid: str | None = None,
        *,
        include_complete: bool = False,
    ) -> list[RecoveryTransaction]:
        if not self.root.exists():
            return []
        transactions: list[RecoveryTransaction] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir():
                continue
            transaction = self.get(directory.name)
            if transaction is None:
                continue
            if not include_complete and transaction.state is RecoveryState.COMPLETE:
                continue
            if device_udid is None or transaction.device_udid == device_udid:
                transactions.append(transaction)
        return transactions

    def transition(self, transaction_id: str, state: RecoveryState) -> RecoveryTransaction:
        transaction = self.get(transaction_id)
        if transaction is None:
            raise OperationError(f"Recovery Transaction {transaction_id} does not exist")
        if state not in TRANSITIONS[transaction.state]:
            raise OperationError(
                f"invalid recovery transition: {transaction.state.value} -> {state.value}"
            )
        updated = RecoveryTransaction(
            **{
                **asdict(transaction),
                "state": state,
                "updated_at": self._now(),
            }
        )
        self._write_transaction(updated)
        if state is RecoveryState.COMPLETE:
            transaction_dir = self.root / transaction_id
            if transaction_dir.exists():
                shutil.rmtree(transaction_dir)
        return updated

    def remove(self, transaction_id: str) -> None:
        transaction_dir = self.root / transaction_id
        if transaction_dir.exists():
            shutil.rmtree(transaction_dir)

    def write_books_snapshot(
        self,
        transaction_id: str,
        *,
        files: dict[str, bytes | None],
        directories: dict[str, bool],
    ) -> None:
        if self.get(transaction_id) is None:
            raise OperationError(f"Recovery Transaction {transaction_id} does not exist")
        snapshot = self.root / transaction_id / "snapshot"
        files_dir = snapshot / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, str | None]] = []
        for index, (path, data) in enumerate(files.items()):
            if data is None:
                entries.append({"path": path, "snapshot": None, "sha256": None})
                continue
            name = f"{index:03d}.bin"
            atomic_write_bytes(files_dir / name, data)
            entries.append(
                {
                    "path": path,
                    "snapshot": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest = {"files": entries, "directories": directories}
        atomic_write_json(snapshot / "manifest.json", manifest)

    def load_books_snapshot(self, transaction_id: str) -> BooksSnapshot:
        if self.get(transaction_id) is None:
            raise OperationError(f"Recovery Transaction {transaction_id} does not exist")
        path = self.root / transaction_id / "snapshot" / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OperationError(f"invalid Books snapshot: {error}") from error
        files: dict[str, bytes | None] = {}
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict):
                raise OperationError("invalid Books snapshot file entry")
            file_path = str(entry["path"])
            name = entry.get("snapshot")
            if name is None:
                files[file_path] = None
                continue
            data = (path.parent / "files" / str(name)).read_bytes()
            expected = str(entry.get("sha256") or "")
            if hashlib.sha256(data).hexdigest() != expected:
                raise OperationError(f"Books snapshot hash mismatch: {file_path}")
            files[file_path] = data
        directories = {
            str(key): bool(value)
            for key, value in manifest.get("directories", {}).items()
        }
        return BooksSnapshot(files=files, directories=directories)

from __future__ import annotations

from .errors import OperationError


def validate_background(asset: str, data: bytes) -> None:
    if asset.endswith(".png") and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OperationError(f"invalid Card Background signature: {asset}")
    if asset.endswith(".pdf") and not data.startswith(b"%PDF"):
        raise OperationError(f"invalid Card Background signature: {asset}")
    if not asset.endswith((".png", ".pdf")):
        raise OperationError(f"unsupported Card Background resource: {asset}")

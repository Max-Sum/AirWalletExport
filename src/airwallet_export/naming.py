from __future__ import annotations

import unicodedata
from pathlib import Path

CARD_BACKGROUND_PREFIX = "cardBackgroundCombined"
CARD_BACKGROUND_ASSETS = (
    "cardBackgroundCombined@3x.png",
    "cardBackgroundCombined@2x.png",
    "cardBackgroundCombined.png",
    "cardBackgroundCombined.pdf",
)


def _safe_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    output: list[str] = []
    separator = False
    for character in normalized:
        if character.isalnum():
            if separator and output:
                output.append("-")
            output.append(character)
            separator = False
        else:
            separator = bool(output)
    return "".join(output).strip("-")[:96]


def card_id(label: str | None, card_hash: str) -> str:
    """Build a human-readable, filename-safe Card ID."""
    stem = _safe_stem(label) if label else ""
    prefix = stem or "card"
    hash_part = _safe_stem(card_hash[:8]) or "unknown"
    return f"{prefix}-{hash_part or 'unknown'}"


def resource_suffix(asset: str) -> str:
    if asset not in CARD_BACKGROUND_ASSETS:
        raise ValueError(f"unsupported Card Background resource: {asset}")
    return asset.removeprefix(CARD_BACKGROUND_PREFIX)


def output_filename(card_identifier: str, asset: str) -> str:
    safe_identifier = Path(card_identifier).name
    return f"{safe_identifier}{resource_suffix(asset)}"


def unique_output_path(directory: Path, filename: str) -> Path:
    """Return a non-existing path, adding numeric suffixes when necessary."""
    safe_name = Path(filename).name
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate

    stem = Path(safe_name).stem
    extension = Path(safe_name).suffix
    index = 1
    while True:
        candidate = directory / f"{stem} ({index}){extension}"
        if not candidate.exists():
            return candidate
        index += 1

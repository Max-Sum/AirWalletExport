from __future__ import annotations

import re
import uuid

from .models import CardObservation

HASH_PATTERN = r"[-A-Za-z0-9_+=]{20,44}"
CARD_PATH_PATTERN = re.compile(
    rf"/Passes/Cards/(?P<hash>{HASH_PATTERN})(?:\.pkpass|\.cache|\.pkcache|/)"
)
CARD_TOKEN_PATTERN = re.compile(
    rf"(?:paymentPassUniqueIdentifier|paymentPassWithUniqueIdentifier)"
    rf"\s*[=:]\s*[\"']?(?P<hash>{HASH_PATTERN})",
    re.IGNORECASE,
)
IMAGE_CACHE_PATTERN = re.compile(
    r"Image in cache, calling completion for "
    r"(?P<hash>[A-Za-z0-9+/_-]{27}=):",
    re.IGNORECASE,
)
WALLET_CONTEXT_PATTERN = re.compile(
    r"(?:com\.apple\.passkit|passkit|passd|passbook|stockholm|nanopassd)",
    re.IGNORECASE,
)
LABEL_PATTERN = re.compile(
    r'(?:displayName|localizedName|name)\s*[=:]\s*"((?:\\.|[^"\\]){1,80})"',
    re.IGNORECASE,
)
PLACEHOLDERS = frozenset(
    {
        "00000000000000000000",
        "11111111111111111111",
        "applepay",
        "apple-pay",
    }
)


def _valid_hash(value: str) -> bool:
    normalized = value.strip()
    if normalized.casefold() in PLACEHOLDERS:
        return False
    if len(set(normalized)) <= 2:
        return False
    try:
        uuid.UUID(normalized)
    except ValueError:
        return True
    return False


def parse_card_observation(line: str) -> CardObservation | None:
    """Reduce one Wallet syslog line to a Card Hash and optional label."""
    match = CARD_PATH_PATTERN.search(line) or CARD_TOKEN_PATTERN.search(line)
    if match is None and WALLET_CONTEXT_PATTERN.search(line):
        match = IMAGE_CACHE_PATTERN.search(line)
    if match is None:
        return None
    card_hash = match.group("hash")
    if not _valid_hash(card_hash):
        return None

    label_match = LABEL_PATTERN.search(line)
    label = label_match.group(1).strip() if label_match else None
    return CardObservation(card_hash=card_hash, label=label or None)

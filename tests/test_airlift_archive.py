from __future__ import annotations

import io
import plistlib
import stat
import zipfile

import pytest

from airwallet_export.airlift import (
    CARD_ROOT,
    build_airlock_archive,
    build_books_plist,
    target_identifier,
)
from airwallet_export.errors import OperationError


def test_archive_contains_safe_symlink_and_payload_contract() -> None:
    target = "/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass"

    archive = build_airlock_archive(target)

    with zipfile.ZipFile(io.BytesIO(archive)) as value:
        names = value.namelist()
        assert "p0/p1/p2/link" in names
        assert "payload" in names
        link = value.getinfo("p0/p1/p2/link")
        mode = link.external_attr >> 16
        assert stat.S_ISLNK(mode)
        assert value.read("p0/p1/p2/link") == (
            b"../../../var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass"
        )
        assert value.read("payload") == b""


def test_books_plist_only_contains_expected_asset_identifiers() -> None:
    identifiers = [
        "../../airlift-src-token/p0/p1/p2/link",
        "../../airlift-src-token/payload",
        "var/mobile/Library/Passes/Cards/card.pkpass",
    ]

    books = plistlib.loads(build_books_plist(identifiers))

    assert [row["Persistent ID"] for row in books["Books"]] == identifiers
    assert all(set(row) == {"Persistent ID", "Item ID", "DSID"} for row in books["Books"])


def test_target_identifier_allows_the_required_relative_card_path() -> None:
    identifier = target_identifier(
        "/var/mobile/Library/Passes/Cards/test-card-hash-path-000001.pkpass/"
        "cardBackgroundCombined@2x.png"
    )

    assert identifier == (
        "../../../Library/Passes/Cards/test-card-hash-path-000001.pkpass/"
        "cardBackgroundCombined@2x.png"
    )


def test_target_identifier_rejects_parent_traversal() -> None:
    with pytest.raises(OperationError, match="outside the Apple Pay Cards root"):
        target_identifier(f"{CARD_ROOT}/../../Documents/secret.png")

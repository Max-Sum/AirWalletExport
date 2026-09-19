from __future__ import annotations

from pathlib import Path

import pytest

from airwallet_export.atomic import atomic_write_new_bytes
from airwallet_export.naming import card_id, output_filename, unique_output_path


def test_card_id_uses_safe_label_and_hash_prefix() -> None:
    assert card_id("Visa • Personal", "AbC123xyz789456") == "visa-personal-abc123xy"


def test_card_id_keeps_unicode_letters_without_path_characters() -> None:
    assert card_id("旅行/信用卡", "Hash_123456789") == "旅行-信用卡-hash-123"


def test_card_id_without_label_uses_card_prefix() -> None:
    assert card_id(None, "ABCDEF1234567890") == "card-abcdef12"


def test_output_filename_uses_resource_suffix() -> None:
    assert output_filename("card-a1b2c3d4", "cardBackgroundCombined@3x.png") == (
        "card-a1b2c3d4@3x.png"
    )
    assert output_filename("card-a1b2c3d4", "cardBackgroundCombined.pdf") == (
        "card-a1b2c3d4.pdf"
    )


def test_unique_output_path_never_overwrites(tmp_path: Path) -> None:
    first = tmp_path / "card-a1b2c3d4@2x.png"
    second = tmp_path / "card-a1b2c3d4@2x (1).png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    assert unique_output_path(tmp_path, "card-a1b2c3d4@2x.png") == (
        tmp_path / "card-a1b2c3d4@2x (2).png"
    )


def test_unique_output_path_rejects_suffix_escape(tmp_path: Path) -> None:
    assert unique_output_path(tmp_path, "../outside.png") == tmp_path / "outside.png"


def test_atomic_write_new_bytes_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "card.png"
    path.write_bytes(b"original")

    with pytest.raises(FileExistsError):
        atomic_write_new_bytes(path, b"replacement")

    assert path.read_bytes() == b"original"

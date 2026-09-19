from __future__ import annotations

from airwallet_export.discovery import parse_card_observation


def test_parser_reads_card_hash_from_wallet_path() -> None:
    line = (
        "Sep 20 10:00:00 iPhone passd[42] <Notice>: "
        "loaded /var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass/manifest.json"
    )

    observation = parse_card_observation(line)

    assert observation is not None
    assert observation.card_hash == "AbC123xyz789456QrsTu"
    assert observation.label is None


def test_parser_extracts_only_stable_optional_label_fields() -> None:
    line = (
        'walletd: paymentPassUniqueIdentifier=AbC123xyz789456QrsTu '
        'displayName="Travel Card" organizationName="Example Bank"'
    )

    observation = parse_card_observation(line)

    assert observation is not None
    assert observation.card_hash == "AbC123xyz789456QrsTu"
    assert observation.label == "Travel Card"


def test_parser_reads_card_hash_from_wallet_image_cache_completion() -> None:
    line = (
        "Preferences[64991] [com.apple.passkit:General] "
        "Image in cache, calling completion for "
        "test-card-hash-cache-000001=:"
        "0d162029c8c317c18301318360b2919afd6d0b50:777-{66, 41.501385041551245}"
    )

    observation = parse_card_observation(line)

    assert observation is not None
    assert observation.card_hash == "test-card-hash-cache-000001="
    assert observation.label is None


def test_parser_rejects_image_cache_token_outside_wallet() -> None:
    line = (
        "Photos[42] wallet preview Image in cache, calling completion for "
        "test-card-hash-cache-000001=:"
        "0d162029c8c317c18301318360b2919afd6d0b50:777-{66, 41.501385041551245}"
    )

    assert parse_card_observation(line) is None


def test_parser_rejects_uuid_and_placeholder_values() -> None:
    uuid_line = "passd: 123e4567-e89b-12d3-a456-426614174000.pkpass"
    zero_line = "passd: /var/mobile/Library/Passes/Cards/00000000000000000000.pkpass"

    assert parse_card_observation(uuid_line) is None
    assert parse_card_observation(zero_line) is None


def test_parser_ignores_unrelated_log_lines() -> None:
    assert parse_card_observation("SpringBoard: application did become active") is None


def test_parser_does_not_promote_generic_wallet_passes_to_cards() -> None:
    assert parse_card_observation(
        "walletd: uniqueIdentifier=AbC123xyz789456QrsTu displayName=\"Loyalty Card\""
    ) is None
    assert parse_card_observation(
        "/var/mobile/Library/Passes/AbC123xyz789456QrsTu.pkpass/manifest.json"
    ) is None

from __future__ import annotations

import pytest

from airwallet_export.errors import OperationError
from airwallet_export.validation import validate_background


def test_valid_png_and_pdf_signatures_are_accepted() -> None:
    validate_background("cardBackgroundCombined@2x.png", b"\x89PNG\r\n\x1a\nrest")
    validate_background("cardBackgroundCombined.pdf", b"%PDF-1.7\nrest")


def test_invalid_signature_is_a_protocol_error() -> None:
    with pytest.raises(OperationError, match="invalid Card Background signature"):
        validate_background("cardBackgroundCombined@2x.png", b"<html>not a png</html>")


def test_asset_extension_controls_expected_signature() -> None:
    with pytest.raises(OperationError):
        validate_background("cardBackgroundCombined.pdf", b"\x89PNG\r\n\x1a\n")

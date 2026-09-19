from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from airwallet_export.errors import OperationError, UnsupportedError
from airwallet_export.linux import LinuxTransport
from airwallet_export.macos import MacOSTransport
from airwallet_export.models import Device
from airwallet_export.recovery import RecoveryState, RecoveryStore
from airwallet_export.transport import Transport
from airwallet_export.windows import WindowsTransport

from .fakes import ExperimentalTransport, FakeTransport


def test_fake_and_platform_transports_expose_transport_contract() -> None:
    for value in (
        FakeTransport(),
        ExperimentalTransport(),
        MacOSTransport(),
        WindowsTransport(),
        LinuxTransport(),
    ):
        assert isinstance(value, Transport)


def test_windows_transport_is_honest_experimental_boundary() -> None:
    transport = WindowsTransport()

    with pytest.raises(UnsupportedError, match="experimental"):
        asyncio.run(transport.list_devices())

    assert transport.diagnostics() == {
        "transport": "windows",
        "supported": False,
        "experimental": True,
        "detail": "Windows device transport is experimental and unavailable",
    }


def test_linux_transport_reports_missing_native_client() -> None:
    transport = LinuxTransport()

    with pytest.raises(UnsupportedError, match="native ATC/Grappa"):
        asyncio.run(transport.list_devices())


def test_macos_list_devices_awaits_lockdown_values(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mux:
        serial = "test-device-udid"

    class UsbMux:
        @staticmethod
        async def select_devices_by_connection_type(connection_type: str) -> list[Any]:
            assert connection_type == "USB"
            return [Mux()]

    class Lockdown:
        async def get_value(self) -> dict[str, str]:
            return {
                "UniqueDeviceID": "test-device-udid",
                "DeviceName": "Test iPhone",
                "ProductType": "iPhone16,1",
                "ProductVersion": "18.7.8",
                "BuildVersion": "22H352",
            }

    async def create_using_usbmux(**_kwargs: Any) -> Lockdown:
        return Lockdown()

    transport = MacOSTransport()
    monkeypatch.setattr(
        transport,
        "_load_modules",
        lambda: (UsbMux(), create_using_usbmux, object(), object()),
    )

    devices = asyncio.run(transport.list_devices())

    assert devices[0].name == "Test iPhone"
    assert devices[0].product == "iPhone16,1"


def test_macos_scan_uses_os_trace_card_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class OsTraceService:
        def __init__(self, lockdown: Any) -> None:
            self.lockdown = lockdown

        async def syslog(self) -> Any:
            yield SimpleNamespace(
                filename="/System/Library/PrivateFrameworks/PassKitCore.framework/passd",
                message=(
                    "Resource lookup at file:///var/mobile/Library/Passes/Cards/"
                    "test-card-hash-path-000001.pkpass/zh_cn.lproj/actions.strings"
                ),
            )

    async def create_using_usbmux(**_kwargs: Any) -> object:
        return object()

    transport = MacOSTransport()
    monkeypatch.setattr(
        transport,
        "_load_modules",
        lambda: (object(), create_using_usbmux, object(), OsTraceService),
    )

    observations = asyncio.run(
        transport.scan(
            device=Device(
                udid="test-device-udid",
                name="Test iPhone",
                product="iPhone16,1",
                version="18.7.8",
                build="22H352",
            ),
            duration=None,
            stop_event=None,
        )
    )

    assert [item.card_hash for item in observations] == [
        "test-card-hash-path-000001"
    ]


def test_macos_scan_uses_passkit_image_context_for_image_cache_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OsTraceService:
        def __init__(self, lockdown: Any) -> None:
            self.lockdown = lockdown

        async def syslog(self) -> Any:
            yield SimpleNamespace(
                filename="/Applications/Preferences.app/Preferences",
                image_name=(
                    "/System/Library/PrivateFrameworks/PassKitCore.framework/PassKitCore"
                ),
                message=(
                    "Image in cache, calling completion for "
                    "test-card-hash-cache-000001=:"
                    "0d162029c8c317c18301318360b2919afd6d0b50:"
                    "777-{66, 41.501385041551245}"
                ),
            )

    async def create_using_usbmux(**_kwargs: Any) -> object:
        return object()

    transport = MacOSTransport()
    monkeypatch.setattr(
        transport,
        "_load_modules",
        lambda: (object(), create_using_usbmux, object(), OsTraceService),
    )

    observations = asyncio.run(
        transport.scan(
            device=Device(
                udid="test-device-udid",
                name="Test iPhone",
                product="iPhone16,1",
                version="18.7.8",
                build="22H352",
            ),
            duration=None,
            stop_event=None,
        )
    )

    assert [item.card_hash for item in observations] == [
        "test-card-hash-cache-000001="
    ]


def test_macos_recover_keeps_transaction_on_generic_helper_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RecoveryStore(tmp_path / "recovery")
    transaction = store.begin(
        device_udid="test-device-udid",
        card_hash="AbC123xyz789456QrsTu",
        asset="cardBackgroundCombined@2x.png",
        output_path=tmp_path / "card.png",
        source_path="/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass",
        generated={"source": "source", "link": "link", "recovered": "recovered"},
    )
    store.write_books_snapshot(transaction.id, files={}, directories={})
    store.transition(transaction.id, RecoveryState.STAGED)
    store.transition(transaction.id, RecoveryState.MOVED)
    moved = store.get(transaction.id)
    assert moved is not None
    recovered_name = moved.generated["recovered"]
    selected_device = Device(
        udid="test-device-udid",
        name="Test iPhone",
        product="iPhone16,1",
        version="18.7.8",
        build="22H352",
    )

    class AfcService:
        def __init__(self, lockdown: Any) -> None:
            self.lockdown = lockdown

        async def __aenter__(self) -> AfcService:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def exists(self, path: str) -> bool:
            return path != f"/{recovered_name}"

    async def create_using_usbmux(**_kwargs: Any) -> object:
        return object()

    helper: Any = SimpleNamespace(ensure=lambda: Path("/tmp/airwallet-helper"))
    transport = MacOSTransport(helper=helper)
    monkeypatch.setattr(
        transport,
        "_load_modules",
        lambda: (object(), create_using_usbmux, AfcService, object()),
    )

    async def no_op(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fail_move(*_args: Any, **_kwargs: Any) -> bytes:
        raise OperationError("AirTraffic verify move failed")

    monkeypatch.setattr(transport, "_write_helper_books", no_op)
    monkeypatch.setattr(transport, "_move_target_to_recovered", fail_move)
    monkeypatch.setattr(transport, "_cleanup_generated", no_op)
    monkeypatch.setattr(transport, "_restore_books", no_op)

    with pytest.raises(OperationError, match="verify move failed"):
        asyncio.run(transport.recover(selected_device, moved, store))

    assert store.get(transaction.id) is not None

from __future__ import annotations

import asyncio
import io
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from airwallet_export.catalog import Catalog
from airwallet_export.cli import _wait_for_enter, main
from airwallet_export.models import CardObservation, Device
from airwallet_export.recovery import RecoveryStore
from airwallet_export.transport import Transport

from .fakes import PDF, PNG, FakeTransport


def device() -> Device:
    return Device(
        udid="test-device-udid",
        name="Test iPhone",
        product="iPhone16,1",
        version="18.7.8",
        build="22H352",
        connection="USB",
    )


def populated_catalog(path: Path) -> Catalog:
    catalog = Catalog(path)
    catalog.observe(
        device(),
        [
            CardObservation(
                card_hash="AbC123xyz789456QrsTu",
                label="Travel",
            )
        ],
        "2026-09-20T00:00:00Z",
    )
    catalog.save()
    return Catalog(path).load()


def invoke(
    argv: list[str],
    transport: Transport,
    *,
    catalog_path: Path,
    state_dir: Path,
    stdin: io.StringIO | None = None,
    stderr: io.StringIO | None = None,
) -> tuple[int, Any, str]:
    stdout = io.StringIO()
    error_output = stderr or io.StringIO()
    code = main(
        argv,
        transport=transport,
        catalog=Catalog(catalog_path),
        store=RecoveryStore(state_dir / "recovery"),
        stdin=stdin or io.StringIO(),
        stdout=stdout,
        stderr=error_output,
    )
    output = stdout.getvalue()
    parsed: dict[str, object] | str
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = output
    return code, parsed, error_output.getvalue()


def test_export_requires_all_or_card_selector(tmp_path: Path) -> None:
    code, _output, error = invoke(
        ["export"],
        FakeTransport(devices=[device()]),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 2
    assert "export requires --all or at least one --card" in error


def test_export_json_emits_one_object_and_warning_on_stderr(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)
    transport = FakeTransport(
        devices=[device()],
        assets={
            ("AbC123xyz789456QrsTu", "cardBackgroundCombined@2x.png"): PNG,
            ("AbC123xyz789456QrsTu", "cardBackgroundCombined.pdf"): PDF,
        },
    )

    code, output, error = invoke(
        ["--json", "export", "--all", "--output", str(tmp_path / "exports")],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert isinstance(output, dict)
    assert output["ok"] is True
    assert output["recovery_required"] is False
    assert len(output["exported"]) == 2
    assert len(output["missing"]) == 2
    assert "Data loss is possible" in error
    assert "Exporting card" not in error


def test_export_prints_card_progress_in_text_mode(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)
    transport = FakeTransport(
        devices=[device()],
        assets={("AbC123xyz789456QrsTu", "cardBackgroundCombined@2x.png"): PNG},
    )

    code, output, error = invoke(
        ["export", "--all", "--output", str(tmp_path / "exports")],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert "Exporting card 1/1...\n" in error
    assert "exported\tcardBackgroundCombined@2x.png" in output


def test_no_warning_is_honored(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)
    transport = FakeTransport(
        devices=[device()],
        assets={("AbC123xyz789456QrsTu", "cardBackgroundCombined@2x.png"): PNG},
    )

    code, _output, error = invoke(
        [
            "--json",
            "--no-warning",
            "export",
            "--card",
            "travel-abc123xy",
            "--output",
            str(tmp_path / "exports"),
        ],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert error == ""


def test_cards_json_accepts_global_option_after_command(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)

    code, output, error = invoke(
        ["cards", "--json", "--catalog", str(catalog_path)],
        FakeTransport(),
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert isinstance(output, dict)
    assert output["ok"] is True
    assert output["cards"][0]["card_id"] == "travel-abc123xy"
    assert error == ""


def test_devices_lists_usb_metadata_and_suppresses_warning_for_scripts(tmp_path: Path) -> None:
    code, output, error = invoke(
        ["devices", "--json", "--no-warning"],
        FakeTransport(devices=[device()]),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert isinstance(output, dict)
    assert output["devices"] == [device().to_dict()]
    assert error == ""


def test_scan_updates_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    transport = FakeTransport(
        devices=[device()],
        observations=[CardObservation("AbC123xyz789456QrsTu", "Travel")],
    )

    code, output, _error = invoke(
        ["scan", "--duration", "0", "--json"],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert isinstance(output, dict)
    assert "Settings -> Wallet & Apple Pay" in _error
    assert output["cards"][0]["card_hash"] == "AbC123xyz789456QrsTu"
    assert Catalog(catalog_path).load().cards_for_device(device().udid)[0].label == "Travel"


def test_scan_reports_running_unique_card_count(tmp_path: Path) -> None:
    class RealTimeTransport(FakeTransport):
        def __init__(self, stream: io.StringIO) -> None:
            super().__init__(
                devices=[device()],
                observations=[
                    CardObservation("AbC123xyz789456QrsTu", "Travel"),
                    CardObservation("AbC123xyz789456QrsTu", "Travel"),
                    CardObservation("ZyX987abcdef654321QrsTu"),
                ],
            )
            self.stream = stream

        async def scan(
            self,
            device: Device,
            duration: float | None,
            stop_event: asyncio.Event | None,
            on_observation: Callable[[CardObservation], None] | None = None,
        ) -> list[CardObservation]:
            for observation in self.observations:
                if on_observation is not None:
                    on_observation(observation)
            assert "Detected 1 Card(s) so far." in self.stream.getvalue()
            assert "Detected 2 Card(s) so far." in self.stream.getvalue()
            return list(self.observations)

    catalog_path = tmp_path / "catalog.json"
    error_output = io.StringIO()
    transport = RealTimeTransport(error_output)

    code, _output, error = invoke(
        ["scan", "--duration", "0", "--no-warning"],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
        stderr=error_output,
    )

    assert code == 0
    assert "Detected 1 Card(s) so far." in error
    assert "Detected 2 Card(s) so far." in error
    assert "Detected 3 Card(s) so far." not in error


def test_recovery_error_has_stable_exit_code_and_json_flag(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)
    transport = FakeTransport(
        devices=[device()],
        assets={("AbC123xyz789456QrsTu", "cardBackgroundCombined@3x.png"): PNG},
        failure=("disconnect_after", "cardBackgroundCombined@3x.png"),
    )

    code, output, _error = invoke(
        ["export", "--all", "--json"],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 3
    assert isinstance(output, dict)
    assert output["ok"] is False
    assert output["recovery_required"] is True


def test_invalid_command_returns_usage_exit_code(tmp_path: Path) -> None:
    code, _output, error = invoke(
        ["not-a-command"],
        FakeTransport(),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 2
    assert "invalid choice" in error


def test_invalid_command_with_json_returns_json_error(tmp_path: Path) -> None:
    code, output, _error = invoke(
        ["--json", "not-a-command"],
        FakeTransport(),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 2
    assert output["ok"] is False


def test_ctrl_c_during_scan_saves_observations_already_seen(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    transport = FakeTransport(
        devices=[device()],
        observations=[CardObservation("AbC123xyz789456QrsTu", "Travel")],
        scan_interrupt=True,
    )

    code, output, _error = invoke(
        ["scan", "--json"],
        transport,
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 0
    assert output["ok"] is True
    assert Catalog(catalog_path).load().cards_for_device(device().udid)[0].card_hash == (
        "AbC123xyz789456QrsTu"
    )


def test_doctor_reports_pending_recovery_as_exit_three(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    populated_catalog(catalog_path)
    store = RecoveryStore(tmp_path / "state" / "recovery")
    store.begin(
        device_udid=device().udid,
        card_hash="AbC123xyz789456QrsTu",
        asset="cardBackgroundCombined@3x.png",
        output_path=tmp_path / "card.png",
        source_path="/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass",
        generated={"source": "source", "link": "link", "recovered": "recovered"},
    )

    code, output, error = invoke(
        ["doctor", "--json"],
        FakeTransport(devices=[device()]),
        catalog_path=catalog_path,
        state_dir=tmp_path / "state",
    )

    assert code == 3
    assert output["ok"] is False
    assert output["pending_recovery"][0]["state"] == "planned"
    assert "Data loss is possible" in error


def test_devices_reports_pending_recovery_as_exit_three(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "state" / "recovery")
    store.begin(
        device_udid=device().udid,
        card_hash="AbC123xyz789456QrsTu",
        asset="cardBackgroundCombined@3x.png",
        output_path=tmp_path / "card.png",
        source_path="/var/mobile/Library/Passes/Cards/AbC123xyz789456QrsTu.pkpass",
        generated={"source": "source", "link": "link", "recovered": "recovered"},
    )

    code, output, _error = invoke(
        ["devices", "--json", "--no-warning"],
        FakeTransport(devices=[device()]),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 3
    assert output["ok"] is False
    assert output["recovery_required"] is True


def test_doctor_reports_windows_boundary_without_listing_devices(tmp_path: Path) -> None:
    from airwallet_export.windows import WindowsTransport

    code, output, _error = invoke(
        ["doctor", "--json", "--no-warning"],
        WindowsTransport(),
        catalog_path=tmp_path / "catalog.json",
        state_dir=tmp_path / "state",
    )

    assert code == 4
    assert output["ok"] is False
    assert output["diagnostics"]["experimental"] is True


def test_enter_waiter_uses_loop_reader_and_stops_cleanly() -> None:
    import asyncio

    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, encoding="utf-8")
    stop_event = asyncio.Event()

    async def scenario() -> None:
        task = asyncio.create_task(_wait_for_enter(reader, stop_event))
        await asyncio.sleep(0)
        os.write(write_fd, b"\n")
        await asyncio.wait_for(task, timeout=1)

    try:
        asyncio.run(scenario())
    finally:
        reader.close()
        os.close(write_fd)

    assert stop_event.is_set()

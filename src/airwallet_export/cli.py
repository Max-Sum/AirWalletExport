from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Never, TextIO

from .catalog import Catalog
from .errors import (
    EXIT_OK,
    EXIT_OPERATION_ERROR,
    EXIT_RECOVERY_REQUIRED,
    EXIT_UNSUPPORTED,
    AirWalletError,
    OperationError,
    UsageError,
)
from .export_service import ExportService, recover_pending
from .models import Card, CardObservation, Device
from .recovery import RecoveryStore
from .transport import Transport

WARNING = (
    "WARNING: AirWallet Export moves Wallet resources and uses unsupported Apple "
    "services. Data loss is possible. Back up the iPhone, keep it unlocked and "
    "USB-connected, and run recover before another export after an interruption.\n"
)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise UsageError(message)


def default_catalog_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "AirWallet Export"
            / "catalog.json"
        )
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return root / "AirWallet Export" / "catalog.json"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "airwallet-export" / "catalog.json"


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--catalog", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--state-dir", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--device", default=argparse.SUPPRESS)
    parser.add_argument("--no-warning", action="store_true", default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    global_options = _ArgumentParser(add_help=False)
    _add_global_options(global_options)

    parser = _ArgumentParser(
        prog="airwallet-export",
        description="Export original Apple Wallet card backgrounds from a USB iPhone.",
        parents=[global_options],
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser(
        "doctor",
        parents=[global_options],
        help="check host and device prerequisites",
    )
    subparsers.add_parser("devices", parents=[global_options], help="list USB-connected iPhones")

    scan = subparsers.add_parser("scan", parents=[global_options], help="collect Card Hashes")
    scan.add_argument("--duration", type=float, default=None)

    subparsers.add_parser("cards", parents=[global_options], help="show the local Catalog")

    export = subparsers.add_parser(
        "export",
        parents=[global_options],
        help="export Card Backgrounds",
    )
    selector = export.add_mutually_exclusive_group()
    selector.add_argument("--all", dest="all_cards", action="store_true")
    selector.add_argument("--card", action="append", default=[])
    export.add_argument("--output", type=Path, default=Path("exports"))

    subparsers.add_parser("recover", parents=[global_options], help="complete pending recovery")
    return parser


def build_transport() -> Transport:
    if sys.platform == "darwin":
        from .macos import MacOSTransport

        return MacOSTransport()
    if os.name == "nt":
        from .windows import WindowsTransport

        return WindowsTransport()
    from .linux import LinuxTransport

    return LinuxTransport()


def _write_json(stream: TextIO, value: dict[str, Any]) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    stream.flush()


def _write_error(
    error: AirWalletError,
    *,
    json_output: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if json_output:
        value: dict[str, Any] = {
            "ok": False,
            "error": error.message,
            "recovery_required": error.recovery_required,
        }
        value.update(error.context)
        _write_json(stdout, value)
    else:
        stderr.write(f"error: {error.message}\n")
        stderr.flush()
    return error.exit_code


async def _select_device(
    transport: Transport,
    requested: str | None,
    stdin: TextIO,
) -> Device:
    devices = await transport.list_devices()
    if requested:
        for device in devices:
            if device.udid.casefold() == requested.casefold():
                return device
        raise OperationError(f"requested USB Device is not connected: {requested}")
    if len(devices) == 1:
        return devices[0]
    if not devices:
        raise OperationError("no paired USB iPhone found")
    if not stdin.isatty():
        raise UsageError("multiple USB iPhones found; use --device UDID")

    sys.stderr.write("Available USB iPhones:\n")
    for index, device in enumerate(devices, 1):
        sys.stderr.write(
            f"  [{index}] {device.name} | {device.product} | iOS {device.version} "
            f"({device.build}) | {device.udid}\n"
        )
    while True:
        sys.stderr.write("Select Device: ")
        sys.stderr.flush()
        response = stdin.readline()
        if not response:
            raise UsageError("Device selection cancelled")
        try:
            index = int(response.strip())
        except ValueError:
            index = 0
        if 1 <= index <= len(devices):
            return devices[index - 1]
        sys.stderr.write(f"Enter a number from 1 to {len(devices)}.\n")


def _select_cards(
    catalog: Catalog,
    device_udid: str,
    *,
    all_cards: bool,
    selectors: list[str],
) -> list[Card]:
    available = catalog.cards_for_device(device_udid)
    if all_cards:
        return available
    selected: list[Card] = []
    seen: set[str] = set()
    for selector in selectors:
        matches = [
            card
            for card in available
            if selector.casefold() in {card.card_id.casefold(), card.card_hash.casefold()}
        ]
        if not matches:
            raise OperationError(f"Card selector not found for this Device: {selector}")
        for card in matches:
            if card.card_hash not in seen:
                selected.append(card)
                seen.add(card.card_hash)
    return selected


async def _run_command(
    arguments: argparse.Namespace,
    *,
    transport: Transport,
    catalog: Catalog,
    store: RecoveryStore,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    warning_enabled = not bool(arguments.no_warning)

    if arguments.command == "doctor":
        if warning_enabled:
            stderr.write(WARNING)
        diagnostics = transport.diagnostics()
        if not diagnostics.get("supported"):
            unsupported_result = {
                "ok": False,
                "checks": {"supported_platform": False},
                "diagnostics": diagnostics,
                "pending_recovery": [
                    transaction.to_dict() for transaction in store.pending()
                ],
            }
            if arguments.json:
                _write_json(stdout, unsupported_result)
            else:
                stdout.write(f"Transport: {diagnostics}\n")
            return EXIT_UNSUPPORTED
        catalog_error: str | None = None
        catalog_count = 0
        try:
            catalog.load()
            catalog_count = len(catalog.all_cards())
        except AirWalletError as error:
            catalog_error = error.message
        devices = await transport.list_devices()
        pending = store.pending()
        selected_device: Device | None = None
        if arguments.device:
            selected_device = next(
                (
                    item
                    for item in devices
                    if item.udid.casefold() == arguments.device.casefold()
                ),
                None,
            )
        elif len(devices) == 1:
            selected_device = devices[0]
        probe_result = None
        probe_error: str | None = None
        if selected_device is not None:
            try:
                probe_result = await transport.probe(selected_device)
            except AirWalletError as error:
                probe_error = error.message
        host_diagnostics = getattr(transport, "host_diagnostics", None)
        host_error: str | None = None
        if callable(host_diagnostics):
            try:
                host_result = await host_diagnostics()
            except AirWalletError as error:
                host_result = {}
                host_error = error.message
        else:
            host_result = {}
        diagnostics.update(host_result)
        signature_valid = diagnostics.get("signature_valid", True) is not False
        checks = {
            "catalog": catalog_error is None,
            "usb_device": selected_device is not None,
            "probe": bool(probe_result and probe_result.ok) and probe_error is None,
            "helper": signature_valid and host_error is None,
            "no_pending_recovery": not pending,
        }
        ok = all(checks.values())
        result: dict[str, Any] = {
            "ok": ok,
            "checks": checks,
            "diagnostics": diagnostics,
            "usb_devices": [device.to_dict() for device in devices],
            "pending_recovery": [transaction.to_dict() for transaction in pending],
            "catalog_cards": catalog_count,
        }
        if selected_device is not None:
            result["device"] = selected_device.to_dict()
        if probe_result is not None:
            result["probe"] = probe_result.to_dict()
        if catalog_error or probe_error or host_error:
            result["errors"] = {
                key: value
                for key, value in {
                    "catalog": catalog_error,
                    "probe": probe_error,
                    "host": host_error,
                }.items()
                if value
            }
        if arguments.json:
            _write_json(stdout, result)
        else:
            stdout.write(f"Transport: {diagnostics}\n")
            stdout.write(f"USB iPhones: {len(devices)}\n")
            stdout.write(f"Pending Recovery Transactions: {len(pending)}\n")
        if pending:
            return EXIT_RECOVERY_REQUIRED
        return EXIT_OK if ok else EXIT_OPERATION_ERROR

    if arguments.command == "devices":
        if warning_enabled:
            stderr.write(WARNING)
        devices = await transport.list_devices()
        pending = store.pending()
        result = {
            "ok": not pending,
            "devices": [item.to_dict() for item in devices],
            "pending_recovery": [item.to_dict() for item in pending],
            "recovery_required": bool(pending),
        }
        if arguments.json:
            _write_json(stdout, result)
        else:
            for device in devices:
                stdout.write(
                    f"{device.name}\t{device.product}\t{device.version}\t{device.build}\t"
                    f"{device.udid}\t{device.connection}\n"
                )
        return EXIT_RECOVERY_REQUIRED if pending else EXIT_OK

    if arguments.command == "cards":
        catalog.load()
        if arguments.device:
            selected_device = catalog.device(arguments.device)
            cards = catalog.cards_for_device(arguments.device)
            devices = [selected_device] if selected_device else []
        else:
            cards = [card for _device, card in catalog.all_cards()]
            devices = catalog.devices()
        if arguments.json:
            _write_json(
                stdout,
                {
                    "ok": True,
                    "devices": [item.to_dict() for item in devices],
                    "cards": [item.to_dict() for item in cards],
                },
            )
        else:
            for card in cards:
                label = card.label or "(unlabeled)"
                stdout.write(f"{card.card_id}\t{label}\t{card.card_hash}\n")
        return EXIT_OK

    if warning_enabled:
        stderr.write(WARNING)
    device = await _select_device(transport, arguments.device, stdin)

    if arguments.command == "scan":
        if arguments.duration is not None and arguments.duration < 0:
            raise UsageError("--duration must be zero or greater")
        await recover_pending(transport, store, device)
        stderr.write(
            "Open Settings -> Wallet & Apple Pay on the iPhone to reveal Card Hashes.\n"
        )
        stderr.flush()
        stop_event = asyncio.Event()
        enter_task: asyncio.Task[None] | None = None
        if arguments.duration is None and stdin.isatty():
            enter_task = asyncio.create_task(_wait_for_enter(stdin, stop_event))
        loop = asyncio.get_running_loop()
        signal_handler_installed = False
        try:
            loop.add_signal_handler(signal.SIGINT, stop_event.set)
            signal_handler_installed = True
        except (NotImplementedError, RuntimeError):
            pass
        collected: dict[str, CardObservation] = {}

        def collect(observation: CardObservation) -> None:
            is_new = observation.card_hash not in collected
            collected[observation.card_hash] = observation
            if is_new:
                stderr.write(f"Detected {len(collected)} Card(s) so far.\n")
                stderr.flush()

        try:
            returned = await transport.scan(
                device,
                arguments.duration,
                stop_event,
                on_observation=collect,
            )
        except KeyboardInterrupt:
            returned = []
        finally:
            if enter_task is not None:
                enter_task.cancel()
            if signal_handler_installed:
                loop.remove_signal_handler(signal.SIGINT)
        for observation in returned:
            collect(observation)
        observations = list(collected.values())
        catalog.load()
        catalog.observe(device, observations, _timestamp())
        catalog.save()
        cards = catalog.cards_for_device(device.udid)
        if arguments.json:
            _write_json(
                stdout,
                {
                    "ok": True,
                    "device": device.to_dict(),
                    "cards": [card.to_dict() for card in cards],
                },
            )
        else:
            stdout.write(f"Observed {len(observations)} Card observation(s).\n")
            for card in cards:
                stdout.write(f"{card.card_id}\t{card.label or '(unlabeled)'}\t{card.card_hash}\n")
        return EXIT_OK

    if arguments.command == "export":
        if not arguments.all_cards and not arguments.card:
            raise UsageError("export requires --all or at least one --card")
        catalog.load()
        cards = _select_cards(
            catalog,
            device.udid,
            all_cards=bool(arguments.all_cards),
            selectors=list(arguments.card),
        )
        service = ExportService(transport, store)

        def report_progress(current: int, total: int) -> None:
            stderr.write(f"Exporting card {current}/{total}...\n")

        summary = await service.export(
            device,
            cards,
            arguments.output,
            on_progress=None if arguments.json else report_progress,
        )
        if arguments.json:
            _write_json(stdout, summary.to_dict())
        else:
            stdout.write(f"Device: {device.name} ({device.udid})\n")
            stdout.write(f"Output: {summary.output}\n")
            for item in summary.exported:
                stdout.write(f"exported\t{item['asset']}\t{item['path']}\n")
            for item in summary.missing:
                stdout.write(f"missing\t{item['asset']}\n")
        return EXIT_OK

    if arguments.command == "recover":
        count = await recover_pending(transport, store, device)
        if arguments.json:
            _write_json(
                stdout,
                {
                    "ok": True,
                    "device": device.to_dict(),
                    "recovered": count,
                    "recovery_required": False,
                },
            )
        else:
            stdout.write(f"Recovered {count} transaction(s).\n")
        return EXIT_OK

    raise UsageError("a command is required")


async def _wait_for_enter(stdin: TextIO, stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    completed = asyncio.Event()
    descriptor = stdin.fileno()

    def on_readable() -> None:
        stdin.readline()
        stop_event.set()
        completed.set()

    loop.add_reader(descriptor, on_readable)
    try:
        await completed.wait()
    finally:
        loop.remove_reader(descriptor)


def _timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    catalog: Catalog | None = None,
    store: RecoveryStore | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = build_parser()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    json_output = "--json" in raw_argv
    arguments: argparse.Namespace | None = None
    try:
        arguments = parser.parse_args(raw_argv)
        for name, default in (
            ("json", False),
            ("catalog", None),
            ("state_dir", None),
            ("device", None),
            ("no_warning", False),
        ):
            if not hasattr(arguments, name):
                setattr(arguments, name, default)
        json_output = bool(arguments.json)
        if arguments.command is None:
            raise UsageError("a command is required")
        selected_transport = transport or build_transport()
        selected_catalog = catalog or Catalog(arguments.catalog or default_catalog_path())
        state_dir = arguments.state_dir or Path.cwd() / ".airwallet-export"
        selected_store = store or RecoveryStore(Path(state_dir) / "recovery")
        return asyncio.run(
            _run_command(
                arguments,
                transport=selected_transport,
                catalog=selected_catalog,
                store=selected_store,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        )
    except SystemExit as exit_signal:
        return int(exit_signal.code or 0)
    except AirWalletError as error:
        return _write_error(
            error,
            json_output=json_output,
            stdout=stdout,
            stderr=stderr,
        )
    except KeyboardInterrupt:
        interrupted_error = OperationError("interrupted")
        return _write_error(
            interrupted_error,
            json_output=json_output,
            stdout=stdout,
            stderr=stderr,
        )

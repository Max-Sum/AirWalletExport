from __future__ import annotations

import asyncio
import hashlib
import json
import plistlib
import posixpath
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .airlift import (
    AIRLOCK_ROOT,
    build_airlock_archive,
    build_books_plist,
    helper_discard_path,
    helper_payload_identifiers,
    target_identifier,
)
from .atomic import atomic_write_new_bytes
from .discovery import parse_card_observation
from .errors import (
    MissingResource,
    OperationError,
    RecoveryRequiredError,
    UnsupportedError,
)
from .helper import MacOSHelperBuilder
from .models import CapabilityResult, CardObservation, Device, ExportArtifact
from .recovery import RecoveryState, RecoveryStore, RecoveryTransaction
from .validation import validate_background

ZIP_SERVICE = "com.apple.streaming_zip_conduit"
TRACKED_BOOK_FILES = (
    "Books/Books.plist",
    "Books/Sync/Books.plist",
    "Books/Sync/Upload.plist",
    "Books/Sync/Database/OutstandingAssets_4.sqlite",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-shm",
    "Books/Sync/Database/OutstandingAssets_4.sqlite-wal",
)
TRACKED_BOOK_DIRECTORIES = ("Books", "Books/Sync", "Books/Sync/Database")


class _CardBackgroundAbsent(OperationError):
    pass


class MacOSTransport:
    def __init__(self, *, helper: MacOSHelperBuilder | None = None) -> None:
        self.helper = helper or MacOSHelperBuilder()

    def _load_modules(self) -> tuple[Any, Any, Any, Any]:
        try:
            from pymobiledevice3 import usbmux
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService
            from pymobiledevice3.services.os_trace import OsTraceService
        except ImportError as error:
            raise UnsupportedError(f"pymobiledevice3 is unavailable: {error}") from error
        return usbmux, create_using_usbmux, AfcService, OsTraceService

    async def list_devices(self) -> list[Device]:
        usbmux, create_using_usbmux, _afc, _os_trace = self._load_modules()
        try:
            devices = await usbmux.select_devices_by_connection_type("USB")
        except Exception as error:
            raise OperationError(f"could not enumerate USB iPhones: {error}") from error

        result: list[Device] = []
        for mux_device in devices:
            try:
                lockdown = await create_using_usbmux(
                    serial=mux_device.serial,
                    connection_type="USB",
                    autopair=False,
                )
                values = await lockdown.get_value()
                product = str(values.get("ProductType") or "")
                if not product.startswith("iPhone"):
                    continue
                result.append(
                    Device(
                        udid=str(values.get("UniqueDeviceID") or mux_device.serial),
                        name=str(values.get("DeviceName") or product),
                        product=product,
                        version=str(values.get("ProductVersion") or "unknown"),
                        build=str(values.get("BuildVersion") or "unknown"),
                        connection="USB",
                    )
                )
            except Exception:
                continue
        return sorted(result, key=lambda item: (item.name.casefold(), item.udid))

    async def probe(self, device: Device) -> CapabilityResult:
        _usbmux, create_using_usbmux, AfcService, _os_trace = self._load_modules()
        checks: dict[str, bool] = {}
        try:
            helper_path = await asyncio.to_thread(self.helper.ensure)
            checks["helper"] = helper_path.is_file()
        except Exception as error:
            return CapabilityResult(ok=False, checks={"helper": False}, detail=str(error))

        try:
            lockdown = await create_using_usbmux(
                serial=device.udid,
                connection_type="USB",
                autopair=False,
            )
            async with AfcService(lockdown) as afc:
                checks["afc"] = bool(await afc.exists("/"))
            async with await lockdown.start_lockdown_service(ZIP_SERVICE):
                checks["airtraffic_service"] = True
        except Exception as error:
            return CapabilityResult(ok=False, checks=checks, detail=str(error))
        return CapabilityResult(ok=all(checks.values()), checks=checks)

    async def scan(
        self,
        device: Device,
        duration: float | None,
        stop_event: asyncio.Event | None,
        on_observation: Callable[[CardObservation], None] | None = None,
    ) -> list[CardObservation]:
        if duration is not None and duration <= 0:
            return []
        _usbmux, create_using_usbmux, _afc, OsTraceService = self._load_modules()
        lockdown = await create_using_usbmux(
            serial=device.udid,
            connection_type="USB",
            autopair=False,
        )
        observations: dict[str, CardObservation] = {}
        deadline = None if duration is None else asyncio.get_running_loop().time() + duration
        iterator = OsTraceService(lockdown).syslog().__aiter__()
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                    break
                try:
                    entry = await asyncio.wait_for(anext(iterator), timeout=0.25)
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                label = getattr(entry, "label", None)
                image_name = getattr(entry, "image_name", "")
                subsystem = getattr(label, "subsystem", "") if label is not None else ""
                category = getattr(label, "category", "") if label is not None else ""
                line = f"{entry.filename} {image_name} {subsystem} {category} {entry.message}"
                observation = parse_card_observation(line)
                if observation is not None:
                    observations[observation.card_hash] = observation
                    if on_observation is not None:
                        on_observation(observation)
        finally:
            aclose = getattr(iterator, "aclose", None)
            if callable(aclose):
                await aclose()
        return list(observations.values())

    async def export_background(
        self,
        device: Device,
        card_hash: str,
        asset: str,
        output_path: Path,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> ExportArtifact:
        _usbmux, create_using_usbmux, AfcService, _os_trace = self._load_modules()
        helper_path = await asyncio.to_thread(self.helper.ensure)
        lockdown = await create_using_usbmux(
            serial=device.udid,
            connection_type="USB",
            autopair=False,
        )
        generated = transaction.generated
        source = generated.get("source", "")
        link = generated.get("link", "")
        recovered = generated.get("recovered", "")
        if not source or not link or not recovered:
            raise OperationError("Recovery Transaction is missing generated Airlift identifiers")

        source_directory = transaction.source_path
        source_path = posixpath.join(source_directory, asset)
        link_identifier = f"../../{source}/p0/p1/p2/link"
        source_identifier = target_identifier(source_path)
        recovered_identifier = posixpath.relpath(
            f"/var/mobile/Media/{recovered}", AIRLOCK_ROOT
        )
        moved = False
        books_snapshot = None

        async with AfcService(lockdown) as afc:
            try:
                books_snapshot = await self._snapshot_books(afc)
                store.write_books_snapshot(
                    transaction.id,
                    files=books_snapshot.files,
                    directories=books_snapshot.directories,
                )
                archive = build_airlock_archive(source_directory)
                await self._send_archive(lockdown, source, archive)
                await self._write_helper_books(
                    afc,
                    source=source,
                    source_identifier=source_identifier,
                    recovered_identifier=recovered_identifier,
                )
                store.transition(transaction.id, RecoveryState.STAGED)
                store.transition(transaction.id, RecoveryState.MOVED)
                moved = True

                try:
                    move = await self._run_helper(
                        helper_path,
                        device.udid,
                        (
                            (link_identifier, link),
                            (source_identifier, recovered),
                        ),
                    )
                except Exception as error:
                    raise RecoveryRequiredError(
                        f"AirTraffic move outcome is uncertain: {error}",
                        transaction_id=transaction.id,
                    ) from error
                if move.get("error") == "expected assets absent from manifest":
                    moved = False
                    await self._cleanup_no_move(
                        afc,
                        store,
                        transaction,
                        source=source,
                        link=link,
                        recovered=recovered,
                        snapshot=books_snapshot,
                    )
                    raise MissingResource(asset)
                if not move.get("ok"):
                    raise OperationError(str(move.get("error") or "AirTraffic move failed"))

                try:
                    data = await self._read_recovered(afc, recovered, attempts=10)
                except OperationError:
                    moved = False
                    await self._cleanup_no_move(
                        afc,
                        store,
                        transaction,
                        source=source,
                        link=link,
                        recovered=recovered,
                        snapshot=books_snapshot,
                    )
                    raise MissingResource(asset) from None
                validate_background(asset, data)
                atomic_write_new_bytes(output_path, data)
                store.transition(transaction.id, RecoveryState.EXPORTED)

                await self._restore_and_verify(
                    afc,
                    helper_path,
                    device.udid,
                    expected=data,
                    source=source,
                    source_identifier=source_identifier,
                    recovered_identifier=recovered_identifier,
                    link=link,
                    asset=asset,
                    recovered=recovered,
                )

                store.transition(transaction.id, RecoveryState.RESTORED)
                await self._cleanup_generated(
                    afc,
                    source=source,
                    link=link,
                    recovered=recovered,
                )
                await self._restore_books(afc, books_snapshot)
                store.transition(transaction.id, RecoveryState.COMPLETE)
                return ExportArtifact(
                    card_id=card_hash,
                    card_hash=card_hash,
                    asset=asset,
                    path=str(output_path.resolve()),
                    bytes_written=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            except MissingResource:
                raise
            except RecoveryRequiredError:
                raise
            except Exception as error:
                if moved:
                    try:
                        await self._restore_after_move(
                            afc,
                            helper_path,
                            device.udid,
                            transaction,
                            source=source,
                            link=link,
                            recovered=recovered,
                            store=store,
                            snapshot=books_snapshot,
                        )
                    except Exception as recovery_error:
                        raise RecoveryRequiredError(
                            f"Card Background recovery failed: {recovery_error}",
                            transaction_id=transaction.id,
                        ) from recovery_error
                    if isinstance(error, OperationError):
                        raise
                    raise OperationError(str(error)) from error
                try:
                    if books_snapshot is not None:
                        await self._cleanup_generated(
                            afc,
                            source=source,
                            link=link,
                            recovered=recovered,
                        )
                        await self._restore_books(afc, books_snapshot)
                    store.remove(transaction.id)
                except Exception as cleanup_error:
                    raise RecoveryRequiredError(
                        f"cleanup before move failed: {cleanup_error}",
                        transaction_id=transaction.id,
                    ) from cleanup_error
                if isinstance(error, OperationError):
                    raise
                if books_snapshot is None:
                    raise OperationError(
                        "Device disconnected before the Card Background move"
                    ) from error
                raise OperationError(str(error)) from error

    async def recover(
        self,
        device: Device,
        transaction: RecoveryTransaction,
        store: RecoveryStore,
    ) -> bool:
        _usbmux, create_using_usbmux, AfcService, _os_trace = self._load_modules()
        helper_path = await asyncio.to_thread(self.helper.ensure)
        lockdown = await create_using_usbmux(
            serial=device.udid,
            connection_type="USB",
            autopair=False,
        )
        source = transaction.generated.get("source", "")
        link = transaction.generated.get("link", "")
        recovered = transaction.generated.get("recovered", "")
        if not source or not link or not recovered:
            raise RecoveryRequiredError(
                "Recovery Transaction is missing generated Airlift identifiers",
                transaction_id=transaction.id,
            )

        try:
            snapshot = store.load_books_snapshot(transaction.id)
        except OperationError:
            if transaction.state is RecoveryState.PLANNED:
                store.remove(transaction.id)
                return True
            raise

        async with AfcService(lockdown) as afc:
            if transaction.state in (RecoveryState.PLANNED, RecoveryState.STAGED):
                await self._cleanup_generated(
                    afc,
                    source=source,
                    link=link,
                    recovered=recovered,
                )
                await self._restore_books(afc, snapshot)
                store.remove(transaction.id)
                return True

            if transaction.state is RecoveryState.RESTORED:
                output = Path(transaction.output_path)
                if output.is_file():
                    try:
                        validate_background(transaction.asset, output.read_bytes())
                    except OperationError as error:
                        raise RecoveryRequiredError(
                            f"host output is invalid during recovery: {error}",
                            transaction_id=transaction.id,
                        ) from error
                await self._cleanup_generated(
                    afc,
                    source=source,
                    link=link,
                    recovered=recovered,
                )
                await self._restore_books(afc, snapshot)
                store.transition(transaction.id, RecoveryState.COMPLETE)
                return True

            link_exists = bool(await afc.exists(f"/{link}"))
            if transaction.state in (
                RecoveryState.MOVED,
                RecoveryState.EXPORTED,
            ) and not link_exists:
                staged_link = f"/{source}/p0/p1/p2/link"
                if not await afc.exists(staged_link):
                    raise RecoveryRequiredError(
                        "could not locate the staged Airlift link for recovery",
                        transaction_id=transaction.id,
                    )
                link_identifier = f"../../{source}/p0/p1/p2/link"
                result = await self._run_helper(
                    helper_path,
                    device.udid,
                    ((link_identifier, link),),
                )
                if not result.get("ok") or not await self._wait_for_path(afc, link):
                    raise RecoveryRequiredError(
                        str(result.get("error") or "could not restore the Airlift link"),
                        transaction_id=transaction.id,
                    )

            asset = transaction.asset
            source_identifier = target_identifier(posixpath.join(transaction.source_path, asset))
            recovered_identifier = posixpath.relpath(
                f"/var/mobile/Media/{recovered}", AIRLOCK_ROOT
            )
            await self._write_helper_books(
                afc,
                source=source,
                source_identifier=source_identifier,
                recovered_identifier=recovered_identifier,
            )
            if await afc.exists(f"/{recovered}"):
                recovered_data = cast(
                    bytes,
                    await afc.get_file_contents(f"/{recovered}"),
                )
                validate_background(asset, recovered_data)
            else:
                try:
                    recovered_data = await self._move_target_to_recovered(
                        afc,
                        helper_path,
                        device.udid,
                        source=source,
                        source_identifier=source_identifier,
                        recovered=recovered,
                    )
                except _CardBackgroundAbsent:
                    await self._cleanup_generated(
                        afc,
                        source=source,
                        link=link,
                        recovered=recovered,
                    )
                    await self._restore_books(afc, snapshot)
                    store.remove(transaction.id)
                    return True
                validate_background(asset, recovered_data)

            output = Path(transaction.output_path)
            if output.is_file() and hashlib.sha256(output.read_bytes()).digest() != hashlib.sha256(
                recovered_data
            ).digest():
                raise RecoveryRequiredError(
                    "recovered Card Background bytes differ from the host output",
                    transaction_id=transaction.id,
                )
            await self._restore_and_verify(
                afc,
                helper_path,
                device.udid,
                expected=recovered_data,
                source=source,
                source_identifier=source_identifier,
                recovered_identifier=recovered_identifier,
                link=link,
                asset=asset,
                recovered=recovered,
            )
            store.transition(transaction.id, RecoveryState.RESTORED)
            await self._cleanup_generated(
                afc,
                source=source,
                link=link,
                recovered=recovered,
            )
            await self._restore_books(afc, snapshot)
            store.transition(transaction.id, RecoveryState.COMPLETE)
            return True

    async def _snapshot_books(self, afc: Any) -> Any:
        from .recovery import BooksSnapshot

        files: dict[str, bytes | None] = {}
        for path in TRACKED_BOOK_FILES:
            full_path = f"/{path}"
            files[path] = (
                await afc.get_file_contents(full_path)
                if await afc.exists(full_path)
                else None
            )
        directories = {
            path: bool(await afc.exists(f"/{path}"))
            for path in TRACKED_BOOK_DIRECTORIES
        }
        return BooksSnapshot(files=files, directories=directories)

    async def _restore_books(self, afc: Any, snapshot: Any) -> None:
        for path, data in snapshot.files.items():
            full_path = f"/{path}"
            if data is None:
                await afc.rm_single(full_path, force=True)
                continue
            await afc.makedirs(f"/{posixpath.dirname(path)}")
            await afc.set_file_contents(full_path, data)
        for path, existed in reversed(tuple(snapshot.directories.items())):
            if not existed:
                await afc.rm(f"/{path}", force=True)
        for path, expected in snapshot.files.items():
            if expected is None:
                if await afc.exists(f"/{path}"):
                    raise OperationError(f"Books path was not removed: {path}")
                continue
            actual = await afc.get_file_contents(f"/{path}")
            if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
                raise OperationError(f"Books state verification failed: {path}")

    async def _send_archive(self, lockdown: Any, media_subdir: str, archive: bytes) -> None:
        async with await lockdown.start_lockdown_service(ZIP_SERVICE) as service:
            await service.send_plist(
                {"MediaSubdir": media_subdir},
                fmt=plistlib.FMT_BINARY,
            )
            await service.sendall(archive)
            response = await service.recv_plist()
        if response.get("Error"):
            raise OperationError(f"streaming zip staging failed: {response['Error']}")

    async def _run_helper(
        self,
        helper_path: Path,
        udid: str,
        pairs: tuple[tuple[str, str], ...],
    ) -> dict[str, Any]:
        command = [str(helper_path), udid]
        for source, destination in pairs:
            command.extend((source, destination))
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise OperationError("AirTraffic helper timed out") from error
        result: dict[str, Any] | None = None
        for line in reversed(stdout.decode(errors="replace").splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result = value
                break
        if result is None:
            detail = stderr.decode(errors="replace").strip()
            raise OperationError(
                f"AirTraffic helper returned no JSON result (exit {process.returncode}): {detail}"
            )
        result["exitCode"] = process.returncode
        return result

    async def _read_recovered(
        self,
        afc: Any,
        recovered: str,
        *,
        attempts: int = 50,
    ) -> bytes:
        for _ in range(attempts):
            if await afc.exists(f"/{recovered}"):
                return cast(bytes, await afc.get_file_contents(f"/{recovered}"))
            await asyncio.sleep(0.1)
        raise OperationError("AirTraffic did not create the recovered Card Background path")

    async def _wait_for_absent(self, afc: Any, path: str) -> bool:
        for _ in range(50):
            if not await afc.exists(f"/{path}"):
                return True
            await asyncio.sleep(0.1)
        return False

    async def _restore_once(
        self,
        afc: Any,
        helper_path: Path,
        udid: str,
        *,
        source: str,
        recovered_identifier: str,
        link: str,
        asset: str,
        recovered: str,
    ) -> None:
        result = await self._run_helper_with_available_payload(
            afc,
            helper_path,
            udid,
            source=source,
            primary=(recovered_identifier, posixpath.join(link, asset)),
        )
        if result.get("error") == "expected assets absent from manifest":
            raise OperationError("AirTraffic could not find the recovered Card Background")
        if not result.get("ok"):
            raise OperationError(str(result.get("error") or "AirTraffic restore failed"))
        if not await self._wait_for_absent(afc, recovered):
            raise OperationError("AirTraffic did not move the recovered Card Background")

    async def _move_target_to_recovered(
        self,
        afc: Any,
        helper_path: Path,
        udid: str,
        *,
        source: str,
        source_identifier: str,
        recovered: str,
    ) -> bytes:
        result = await self._run_helper_with_available_payload(
            afc,
            helper_path,
            udid,
            source=source,
            primary=(source_identifier, recovered),
        )
        if result.get("error") == "expected assets absent from manifest":
            raise _CardBackgroundAbsent("the Card Background is absent from its original path")
        if not result.get("ok"):
            raise OperationError(str(result.get("error") or "AirTraffic verify move failed"))
        return await self._read_recovered(afc, recovered)

    async def _restore_and_verify(
        self,
        afc: Any,
        helper_path: Path,
        udid: str,
        *,
        expected: bytes,
        source: str,
        source_identifier: str,
        recovered_identifier: str,
        link: str,
        asset: str,
        recovered: str,
    ) -> None:
        await self._restore_once(
            afc,
            helper_path,
            udid,
            source=source,
            recovered_identifier=recovered_identifier,
            link=link,
            asset=asset,
            recovered=recovered,
        )
        verified = await self._move_target_to_recovered(
            afc,
            helper_path,
            udid,
            source=source,
            source_identifier=source_identifier,
            recovered=recovered,
        )
        if hashlib.sha256(verified).digest() != hashlib.sha256(expected).digest():
            raise OperationError("restored Card Background bytes differ from expected bytes")
        await self._restore_once(
            afc,
            helper_path,
            udid,
            source=source,
            recovered_identifier=recovered_identifier,
            link=link,
            asset=asset,
            recovered=recovered,
        )

    async def _wait_for_path(self, afc: Any, path: str) -> bool:
        for _ in range(50):
            if await afc.exists(f"/{path}"):
                return True
            await asyncio.sleep(0.1)
        return False

    async def _write_helper_books(
        self,
        afc: Any,
        *,
        source: str,
        source_identifier: str,
        recovered_identifier: str,
    ) -> None:
        link_identifier = f"../../{source}/p0/p1/p2/link"
        payload_identifiers = helper_payload_identifiers(source)
        await afc.makedirs(f"/{source}")
        for index in range(len(payload_identifiers)):
            await afc.set_file_contents(f"/{source}/payload-{index}", b"")
        await afc.makedirs("/Books/Sync")
        await afc.set_file_contents(
            "/Books/Sync/Books.plist",
            build_books_plist(
                [
                    link_identifier,
                    source_identifier,
                    recovered_identifier,
                    *payload_identifiers,
                ]
            ),
        )

    async def _run_helper_with_available_payload(
        self,
        afc: Any,
        helper_path: Path,
        udid: str,
        *,
        source: str,
        primary: tuple[str, str],
    ) -> dict[str, Any]:
        for index, payload_identifier in enumerate(helper_payload_identifiers(source)):
            if not await afc.exists(f"/{source}/payload-{index}"):
                continue
            return await self._run_helper(
                helper_path,
                udid,
                (primary, (payload_identifier, helper_discard_path(source, index))),
            )
        raise OperationError("no staged helper payload remains for recovery")

    async def _cleanup_no_move(
        self,
        afc: Any,
        store: RecoveryStore,
        transaction: RecoveryTransaction,
        *,
        source: str,
        link: str,
        recovered: str,
        snapshot: Any,
    ) -> None:
        await self._cleanup_generated(
            afc,
            source=source,
            link=link,
            recovered=recovered,
        )
        await self._restore_books(afc, snapshot)
        store.remove(transaction.id)

    async def _restore_after_move(
        self,
        afc: Any,
        helper_path: Path,
        udid: str,
        transaction: RecoveryTransaction,
        *,
        source: str,
        link: str,
        recovered: str,
        store: RecoveryStore,
        snapshot: Any,
    ) -> None:
        asset = transaction.asset
        source_identifier = target_identifier(posixpath.join(transaction.source_path, asset))
        recovered_identifier = posixpath.relpath(
            f"/var/mobile/Media/{recovered}", AIRLOCK_ROOT
        )
        await self._write_helper_books(
            afc,
            source=source,
            source_identifier=source_identifier,
            recovered_identifier=recovered_identifier,
        )
        if await afc.exists(f"/{recovered}"):
            recovered_data = cast(
                bytes,
                await afc.get_file_contents(f"/{recovered}"),
            )
            validate_background(asset, recovered_data)
        else:
            try:
                recovered_data = await self._move_target_to_recovered(
                    afc,
                    helper_path,
                    udid,
                    source=source,
                    source_identifier=source_identifier,
                    recovered=recovered,
                )
            except _CardBackgroundAbsent:
                await self._cleanup_generated(
                    afc,
                    source=source,
                    link=link,
                    recovered=recovered,
                )
                await self._restore_books(afc, snapshot)
                store.remove(transaction.id)
                return
            validate_background(asset, recovered_data)

        output = Path(transaction.output_path)
        if output.is_file() and hashlib.sha256(output.read_bytes()).digest() != hashlib.sha256(
            recovered_data
        ).digest():
            raise OperationError("restored Card Background bytes differ from the host output")
        await self._restore_and_verify(
            afc,
            helper_path,
            udid,
            expected=recovered_data,
            source=source,
            source_identifier=source_identifier,
            recovered_identifier=recovered_identifier,
            link=link,
            asset=asset,
            recovered=recovered,
        )
        current = store.get(transaction.id)
        if current is not None and current.state in (
            RecoveryState.MOVED,
            RecoveryState.EXPORTED,
        ):
            store.transition(transaction.id, RecoveryState.RESTORED)
        await self._cleanup_generated(
            afc,
            source=source,
            link=link,
            recovered=recovered,
        )
        await self._restore_books(afc, snapshot)
        store.transition(transaction.id, RecoveryState.COMPLETE)

    async def _cleanup_generated(
        self,
        afc: Any,
        *,
        source: str,
        link: str,
        recovered: str,
    ) -> None:
        for name in (recovered, link):
            await afc.rm_single(f"/{name}", force=True)
        for index in range(len(helper_payload_identifiers(source))):
            await afc.rm_single(f"/{helper_discard_path(source, index)}", force=True)
        await afc.rm(f"/{source}", force=True)

    def diagnostics(self) -> dict[str, object]:
        result = self.helper.diagnostics()
        result["transport"] = "macos"
        return result

    async def host_diagnostics(self) -> dict[str, object]:
        helper_path = await asyncio.to_thread(self.helper.ensure)
        process = await asyncio.create_subprocess_exec(
            "lipo",
            "-archs",
            str(helper_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await process.communicate()
        return {
            "helper": str(helper_path),
            "architecture": stdout.decode().strip() if process.returncode == 0 else "unknown",
            "signature_valid": await asyncio.to_thread(self.helper.verify_signature),
        }

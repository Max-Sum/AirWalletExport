# Implementation Plan

> Status: implementation complete through host verification. Real-device acceptance and Windows research remain pending.

## Phase 0: Documentation

Completed deliverables:

- Project glossary in `CONTEXT.md`.
- Architecture decisions in `docs/adr/`.
- English README with a prominent data-loss warning.
- Chinese tutorial with the planned workflow and recovery model.
- Architecture, CLI, compatibility, security, and implementation documents.

Exit criteria:

- The scope is limited to Apple Pay Card Backgrounds.
- The move-read-restore model is explicit.
- Windows and Linux status is accurate.
- No implementation file is presented as working before it is tested.

## Phase 1: Minimal Python Package

Implemented:

- `pyproject.toml` with the `airwallet-export` console script.
- Package entry points for `airwallet-export` and `python -m airwallet_export`.
- Standard-library argument parsing.
- Error types and exit codes.
- Atomic output helpers.

Exit criteria:

- `airwallet-export --help` works.
- Invalid command and selector cases return usage exit code `2`.
- Unit tests cover command parsing and output naming.

## Phase 2: Catalog and Scan

Implemented:

- OS-specific Catalog path.
- USB device discovery through `pymobiledevice3`.
- Syslog scanning for Card Hashes.
- Optional label extraction.
- Atomic Catalog writes.
- `devices`, `scan`, and `cards` commands.

Exit criteria:

- Unit tests cover parser inputs, duplicate hashes, labels, and Catalog round trips.
- A real USB iPhone can be discovered. This remains part of the manual acceptance run.
- Opening Settings, Wallet & Apple Pay produces Card Hashes in `scan`. This remains part of the manual acceptance run.

## Phase 3: Airlift Helper

Track the MIT Airlift repository as a Git submodule and use only its `airtraffic_host.m` source and license.

Implemented:

- Lazy macOS helper build into the application data directory.
- Ad-hoc code signing.
- Helper version and error diagnostics.
- `doctor` checks.

Do not copy or depend on the current AirCard repository's unlicensed implementation.

Exit criteria:

- The helper builds from a clean package installation.
- `doctor` reports the helper path, architecture, and signing result.
- Missing Apple support on Windows produces the experimental message, not a misleading device error.

## Phase 4: Recovery Transaction

Implemented:

- Durable transaction directory creation.
- Books snapshot and restore.
- Transaction state transitions.
- Persisting the uncertain `moved` state before invoking the AirTraffic move.
- Automatic pending recovery before device operations.
- `recover` command.

Exit criteria:

- Unit tests simulate interruption at every state.
- A recovery transaction cannot be deleted while the device resource is unresolved.
- Books state is compared after restore.

## Phase 5: Export Transport

Implemented:

- AIRLock archive construction.
- Controlled Books state.
- First AirTraffic move.
- AFC read of the recovered resource.
- Atomic host output.
- Second AirTraffic move back through the staged link.
- Restore verification.

Exit criteria:

- PNG and PDF signature validation is enforced.
- Raw bytes are preserved.
- Missing resources are skipped without moving anything.
- Recovery uncertainty stops the batch.
- Duplicate output names receive numeric suffixes.

## Phase 6: Real macOS Device Verification

Run on `iPhone16,1`, iOS `18.7.8`, build `22H352`:

1. Discover a USB device.
2. Scan and persist Card Hashes.
3. Export a PNG Card Background.
4. Export a PDF Card Background if available.
5. Compare SHA-256 before and after restore in the test fixture.
6. Open Wallet and confirm the original card still renders.
7. Interrupt a controlled test and run `recover`.
8. Confirm `.airwallet-export/recovery/` has no unresolved transaction.

The real-device test is the first point at which the transport can be called verified.

## Phase 7: Windows Research

Windows work starts only when a Windows 10/11 x64 host and USB iPhone are available. The backend must:

- Detect Apple Mobile Device Support and required DLLs.
- Avoid bundling Apple binaries.
- Implement the same transport interface and Recovery Transaction semantics.
- Complete the full acceptance flow before the README changes from experimental.

Linux remains unsupported until a native ATC/Grappa client exists.

## Non-Goals

- GUI.
- Full pass export.
- General Wallet pass types.
- File conversion.
- Index generation.
- Automatic deduplication.
- iOS version allowlists.

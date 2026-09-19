# Architecture

> Status: implemented. The transport implementation follows the move-read-restore and durable Recovery Transaction model described here.

## Goal

AirWallet Export is a small Python CLI that exports original Apple Wallet card backgrounds from a trusted USB-connected iPhone. It deliberately keeps the transport narrow and keeps recovery state explicit.

## Components

### CLI

The CLI parses commands, prints the safety warning, checks pending recovery work, coordinates the Catalog, and formats human or JSON output. It must remain non-interactive for `export` and `recover`; only `scan` and multi-device selection may prompt.

### Catalog

The Catalog is a local JSON file containing Device observations, Card Hashes, optional Card labels, Card IDs, and discovery timestamps. It never stores logs, payment credentials, or Card Background bytes.

### Discovery

Discovery uses `pymobiledevice3` over USB:

- `usbmux` identifies USB-connected, paired devices.
- `syslog_relay` streams Wallet log entries.
- The user opens Settings, Wallet & Apple Pay to cause Wallet to emit Card Hash entries.
- Parser code reduces each line to a Card Hash and an optional label.

### Transport

The macOS transport uses `pymobiledevice3` for lockdown and AFC, and the MIT Airlift `airtraffic_host` helper from the `vendor/airlift` Git submodule for the AirTraffic move primitive. Windows remains an experimental boundary and has no verified implementation.

### Recovery Store

The recovery store lives in the working directory:

```text
.airwallet-export/
  recovery/
    <transaction-id>/
      transaction.json
      snapshot/
        file-0.bin
        file-1.bin
        manifest.json
```

It is created lazily. A transaction is removed only after the Card Background and Books state have been restored and checked.

## Read Operation

The verified method is not a host-side copy. It is a move, read, and restore transaction:

```text
Wallet Card Background
        |
        | AirTraffic move
        v
/var/mobile/Media/airlift-recovered-<token>
        |
        | AFC read
        v
Host output file
        |
        | AirTraffic move through staged symlink
        v
Wallet Card Background restored
```

Before any move, the implementation must:

1. Select exactly one USB iPhone.
2. Run a non-mutating capability probe.
3. Create a Recovery Transaction directory.
4. Save the tracked Books files and directory state.
5. Flush the transaction metadata to disk.

The operation then:

1. Stages a generated Airlift directory under Media.
2. Writes the controlled `Books/Sync/Books.plist` state.
3. Runs `airtraffic_host` to move the staged link and the target Card Background.
4. Reads the recovered bytes through AFC.
5. Validates the PNG/PDF signature.
6. Writes the output atomically.
7. Runs `airtraffic_host` again to move the recovered bytes back through the staged link.
8. Reads the restored resource through the staged link when possible.
9. Restores the Books preimage and verifies it.
10. Removes generated paths and completes the transaction.

## Recovery Transaction States

```text
planned -> staged -> moved -> exported -> restored -> complete
   |          |        |          |           |
   +----------+--------+----------+-----------+------> recovery required
```

State meanings:

| State | Meaning |
| --- | --- |
| `planned` | Snapshot and identifiers are durable; no device move has started. |
| `staged` | Generated archive and Books state may exist on the device. |
| `moved` | The AirTraffic move may have started. This state is persisted before the helper is invoked, so a crash at the move boundary cannot be mistaken for a safe pre-move state. |
| `exported` | The host output exists and its SHA-256 is recorded. |
| `restored` | The original path has been restored and checked. |
| `complete` | Cleanup and Books verification succeeded; the transaction can be removed. |

If recovery state is uncertain, the CLI must stop the batch and preserve the transaction. It must not continue to another card.

## Version Policy

The transport records `ProductVersion` and `BuildVersion` for diagnostics. It does not use them as a gate. Capability detection, recovery durability, and byte verification are the compatibility boundary.

## Platform Boundary

### macOS

The first implementation target. It can build and sign the native Airlift helper locally with `xcrun clang` and `codesign`.

### Windows

The CLI and core modules remain importable and testable, but the Windows transport fails with a clear experimental message until a native backend is implemented and tested on a real Windows host.

### Linux

Linux discovery and AFC can be implemented with existing libraries, but the AirTraffic client is still missing. Linux is not a supported target.

## Output Contract

The output directory contains only exported files. There is no generated index.

```text
exports/
  card-a1b2c3d4@3x.png
  card-a1b2c3d4@2x.png
  card-a1b2c3d4.pdf
```

Existing names are preserved; collisions receive numeric suffixes. Output bytes are written atomically and never converted.

## Failure Model

| Failure | Behavior |
| --- | --- |
| Resource does not exist | Skip that asset and continue with the remaining assets. |
| PNG/PDF signature invalid | Stop, restore, and report a protocol error. |
| Device disconnected before a move | Stop; no Card Background move is assumed. |
| Device disconnected after a move | Stop, preserve the transaction, and require recovery before another export. |
| Restore bytes differ | Stop, preserve the transaction, and require recovery. |
| Books state cannot be verified | Stop, preserve the transaction, and require recovery. |
| Output name exists | Add ` (1)`, ` (2)`, and so on. No overwrite. |

## Explicit Non-Goals

- A GUI.
- Full Wallet card management.
- Exporting complete `.pkpass` archives.
- General Wallet pass support.
- Screenshots or rendered composites.
- Payment credential access.
- Linux AirTraffic support.

# CLI Contract

> Status: implemented. Real-device acceptance remains required before a platform is marked verified.

## Invocation

```text
airwallet-export [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS]
```

Global options:

| Option | Meaning |
| --- | --- |
| `--json` | Emit machine-readable JSON on stdout. Human warnings remain on stderr. |
| `--catalog PATH` | Override the Catalog path. |
| `--state-dir PATH` | Override the recovery directory root. |
| `--device UDID` | Select a USB iPhone explicitly. |
| `--no-warning` | Suppress the safety warning. The README warning still applies. |

## Commands

### `doctor`

Checks the host and device prerequisites without changing device data.

```sh
airwallet-export doctor
```

Checks:

- macOS support.
- Availability of `xcrun`, `clang`, and `codesign`.
- Airlift helper source and build output.
- USB iPhone discovery and pairing.
- AFC capability.
- Pending Recovery Transactions.
- Catalog readability.

Windows reports the experimental boundary and Apple component requirements. Linux reports unsupported.

### `devices`

Lists USB-connected iPhones.

```sh
airwallet-export devices
```

The output includes name, product type, iOS version, build, UDID, and connection type. Network-only devices are not listed as usable targets.

### `scan`

Collects Card Hashes from Wallet syslog.

```sh
airwallet-export scan
airwallet-export scan --duration 30
```

The command prints an instruction to open:

```text
Settings -> Wallet & Apple Pay
```

It updates the Catalog with Card Hash, optional label, device identity, and discovery time. It does not export files and does not modify Wallet resources.

Each newly observed unique Card Hash prints a running `Detected N Card(s) so far.` line to stderr immediately. With `--json`, stdout still contains exactly one JSON object.

### `cards`

Prints the local Catalog.

```sh
airwallet-export cards
airwallet-export cards --device <UDID>
airwallet-export cards --json
```

No device connection is required unless the user explicitly needs to refresh device metadata.

### `export`

Exports original Card Background resources.

```sh
airwallet-export export --all
airwallet-export export --card <CARD_HASH_OR_CARD_ID>
airwallet-export export --card <ID_1> --card <ID_2> --output ./WalletExports
```

Rules:

- Exactly one of `--all` or one or more `--card` selectors is required.
- Default output directory is `./exports`.
- Default recovery directory is `./.airwallet-export/recovery`.
- Export is non-interactive after device selection.
- Existing files are never overwritten.
- A missing resource is skipped.
- A recovery uncertainty stops the batch.
- No index or manifest is written to the output directory.

### `recover`

Completes unfinished Recovery Transactions for the selected USB iPhone.

```sh
airwallet-export recover
airwallet-export recover --json
```

If no transaction exists, the command exits successfully after reporting that nothing needs recovery.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Command completed successfully. |
| `1` | Device, filesystem, or transport operation failed. |
| `2` | Invalid command usage or missing selector. |
| `3` | Recovery is required or could not be completed safely. |
| `4` | Platform or dependency is unsupported. |

## JSON Output

`--json` gives a single JSON object on stdout. A successful export has this shape:

```json
{
  "ok": true,
  "device": {
    "serial": "00000000-0000000000000000",
    "product": "iPhone16,1",
    "version": "18.7.8",
    "build": "22H352"
  },
  "output": "/absolute/path/exports",
  "exported": [
    {
      "card_id": "card-a1b2c3d4",
      "asset": "cardBackgroundCombined@2x.png",
      "path": "/absolute/path/exports/card-a1b2c3d4@2x.png",
      "bytes": 123456,
      "sha256": "0123456789abcdef"
    }
  ],
  "missing": [],
  "recovery_required": false
}
```

Errors use the same envelope with `ok: false`, `error`, and an optional `recovery_required` flag.

## Warning Behavior

Commands that touch the device print the safety warning to stderr before doing work. The warning is also included in both README files. `--no-warning` only suppresses the repeated terminal line; it does not change the risk.

# Compatibility Matrix

> Status: implementation matrix. Unit and host checks are available; device verification requires a physical USB iPhone.

## Platforms

| OS | Architecture | Status | Verification |
| --- | --- | --- | --- |
| macOS 12+ | arm64 | Implemented; device verification pending | Requires real-device export and recovery test. |
| macOS 12+ | x86_64 | Implemented; device verification pending | Requires real-device export and recovery test. |
| Windows 10/11 | x64 | Experimental | No Windows device environment is currently available. |
| Windows 11 | arm64 | Unsupported in first version | Apple component support is not reliable enough to promise. |
| Linux | any | Unsupported | No native ATC/Grappa client. |

## Verification Levels

| Level | Requirement |
| --- | --- |
| Documentation verified | Protocol behavior is supported by source review or an existing recorded export. |
| Unit verified | Core state, catalog, parser, naming, and recovery transitions pass tests. |
| Host verified | Helper builds, signs, launches, and reports useful diagnostics. |
| Device verified | A physical iPhone completes scan, export, restore, byte comparison, and recovery. |
| Platform verified | A named OS and architecture completes the Device verified flow. |

Only macOS can currently move toward Platform verified. Windows remains experimental until a real Windows host completes the same flow.

## Required Acceptance Flow

For each claimed supported platform:

1. Connect one USB iPhone.
2. Run `doctor` and confirm the capability probe.
3. Run `scan` and confirm at least one Card Hash appears.
4. Run `export --card <ID>` for a PNG-backed Card.
5. Confirm PNG bytes and SHA-256 are recorded.
6. Confirm the original Card remains available after export.
7. Run `export --card <ID>` for a PDF-backed Card when available.
8. Force a controlled interruption before restore in a test environment.
9. Run `recover` and confirm the original bytes are restored.
10. Confirm the Books preimage and generated paths are clean.

## Version Policy

There is no iOS version allowlist. The compatibility decision is made by:

- The capability probe.
- The Recovery Transaction.
- The AirTraffic result.
- The restored-byte comparison.

A new iOS version may work without a code change. It may also fail safely and leave a recoverable transaction. Neither outcome should be decided from a version string alone.

# Security and Data-Loss Risks

> Status: implementation warning. Read this before running any device-facing command.

## Summary

AirWallet Export relies on a private AirTraffic behavior to move a Wallet resource outside its normal scope, read it through AFC, and move it back. This is not an Apple-supported API. The primary risk is not credential exposure; it is interrupted restoration of the Wallet resource.

## Data-Loss Risk

The read path is a mutation:

```text
move original -> read temporary file -> move original back
```

The host cannot simply copy the original because AFC cannot directly access the Wallet pass directory. A host-side copy therefore cannot replace the device-side restore.

The implementation must fail closed:

- Persist a Recovery Transaction before the first move.
- Persist the tracked Books files and directory state.
- Never begin a new export while a prior transaction is unresolved.
- Stop the batch when recovery state is uncertain.
- Verify the restored resource and Books state.
- Keep the transaction when verification fails.

## Warning Requirements

Both README files and device-facing CLI commands must state that data loss is possible. The warning must tell users to:

- Back up the iPhone first.
- Keep it unlocked and USB-connected.
- Avoid unplugging or restarting during export.
- Run recovery before a new export after an interruption.

## Sensitive Data

The tool must not export or log:

- PAN or card number.
- DPAN or payment token.
- Pass signatures.
- Payment application data.
- Transaction history.
- Full syslog lines.

The Catalog stores only Device metadata, Card Hash, optional Card label, Card ID, and timestamps.

## Trust Boundary

The user must own or be authorized to access the iPhone and host computer. The tool assumes a paired, trusted USB device and does not attempt to bypass device authorization.

The tool should not:

- Pair a device without user action.
- Use Wi-Fi as an export transport in the first version.
- Disable device security.
- Install a profile or jailbreak the device.
- Modify unrelated files.

## Apple Components

On Windows, Apple Mobile Device Support and its private DLLs are system dependencies. They must not be bundled or redistributed. Apple's own installer may provide them, but installation is not part of the initial documented flow because no Windows verification environment exists.

## Private API Instability

The Airlift helper depends on:

- `MobileDevice` behavior.
- `AirTrafficHost`.
- `com.apple.streaming_zip_conduit`.
- `com.apple.afc`.
- iOS Books synchronization behavior.
- The ATAirlock move semantics.

Apple may change any of these. The tool must report protocol failures accurately and preserve recovery state rather than attempting blind retries.

## Incident Response

If an export or recovery fails:

1. Do not delete `.airwallet-export/`.
2. Keep the iPhone connected by USB and unlocked.
3. Run `airwallet-export recover`.
4. If recovery fails, preserve the transaction directory and the device UDID for diagnosis.
5. Do not run another export until recovery succeeds.

## Legal and Operational Notice

This project is intended for a user's own device and data. It depends on behavior that may violate platform support expectations or local policy. The user is responsible for authorization, backups, and deciding whether the risk is acceptable.

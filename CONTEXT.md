# AirWallet Export

AirWallet Export is a command-line tool that exports Apple Wallet card artwork from a trusted iPhone.

## Language

**Device**:
A physical, trusted, USB-connected iPhone. Network-connected devices are visible to diagnostics but are not export targets.
_Avoid_: Phone, target, handset

**Card**:
An Apple Pay payment pass stored by Wallet under `/var/mobile/Library/Passes/Cards`.
_Avoid_: Pass, account, payment method

**Card Hash**:
The device-side identifier used in a Card's `.pkpass` directory name. It is the stable identity used by the Catalog.
_Avoid_: Card number, token, UUID

**Card ID**:
The host-facing, filename-safe identifier derived from a Card's optional label and Card Hash.
_Avoid_: Pass ID, display name

**Card Background**:
An original `cardBackgroundCombined` resource stored inside a Card, currently `@3x.png`, `@2x.png`, `.png`, or `.pdf`.
_Avoid_: Screenshot, card image, artwork

**Catalog**:
The local record of Device observations, Card Hashes, optional Card labels, and discovery timestamps. It contains no payment credentials.
_Avoid_: Database, index

**Scan**:
A discovery session in which Wallet emits Card Hash log entries while the user opens Settings, Wallet & Apple Pay.
_Avoid_: Crawl, enumerate, search

**Export**:
An operation that writes Card Background bytes from a Card to the host without converting their format or modifying their content.
_Avoid_: Render, convert, screenshot

**Recovery Transaction**:
The durable host-side record and snapshot used to finish restoring a Card Background and the device Books state after an interrupted Export.
_Avoid_: Backup, checkpoint, journal

**Capability Probe**:
A non-mutating check that the Device can open the required AFC and AirTraffic paths before an Export starts.
_Avoid_: Version check, compatibility gate

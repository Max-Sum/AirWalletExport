# AirWallet Export

[中文说明](README.zh-CN.md)

AirWallet Export saves the original background artwork from Apple Pay payment cards on an iPhone to a Mac. It is a command-line tool: connect the iPhone by USB, scan for cards, then choose which artwork to save.

The exported files are the PNG or PDF backgrounds stored by Wallet. The tool does not read card numbers or transaction history.

> [!WARNING]
> An interrupted export can leave card artwork in need of recovery, and data loss is possible. Back up the iPhone before using this tool. Keep it unlocked and connected by USB while exporting or recovering, and do not restart it or unplug the cable. If an export is interrupted, run `airwallet-export recover` before trying again.

## Before You Start

Have the following ready before you begin.

- A Mac running macOS 12 or later.
- An iPhone with at least one Apple Pay payment card in Wallet.
- A USB cable. The iPhone must be unlocked and trusted by the Mac.
- A recent iPhone backup.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for installing the command.

Windows is not currently supported because no test platform is available.

## Install

Open Terminal and run:

```sh
git clone --recurse-submodules https://github.com/Max-Sum/AirWalletExport.git
cd AirWalletExport
uv tool install .
```

Check the installation:

```sh
airwallet-export --help
```

## Export Artwork

### 1. Connect and check the iPhone

Connect the iPhone by USB and unlock it. If the iPhone asks whether to trust the computer, tap **Trust**.

```sh
airwallet-export doctor
```

Continue after the checks pass. If the command says recovery is required, follow [Recover an Interrupted Export](#recover-an-interrupted-export) first.

### 2. Find your cards

Start a 30-second scan:

```sh
airwallet-export scan --duration 30
```

While the scan is running, open **Settings > Wallet & Apple Pay** on the iPhone and scroll up and down. The Terminal reports each card it finds.

After the scan finishes, list the cards:

```sh
airwallet-export cards
```

The first column is the card ID. You will use that ID if you want to export one card.

### 3. Save the files

To export every card found during the scan:

```sh
airwallet-export export --all --output ./WalletArtwork
```

To export one card, replace `<CARD_ID>` with an ID shown by `airwallet-export cards`:

```sh
airwallet-export export --card <CARD_ID> --output ./WalletArtwork
```

Open the result:

```sh
open ./WalletArtwork
```

The folder may contain PNG files at different sizes and a PDF file. A card may not provide every format. Existing files are not overwritten; a new copy receives a suffix such as `(1)`.

## Recover an Interrupted Export

Keep the same iPhone unlocked and connected by USB, then run:

```sh
airwallet-export recover
```

Do not start another export until recovery succeeds. Keep the `.airwallet-export` directory in the directory where you ran the interrupted command. If recovery still fails, do not delete that directory.

## What It Can Export

AirWallet Export handles the original background artwork of Apple Pay payment cards. It does not export:

- Complete `.pkpass` files.
- Screenshots or rendered images of cards.
- Boarding passes, event tickets, membership cards, or other non-payment passes.
- Card numbers, payment tokens, signatures, balances, or transaction history.

It does not add, remove, or edit cards in Wallet.

## Troubleshooting

### No iPhone is found

Unlock the iPhone, reconnect the USB cable, and accept the **Trust** prompt if it appears. Then run `airwallet-export doctor` again.

### The scan finds no cards

Keep **Settings > Wallet & Apple Pay** open during the scan. Try again with more time:

```sh
airwallet-export scan --duration 60
```

### More than one iPhone is connected

List the devices:

```sh
airwallet-export devices
```

Copy the UDID of the iPhone you want and add `--device <UDID>` to the command, for example:

```sh
airwallet-export export --all --device <UDID> --output ./WalletArtwork
```

### The export stopped or failed

Keep the same iPhone connected and run `airwallet-export recover`. Do not delete `.airwallet-export` or begin another export first.

## Command Reference

| Command | Purpose |
| --- | --- |
| `airwallet-export doctor` | Check the Mac, iPhone connection, and recovery state. |
| `airwallet-export devices` | List USB-connected iPhones. |
| `airwallet-export scan --duration 30` | Find cards while Wallet settings are open on the iPhone. |
| `airwallet-export cards` | List cards found by previous scans. |
| `airwallet-export export --card <CARD_ID>` | Export one card. |
| `airwallet-export export --all` | Export all cards found for the connected iPhone. |
| `airwallet-export recover` | Recover an interrupted export. |

More options are listed in the [command reference](docs/cli.md). Read [security and data-loss risks](docs/security.md) before using the tool on an important device.

## License

MIT
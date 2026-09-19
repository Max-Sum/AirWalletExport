# AirWallet Export

[English README](README.md)

AirWallet Export 可以把 iPhone 中 Apple Pay 支付卡片的原始背景图保存到 Mac。它是一个命令行工具：用 USB 连接 iPhone，扫描卡片，再选择要保存的背景图。

导出的内容是 Wallet 保存在手机上的 PNG 或 PDF 背景文件。程序不会读取卡号或交易记录。

> [!WARNING]
> 导出一旦中断，卡片背景图可能需要恢复，严重时可能丢失数据。使用前请备份 iPhone。导出或恢复期间，手机要保持解锁并通过 USB 连接，不要重启手机或拔掉数据线。如果导出中断，请先运行 `airwallet-export recover`，不要直接重试导出。

## 开始前的准备

准备好下面这些东西再开始。

- 一台运行 macOS 12 或更高版本的 Mac。
- 一台 Wallet 中至少有一张 Apple Pay 支付卡片的 iPhone。
- 一根 USB 数据线。iPhone 需要保持解锁，并已信任这台 Mac。
- 一份近期的 iPhone 备份。
- 用来安装命令的 [`uv`](https://docs.astral.sh/uv/getting-started/installation/)。

Windows 因为没有实验平台暂时未支持。

## 安装

打开 Mac 上的“终端”，运行：

```sh
git clone --recurse-submodules https://github.com/Max-Sum/AirWalletExport.git
cd AirWalletExport
uv tool install .
```

检查安装是否成功：

```sh
airwallet-export --help
```

## 导出背景图

### 1. 连接并检查 iPhone

用 USB 连接 iPhone 并解锁。手机询问是否信任这台电脑时，选择“信任”。

```sh
airwallet-export doctor
```

检查通过后再继续。如果命令提示需要恢复，请先按照[恢复中断的导出](#恢复中断的导出)操作。

### 2. 找到卡片

开始一次 30 秒的扫描：

```sh
airwallet-export scan --duration 30
```

扫描期间，在 iPhone 上打开“设置 > 钱包与 Apple Pay”，上下滑动。终端会逐个报告找到的卡片。

扫描结束后查看卡片列表：

```sh
airwallet-export cards
```

第一列是卡片 ID。只导出一张卡片时需要用到这个 ID。

### 3. 保存文件

导出扫描到的全部卡片：

```sh
airwallet-export export --all --output ./WalletArtwork
```

只导出一张卡片时，把 `<CARD_ID>` 换成 `airwallet-export cards` 显示的 ID：

```sh
airwallet-export export --card <CARD_ID> --output ./WalletArtwork
```

打开导出目录：

```sh
open ./WalletArtwork
```

目录中可能有不同尺寸的 PNG 文件和 PDF 文件。每张卡片提供的格式可能不同。程序不会覆盖已有文件；遇到重名时，新文件会带有 `(1)` 一类的编号。

## 恢复中断的导出

保持同一台 iPhone 解锁并通过 USB 连接，然后运行：

```sh
airwallet-export recover
```

恢复成功前不要开始新的导出。请保留中断时运行命令的目录中的 `.airwallet-export` 文件夹。恢复仍然失败时，也不要删除这个文件夹。

## 可以导出什么

AirWallet Export 只处理 Apple Pay 支付卡片的原始背景图。它不会导出：

- 完整的 `.pkpass` 文件。
- 卡片截图或渲染后的图片。
- 登机牌、活动门票、会员卡等非支付卡片。
- 卡号、支付令牌、签名、余额或交易记录。

程序也不会增加、删除或修改 Wallet 中的卡片。

## 常见问题

### 找不到 iPhone

解锁 iPhone，重新连接 USB 数据线。手机出现“信任”提示时选择“信任”，然后再次运行 `airwallet-export doctor`。

### 扫描不到卡片

扫描期间不要离开“设置 > 钱包与 Apple Pay”页面。也可以延长扫描时间后重试：

```sh
airwallet-export scan --duration 60
```

### 连接了多台 iPhone

先列出设备：

```sh
airwallet-export devices
```

复制目标 iPhone 的 UDID，在命令中加入 `--device <UDID>`。例如：

```sh
airwallet-export export --all --device <UDID> --output ./WalletArtwork
```

### 导出停止或失败

保持同一台 iPhone 连接，然后运行 `airwallet-export recover`。不要删除 `.airwallet-export`，也不要先开始新的导出。

## 命令速查

| 命令 | 用途 |
| --- | --- |
| `airwallet-export doctor` | 检查 Mac、iPhone 连接和恢复状态。 |
| `airwallet-export devices` | 列出通过 USB 连接的 iPhone。 |
| `airwallet-export scan --duration 30` | 在 iPhone 上打开 Wallet 设置页面时查找卡片。 |
| `airwallet-export cards` | 查看以前扫描到的卡片。 |
| `airwallet-export export --card <CARD_ID>` | 导出一张卡片。 |
| `airwallet-export export --all` | 导出当前 iPhone 上扫描到的全部卡片。 |
| `airwallet-export recover` | 恢复中断的导出。 |

其他选项见[命令参考](docs/cli.md)。在重要设备上使用前，请阅读[安全和数据丢失风险](docs/security.md)。

## 许可证

MIT

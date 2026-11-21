---
name: "cli-anything-iloader"
description: "Command-line interface for Iloader - Agent-friendly CLI for [iloader](https://github.com/nab138/iloader), the iOS sideloader. It uses the..."
---

# cli-anything-iloader

Agent-friendly CLI for [iloader](https://github.com/nab138/iloader), the iOS sideloader. It uses the same engine as the GUI (the `isideload` and `idevice` crates) through a small headless Rust helper, `iloader-helper`.

## Installation

This CLI is installed as part of the cli-anything-iloader package:

```bash
pip install cli-anything-iloader
```

**Prerequisites:**
- Python 3.10+
- Iloader must be installed on your system

## Usage

### Basic Commands

```bash
# Show help
cli-anything-iloader --help

# Start interactive REPL mode
cli-anything-iloader

# Create a new project
cli-anything-iloader project new -o project.json

# Run with JSON output (for agent consumption)
cli-anything-iloader --json project info -p project.json
```

## Command Groups

### Cli

Sideload IPAs to iOS devices with iloader's isideload/idevice engine.

| Command | Description |
|---------|-------------|
| `install` | Sign with the Apple ID and install an IPA on the device. |
| `repl` | Interactive REPL (default when no subcommand is given). |

### Session

Session state: account, anisette server, selected device.

| Command | Description |
|---------|-------------|
| `status` | Show current session state. |
| `set-account` | Set the Apple ID (password comes from ILOADER_PASSWORD, never stored). |
| `select-device` | Select the target device by UDID (see `device list`). |
| `undo` | Undo the last session change. |
| `redo` | Redo the last undone session change. |
| `anisette-servers` | List known anisette servers. |

### Device

Connected iOS devices (via usbmuxd).

| Command | Description |
|---------|-------------|
| `list` | List devices reported by usbmuxd. |

### Ipa

Inspect and fetch IPA files.

| Command | Description |
|---------|-------------|
| `info` | Show bundle id, version and extensions of an IPA. |
| `fetch-sidestore` | Download SideStore / LiveContainer+SideStore (same sources as iloader). |

### Account

Developer account resources (needs ILOADER_PASSWORD; 2FA via ILOADER_2FA_CODE).

| Command | Description |
|---------|-------------|
| `certs` | List development certificates. |
| `revoke-cert` | Revoke a development certificate by serial number. |
| `app-ids` | List registered App IDs and remaining quota. |
| `delete-app-id` | Delete an App ID. |

## Examples

### Create a New Project

Create a new iloader project file.

```bash
cli-anything-iloader project new -o myproject.json
# Or with JSON output for programmatic use
cli-anything-iloader --json project new -o myproject.json
```

### Interactive REPL Session

Start an interactive session with undo/redo support.

```bash
cli-anything-iloader
# Enter commands interactively
# Use 'help' to see available commands
# Use 'undo' and 'redo' for history navigation
```

## For AI Agents

When using this CLI programmatically:

1. **Always use `--json` flag** for parseable output
2. **Check return codes** - 0 for success, non-zero for errors
3. **Parse stderr** for error messages on failure
4. **Use absolute paths** for all file operations
5. **Verify outputs exist** after export operations

## Version

1.0.0
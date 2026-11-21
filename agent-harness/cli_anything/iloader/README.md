# cli-anything-iloader

Agent-friendly CLI for [iloader](https://github.com/nab138/iloader), the iOS sideloader.
It uses the same engine as the GUI (the `isideload` and `idevice` crates) through a small
headless Rust helper, `iloader-helper`.

## Requirements

- Python 3.10+, and a Rust toolchain to build the helper (on Windows: LLVM, set `LIBCLANG_PATH`).
- usbmuxd reachable (Apple Devices / iTunes on Windows, `usbmuxd` on Linux, built in on macOS).
- An Apple ID with 2FA for `install` and `account` commands.

## Install

```bash
cd agent-harness
pip install -e .
cd iloader-helper && cargo build --release      # first build takes ~13 min
export ILOADER_HELPER=/path/to/target/release/iloader-helper   # or put it on PATH
cli-anything-iloader --help
```

## Secrets

The Apple ID password is **never** a CLI argument or stored in the session. Export
`ILOADER_PASSWORD` for the command; 2FA codes come from `ILOADER_2FA_CODE` (or stdin).

### Reusing the GUI's saved password (experimental)

`session set-account <email> --anisette <server> --use-saved-login` makes the helper read the
password from the OS keyring entry the iloader GUI saves (service `iloader`, user = email). The
CLI keeps its **own** anisette identity under `~/.cli-anything-iloader/helper` (or
`$ILOADER_CLI_HOME/helper`). It reuses the GUI's development certificate (machine name `iloader`)
through a **read-only** view of the GUI's keyring storage, so it never creates or revokes a
certificate and can never overwrite the GUI's certificate key. Free Apple IDs allow only one
development certificate, which is why the certificate is shared instead of creating a second one.

Sharing the GUI's anisette state was tried first and Apple rejected the login with GrandSlam
`-22410`, so only the certificate is shared. A new anisette identity may ask for a 2FA code on its
first login (it did not in the verified run); later runs reuse it.

For callers without an interactive stdin, set `ILOADER_2FA_FILE=<path>`: the helper then waits up to
3 minutes for that file to appear, reads the code from it and deletes it.
Set `RUST_LOG=isideload=debug` when running the helper directly to see its progress on stderr.

## Usage

```bash
cli-anything-iloader --json device list
cli-anything-iloader session set-account me@example.com --anisette ani.iloader.app
cli-anything-iloader session select-device <UDID>
cli-anything-iloader ipa info app.ipa
cli-anything-iloader ipa fetch-sidestore --dest ./dl
ILOADER_PASSWORD=... cli-anything-iloader install app.ipa
ILOADER_PASSWORD=... cli-anything-iloader account certs
ILOADER_PASSWORD=... cli-anything-iloader account revoke-cert <serial> --yes
```

Run with no subcommand for the REPL. Session changes auto-save after one-shot commands;
`--dry-run` suppresses the save. `session undo` / `session redo` step through changes.

## Tests

```bash
CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/iloader/tests/ -v -s
```

# ILOADER.md - harness SOP

## Analysis
- iloader is a Tauri 2 app (React front end, Rust back end in `src-tauri/src`).
- Back end engine: `isideload` (Apple developer API, signing, install) and `idevice` (usbmuxd, lockdown, house arrest).
- No CLI exists; every action is a `#[tauri::command]` bound to `AppHandle`/`Window`/`State`, so it cannot be called headless.
- State: in-memory `Sideloader` (logged-in account) and selected device with pairing file; credentials in the OS keyring; settings in `data.json` (tauri store).

## GUI action -> CLI mapping
| GUI | Tauri command | CLI |
|---|---|---|
| Device list | `list_devices` | `device list` |
| Pick device | `set_selected_device` | `session select-device` |
| Sign in | `login_new` / `login_stored` | `session set-account` + `ILOADER_PASSWORD` |
| Install IPA | `sideload_operation` | `install` |
| Install SideStore | `install_sidestore_operation` | `ipa fetch-sidestore` then `install` |
| Certificates | `get_certificates`, `revoke_certificate` | `account certs`, `account revoke-cert` |
| App IDs | `list_app_ids`, `delete_app_id` | `account app-ids`, `account delete-app-id` |

## Architecture
`cli_anything/iloader/iloader_cli.py` (Click + REPL) -> `core/` (session, IPA) -> `utils/iloader_backend.py` -> `iloader-helper` (Rust, one JSON document per call).

## Known gaps
- Not ported: pairing-file export/placement for SideStore (`export_pairing_cmd`, `place_pairing_cmd`), RemotePairing, keyring storage, team selection, interactive max-certs prompt (the helper aborts instead of revoking).
- The helper logs in on every call (no long-lived daemon), so each account command may need a 2FA code.

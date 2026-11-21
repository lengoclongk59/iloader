# TEST.md - cli-anything-iloader

## Test Inventory Plan

- `test_core.py`: 17 unit tests (synthetic data, no external deps)
- `test_full_e2e.py`: 11 E2E tests (real IPA files, real network, real helper binary, installed CLI subprocess)

## Unit Test Plan

| Module | Covered | Edge cases |
|---|---|---|
| `core/session.py` | defaults, mutate, undo/redo, save/load round-trip, history cap, status (no password leak) | missing file, empty undo stack, redo cleared after new mutation |
| `core/ipa.py` | `inspect_ipa` on a synthetic IPA (bundle id, version, extensions) | missing file, non-zip, zip without Info.plist |
| `utils/iloader_backend.py` | helper discovery, `account_args` validation | missing helper, missing email, missing `ILOADER_PASSWORD` |
| `iloader_cli.py` | `--json` output, `--dry-run` does not save, auto-save does, revoke/delete refuse without `--yes` | install without device |

## E2E Test Plan

- Build a real IPA zip on disk and inspect it through the installed CLI.
- Download the real SideStore IPA from GitHub and verify it is a valid IPA (zip magic, `Payload/*.app/Info.plist`, bundle id contains `sidestore`).
- Run the real `iloader-helper` binary (built from the same `isideload`/`idevice` crates iloader uses): `device list` must return a JSON list when usbmuxd is reachable, or a clean JSON error when it is not.
- Run account commands without credentials: must fail loudly with a clear message.

Not testable here (needs hardware/credentials): `install`, `account certs|app-ids|revoke-cert|delete-app-id` against Apple servers, and 2FA. These are exercised only up to argument validation.

## Realistic Workflow Scenarios

- **Prepare a SideStore install**: Simulates the "Install SideStore" button. Operations: `ipa fetch-sidestore` -> `ipa info` -> `session set-account` -> `session select-device`. Verified: IPA is valid zip with a SideStore bundle id; session file holds email and UDID and never a password.
- **Session iteration**: Simulates changing the target. Operations: set account, select device A, select device B, undo, redo. Verified: state after each step, persisted file after auto-save, untouched file with `--dry-run`.

---

## Test Results

Command: `CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/iloader/tests/ -v -s` (2026-11-21)

```
[_resolve_cli] Using installed command: C:\Users\Admin\AppData\Local\Programs\Python\Python312\Scripts\cli-anything-iloader.EXE
cli_anything/iloader/tests/test_core.py::TestSession::test_defaults PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_mutate_and_save_roundtrip PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_undo_redo PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_undo_empty PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_redo_empty PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_redo_cleared_after_new_mutation PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_history_capped PASSED
cli_anything/iloader/tests/test_core.py::TestSession::test_status_never_contains_password PASSED
cli_anything/iloader/tests/test_core.py::TestIpa::test_inspect PASSED
cli_anything/iloader/tests/test_core.py::TestIpa::test_missing_file PASSED
cli_anything/iloader/tests/test_core.py::TestIpa::test_not_a_zip PASSED
cli_anything/iloader/tests/test_core.py::TestIpa::test_no_info_plist PASSED
cli_anything/iloader/tests/test_core.py::TestBackend::test_account_args_requires_email PASSED
cli_anything/iloader/tests/test_core.py::TestBackend::test_account_args_requires_password PASSED
cli_anything/iloader/tests/test_core.py::TestBackend::test_account_args_ok_never_includes_password PASSED
cli_anything/iloader/tests/test_core.py::TestBackend::test_missing_helper PASSED
cli_anything/iloader/tests/test_core.py::TestCli::test_json_status PASSED
cli_anything/iloader/tests/test_core.py::TestCli::test_auto_save PASSED
cli_anything/iloader/tests/test_core.py::TestCli::test_dry_run_does_not_save PASSED
cli_anything/iloader/tests/test_core.py::TestCli::test_revoke_requires_yes PASSED
cli_anything/iloader/tests/test_core.py::TestCli::test_install_without_device PASSED
PASSED
PASSED
PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestRealBackend::test_helper_account_cmd_without_email_fails_loudly PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestRealBackend::test_helper_unknown_command PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestRealBackend::test_helper_missing_password_fails_loudly PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestCLISubprocess::test_help PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestCLISubprocess::test_ipa_info_json PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestCLISubprocess::test_device_list_json PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestCLISubprocess::test_prepare_sidestore_workflow PASSED
cli_anything/iloader/tests/test_full_e2e.py::TestCLISubprocess::test_install_without_credentials_fails PASSED
============================= 32 passed in 6.83s ==============================
```

### Summary
- 32 tests, 32 passed (100%), about 7 s.
- Subprocess tests ran against the installed `cli-anything-iloader` command.
- The real `iloader-helper` was built from `isideload 0.5.2` / `idevice 0.1.68`; `devices` returned one connected iPhone.

### Coverage notes / gaps
- `install`, `account certs|app-ids|revoke-cert|delete-app-id` and 2FA were not run against Apple: they need real credentials and would change a real account/device. Only argument/credential validation is covered.
- The SideStore download test fetches only the first 200,000 bytes of the real IPA (the link was ~50 KB/s, file is ~27 MB), so full-IPA validation relies on the synthetic IPA tests.

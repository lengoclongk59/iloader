"""E2E tests: real helper binary, real network, installed CLI via subprocess.

Account/install commands need Apple credentials and cannot run unattended; they are
tested up to loud, clear failure when credentials are missing.
"""

import json
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile

import pytest

from cli_anything.iloader.core import ipa as ipa_mod
from cli_anything.iloader.utils import iloader_backend as backend


def _resolve_cli(name):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


def _make_ipa(path):
    info = {"CFBundleIdentifier": "com.example.e2e", "CFBundleName": "E2E", "CFBundleShortVersionString": "9.9"}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Payload/E2E.app/Info.plist", plistlib.dumps(info))
    return str(path)


class TestRealBackend:
    def test_sidestore_download_prefix_is_zip(self, tmp_path):
        # Truncated on purpose: the link here can be ~50 KB/s and the IPA is ~27 MB.
        result = ipa_mod.download_sidestore(str(tmp_path), max_bytes=200_000)
        print(f"\n  SideStore IPA prefix: {result['path']} ({result['size']:,} bytes)")
        assert result["size"] == 200_000 and result["complete"] is False
        with open(result["path"], "rb") as f:
            assert f.read(4) == b"PK\x03\x04"

    def test_helper_binary_found(self):
        path = backend.find_helper()
        print(f"\n  helper: {path}")
        assert os.path.getsize(path) > 1_000_000

    def test_helper_devices_returns_json_list_or_clean_error(self):
        try:
            data = backend.run_helper(["devices"])
        except backend.BackendError as e:
            # usbmuxd/iTunes service not running: must be a clear message
            assert "usbmuxd" in str(e)
            return
        assert isinstance(data, list)
        for dev in data:
            assert dev["udid"]
            assert dev["connectionType"] in ("USB", "Network", "Unknown")
        print(f"\n  devices: {len(data)}")

    def test_helper_account_cmd_without_email_fails_loudly(self):
        with pytest.raises(backend.BackendError, match="--email"):
            backend.run_helper(["certs"])

    def test_helper_unknown_command(self):
        with pytest.raises(backend.BackendError, match="unknown command"):
            backend.run_helper(["frobnicate"])

    def test_helper_missing_password_fails_loudly(self, monkeypatch):
        monkeypatch.delenv("ILOADER_PASSWORD", raising=False)
        with pytest.raises(backend.BackendError, match="ILOADER_PASSWORD"):
            backend.run_helper(["app-ids", "--email", "nobody@example.com"])


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-iloader")

    def _run(self, args, env_extra=None, check=True):
        env = dict(os.environ)
        env.pop("ILOADER_PASSWORD", None)
        env.update(env_extra or {})
        return subprocess.run(self.CLI_BASE + args, capture_output=True, text=True, check=check, env=env)

    def test_help(self):
        r = self._run(["--help"])
        assert r.returncode == 0
        assert "sideload" in r.stdout.lower()

    def test_ipa_info_json(self, tmp_path):
        p = _make_ipa(tmp_path / "e2e.ipa")
        r = self._run(["--json", "ipa", "info", p])
        data = json.loads(r.stdout)
        assert data["bundle_id"] == "com.example.e2e"

    def test_device_list_json(self):
        r = self._run(["--json", "device", "list"], check=False)
        doc = json.loads(r.stdout)
        if r.returncode == 0:
            assert isinstance(doc, list)
        else:
            assert "error" in doc

    def test_prepare_sidestore_workflow(self, tmp_path):
        sess = str(tmp_path / "s.json")
        base = ["--session", sess]
        fetched = json.loads(
            self._run(base + ["--json", "ipa", "fetch-sidestore", "--dest", str(tmp_path), "--max-bytes", "100000"]).stdout
        )
        assert fetched["size"] == 100_000 and fetched["complete"] is False
        self._run(base + ["session", "set-account", "Dev@Example.com"])
        self._run(base + ["session", "select-device", "UDID-TEST"])
        state = json.load(open(sess))
        assert state["email"] == "dev@example.com"
        assert state["device"] == "UDID-TEST"
        assert "ILOADER_PASSWORD" not in open(sess).read()

    def test_install_without_credentials_fails(self, tmp_path):
        sess = str(tmp_path / "s.json")
        base = ["--session", sess]
        p = _make_ipa(tmp_path / "e2e.ipa")
        self._run(base + ["session", "set-account", "dev@example.com"])
        r = self._run(base + ["--json", "install", p, "--udid", "UDID-TEST"], check=False)
        assert r.returncode == 1
        assert "ILOADER_PASSWORD" in json.loads(r.stdout)["error"]

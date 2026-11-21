"""Unit tests: synthetic data, no network, no device."""

import json
import os
import plistlib
import zipfile

import pytest
from click.testing import CliRunner

from cli_anything.iloader.core import ipa as ipa_mod
from cli_anything.iloader.core.session import Session
from cli_anything.iloader.utils import iloader_backend as backend


def make_ipa(path, bundle_id="com.example.app", extensions=()):
    info = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": "Example",
        "CFBundleShortVersionString": "1.2.3",
        "CFBundleVersion": "45",
        "MinimumOSVersion": "15.0",
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Payload/Example.app/Info.plist", plistlib.dumps(info))
        for ext in extensions:
            zf.writestr(f"Payload/Example.app/PlugIns/{ext}/Info.plist", b"x")
    return str(path)


@pytest.fixture
def sess_path(tmp_path):
    return str(tmp_path / "session.json")


class TestSession:
    def test_defaults(self, sess_path):
        s = Session(sess_path)
        assert s.state["email"] is None
        assert s.state["anisette"] == "ani.iloader.app"
        assert not s.modified

    def test_mutate_and_save_roundtrip(self, sess_path):
        s = Session(sess_path)
        s.mutate(email="a@b.c", device="UDID1")
        assert s.modified
        s.save()
        s2 = Session(sess_path)
        assert s2.state["email"] == "a@b.c"
        assert s2.state["device"] == "UDID1"

    def test_undo_redo(self, sess_path):
        s = Session(sess_path)
        s.mutate(device="A")
        s.mutate(device="B")
        assert s.undo() and s.state["device"] == "A"
        assert s.redo() and s.state["device"] == "B"

    def test_undo_empty(self, sess_path):
        assert Session(sess_path).undo() is False

    def test_redo_empty(self, sess_path):
        assert Session(sess_path).redo() is False

    def test_redo_cleared_after_new_mutation(self, sess_path):
        s = Session(sess_path)
        s.mutate(device="A")
        s.undo()
        s.mutate(device="C")
        assert s.redo() is False

    def test_history_capped(self, sess_path):
        s = Session(sess_path)
        for i in range(60):
            s.record({"n": i})
        assert len(s.state["history"]) == 50
        assert s.state["history"][-1] == {"n": 59}

    def test_status_never_contains_password(self, sess_path, monkeypatch):
        monkeypatch.setenv("ILOADER_PASSWORD", "hunter2-secret")
        status = Session(sess_path).status()
        assert status["password_env_set"] is True
        assert "hunter2-secret" not in json.dumps(status)


class TestIpa:
    def test_inspect(self, tmp_path):
        p = make_ipa(tmp_path / "a.ipa", extensions=["Share.appex", "Widget.appex"])
        info = ipa_mod.inspect_ipa(p)
        assert info["bundle_id"] == "com.example.app"
        assert info["version"] == "1.2.3"
        assert info["min_ios"] == "15.0"
        assert info["extensions"] == ["Share.appex", "Widget.appex"]

    def test_missing_file(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            ipa_mod.inspect_ipa(str(tmp_path / "nope.ipa"))

    def test_not_a_zip(self, tmp_path):
        p = tmp_path / "bad.ipa"
        p.write_bytes(b"hello")
        with pytest.raises(ValueError, match="not a zip"):
            ipa_mod.inspect_ipa(str(p))

    def test_no_info_plist(self, tmp_path):
        p = tmp_path / "empty.ipa"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("readme.txt", "x")
        with pytest.raises(ValueError, match="Info.plist"):
            ipa_mod.inspect_ipa(str(p))


class TestBackend:
    def test_account_args_requires_email(self):
        with pytest.raises(backend.BackendError, match="No Apple ID"):
            backend.account_args(None, "x")

    def test_account_args_requires_password(self, monkeypatch):
        monkeypatch.delenv("ILOADER_PASSWORD", raising=False)
        with pytest.raises(backend.BackendError, match="ILOADER_PASSWORD"):
            backend.account_args("a@b.c", "x")

    def test_account_args_ok_never_includes_password(self, monkeypatch):
        monkeypatch.setenv("ILOADER_PASSWORD", "secret-pw")
        args = backend.account_args("a@b.c", "srv")
        assert args == ["--email", "a@b.c", "--anisette", "srv"]

    def test_missing_helper(self, monkeypatch):
        monkeypatch.setenv("ILOADER_HELPER", "")
        monkeypatch.setattr(backend.shutil, "which", lambda _n: None)
        monkeypatch.setattr(backend.glob, "glob", lambda _p: [])
        with pytest.raises(backend.BackendError, match="cargo build"):
            backend.find_helper()


class TestCli:
    def _run(self, sess_path, *args):
        from cli_anything.iloader import iloader_cli

        iloader_cli._session = None
        return CliRunner().invoke(iloader_cli.cli, ["--session", sess_path, *args])

    def test_json_status(self, sess_path):
        r = self._run(sess_path, "--json", "session", "status")
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["email"] is None

    def test_auto_save(self, sess_path):
        r = self._run(sess_path, "session", "set-account", "X@Y.com")
        assert r.exit_code == 0, r.output
        assert json.load(open(sess_path))["email"] == "x@y.com"

    def test_dry_run_does_not_save(self, sess_path):
        r = self._run(sess_path, "--dry-run", "session", "set-account", "x@y.com")
        assert r.exit_code == 0, r.output
        assert not os.path.exists(sess_path)

    def test_revoke_requires_yes(self, sess_path):
        r = self._run(sess_path, "--json", "account", "revoke-cert", "123")
        assert r.exit_code == 1
        assert "--yes" in r.output

    def test_install_without_device(self, sess_path, tmp_path):
        p = make_ipa(tmp_path / "a.ipa")
        r = self._run(sess_path, "--json", "install", p)
        assert r.exit_code == 1
        assert "No device" in r.output

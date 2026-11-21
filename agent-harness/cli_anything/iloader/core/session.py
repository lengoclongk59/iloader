"""Stateful session for the iloader CLI: Apple ID, anisette server, selected device.

The session never stores passwords. The Apple ID password is only read from the
``ILOADER_PASSWORD`` environment variable at the moment a backend call is made.
"""

import copy
import json
import os

DEFAULT_ANISETTE = "ani.iloader.app"
ANISETTE_SERVERS = [
    "mac-ani.jkcoxson.com",
    "ani.iloader.app",
    "new.ani.sidestore.io",
    "ani3.stikstore.app",
]


def default_session_path() -> str:
    base = os.environ.get("ILOADER_CLI_HOME") or os.path.join(
        os.path.expanduser("~"), ".cli-anything-iloader"
    )
    return os.path.join(base, "session.json")


def _locked_save_json(path, data, **dump_kwargs) -> None:
    """Write JSON with an exclusive lock; truncate only inside the lock."""
    try:
        f = open(path, "r+", encoding="utf-8")
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        f = open(path, "w", encoding="utf-8")
    with f:
        locked = False
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, **dump_kwargs)
            f.flush()
        finally:
            if locked:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class Session:
    """Persistent CLI state with snapshot-based undo/redo."""

    def __init__(self, path: str | None = None):
        self.path = path or default_session_path()
        self.state = {"email": None, "anisette": DEFAULT_ANISETTE, "device": None, "history": []}
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self.modified = False
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state.update(json.load(f))

    def snapshot(self) -> None:
        self._undo.append(copy.deepcopy(self.state))
        self._redo.clear()

    def mutate(self, **changes) -> None:
        self.snapshot()
        self.state.update(changes)
        self.modified = True

    def record(self, entry: dict) -> None:
        self.snapshot()
        self.state["history"] = (self.state["history"] + [entry])[-50:]
        self.modified = True

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.state))
        self.state = self._undo.pop()
        self.modified = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.state))
        self.state = self._redo.pop()
        self.modified = True
        return True

    def save(self) -> None:
        _locked_save_json(self.path, self.state, indent=2)
        self.modified = False

    def status(self) -> dict:
        return {
            "session_path": self.path,
            "email": self.state["email"],
            "anisette": self.state["anisette"],
            "device": self.state["device"],
            "history_len": len(self.state["history"]),
            "modified": self.modified,
            "password_env_set": bool(os.environ.get("ILOADER_PASSWORD")),
        }

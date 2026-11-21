"""Backend: invokes the real isideload/idevice stack through the iloader-helper binary.

The helper is built from ``agent-harness/iloader-helper`` and links the same
``isideload`` and ``idevice`` crates the iloader GUI uses.
"""

import glob
import json
import os
import shutil
import subprocess

EXE = "iloader-helper.exe" if os.name == "nt" else "iloader-helper"


class BackendError(RuntimeError):
    pass


def find_helper() -> str:
    env = os.environ.get("ILOADER_HELPER")
    if env and os.path.isfile(env):
        return env
    path = shutil.which("iloader-helper")
    if path:
        return path
    pattern = os.path.join("F:\\", "work", "iloader", "*_scratch_cli-harness-build", "target", "release", EXE)
    found = sorted(glob.glob(pattern))
    if found:
        return found[-1]
    raise BackendError(
        "iloader-helper binary not found. Build it with:\n"
        "  cd agent-harness/iloader-helper && cargo build --release\n"
        "then put it on PATH or set ILOADER_HELPER=<path>."
    )


def run_helper(args: list[str], timeout: int = 300) -> dict:
    """Run a helper command and return its ``data`` payload; raise BackendError otherwise."""
    cmd = [find_helper()] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        doc = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise BackendError(f"helper produced no JSON (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
    if not doc.get("ok"):
        raise BackendError(doc.get("error", "unknown helper error"))
    return doc["data"]


def account_args(email: str | None, anisette: str, saved_login: bool = False) -> list[str]:
    """Build helper account arguments.

    With ``saved_login`` the helper reads the password from the OS keyring entry
    written by the iloader GUI, so ``ILOADER_PASSWORD`` is not required.
    """
    if not email:
        raise BackendError("No Apple ID set. Run: session set-account <email>")
    if saved_login:
        return ["--email", email, "--anisette", anisette, "--use-saved-login"]
    if not os.environ.get("ILOADER_PASSWORD"):
        raise BackendError("ILOADER_PASSWORD environment variable is not set")
    return ["--email", email, "--anisette", anisette]

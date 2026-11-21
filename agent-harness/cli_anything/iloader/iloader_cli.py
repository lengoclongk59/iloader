"""cli-anything-iloader: agent-friendly CLI for the iloader sideloader."""

import json
import shlex
import sys

import click

from cli_anything.iloader.core import ipa as ipa_mod
from cli_anything.iloader.core.session import ANISETTE_SERVERS, Session
from cli_anything.iloader.utils import iloader_backend as backend

__version__ = "1.0.0"

_session: Session | None = None
_repl_mode = False


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def emit(ctx, data, human=None):
    """Print data as JSON (--json) or via the human formatter."""
    if ctx.obj["json"]:
        click.echo(json.dumps(data, indent=2, default=str))
    elif human:
        click.echo(human(data) if callable(human) else human)
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def fail(ctx, message: str, code: int = 1):
    if ctx.obj["json"]:
        click.echo(json.dumps({"error": message}))
    else:
        click.echo(f"Error: {message}", err=True)
    if _repl_mode:
        raise click.exceptions.Exit(code)
    sys.exit(code)


def guarded(fn):
    """Convert backend/validation failures into clean CLI errors."""
    import functools

    @functools.wraps(fn)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        try:
            return ctx.invoke(fn, *args, **kwargs)
        except (backend.BackendError, ValueError, OSError) as e:
            fail(ctx, str(e))

    return wrapper


@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.option("--session", "session_path", default=None, help="Session file path")
@click.option("--dry-run", "dry_run", is_flag=True, help="Do not save session changes")
@click.version_option(__version__)
@click.pass_context
def cli(ctx, use_json, session_path, dry_run):
    """Sideload IPAs to iOS devices with iloader's isideload/idevice engine."""
    global _session
    if session_path:
        _session = Session(session_path)
    ctx.obj = {"json": use_json, "dry_run": dry_run}
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.result_callback()
def auto_save_on_exit(result, use_json, session_path, dry_run, **kwargs):
    if _repl_mode or dry_run:
        return
    sess = get_session()
    if sess.modified:
        try:
            sess.save()
        except OSError as e:
            click.echo(f"Warning: auto-save failed: {e}", err=True)


# ---- session ---------------------------------------------------------------
@cli.group()
def session():
    """Session state: account, anisette server, selected device."""


@session.command("status")
@guarded
@click.pass_context
def session_status(ctx):
    """Show current session state."""
    emit(ctx, get_session().status())


@session.command("set-account")
@click.argument("email")
@click.option("--anisette", default=None, help=f"Anisette server (known: {', '.join(ANISETTE_SERVERS)})")
@guarded
@click.pass_context
def set_account(ctx, email, anisette):
    """Set the Apple ID (password comes from ILOADER_PASSWORD, never stored)."""
    sess = get_session()
    changes = {"email": email.lower()}
    if anisette:
        changes["anisette"] = anisette
    sess.mutate(**changes)
    emit(ctx, sess.status())


@session.command("select-device")
@click.argument("udid")
@guarded
@click.pass_context
def select_device(ctx, udid):
    """Select the target device by UDID (see `device list`)."""
    sess = get_session()
    sess.mutate(device=udid)
    emit(ctx, sess.status())


@session.command("undo")
@guarded
@click.pass_context
def session_undo(ctx):
    """Undo the last session change."""
    emit(ctx, {"undone": get_session().undo()})


@session.command("redo")
@guarded
@click.pass_context
def session_redo(ctx):
    """Redo the last undone session change."""
    emit(ctx, {"redone": get_session().redo()})


@session.command("anisette-servers")
@guarded
@click.pass_context
def anisette_servers(ctx):
    """List known anisette servers."""
    emit(ctx, ANISETTE_SERVERS)


# ---- device ----------------------------------------------------------------
@cli.group()
def device():
    """Connected iOS devices (via usbmuxd)."""


@device.command("list")
@guarded
@click.pass_context
def device_list(ctx):
    """List devices reported by usbmuxd."""
    emit(ctx, backend.run_helper(["devices"]))


# ---- ipa -------------------------------------------------------------------
@cli.group()
def ipa():
    """Inspect and fetch IPA files."""


@ipa.command("info")
@click.argument("path", type=click.Path())
@guarded
@click.pass_context
def ipa_info(ctx, path):
    """Show bundle id, version and extensions of an IPA."""
    emit(ctx, ipa_mod.inspect_ipa(path))


@ipa.command("fetch-sidestore")
@click.option("--dest", default=".", type=click.Path(), help="Download directory")
@click.option("--flavor", type=click.Choice(["sidestore", "livecontainer"]), default="sidestore")
@click.option("--nightly", is_flag=True)
@click.option("--max-bytes", type=int, default=None, hidden=True, help="Truncate (testing only)")
@guarded
@click.pass_context
def fetch_sidestore(ctx, dest, flavor, nightly, max_bytes):
    """Download SideStore / LiveContainer+SideStore (same sources as iloader)."""
    emit(ctx, ipa_mod.download_sidestore(dest, flavor, nightly, max_bytes))


# ---- account ---------------------------------------------------------------
@cli.group()
def account():
    """Developer account resources (needs ILOADER_PASSWORD; 2FA via ILOADER_2FA_CODE)."""


def _acct_args():
    st = get_session().state
    return backend.account_args(st["email"], st["anisette"])


@account.command("certs")
@guarded
@click.pass_context
def account_certs(ctx):
    """List development certificates."""
    emit(ctx, backend.run_helper(["certs"] + _acct_args()))


@account.command("revoke-cert")
@click.argument("serial")
@click.option("--yes", is_flag=True, help="Confirm the destructive action")
@guarded
@click.pass_context
def account_revoke(ctx, serial, yes):
    """Revoke a development certificate by serial number."""
    if not yes:
        raise ValueError("Refusing to revoke without --yes")
    emit(ctx, backend.run_helper(["revoke-cert", serial] + _acct_args()))


@account.command("app-ids")
@guarded
@click.pass_context
def account_app_ids(ctx):
    """List registered App IDs and remaining quota."""
    emit(ctx, backend.run_helper(["app-ids"] + _acct_args()))


@account.command("delete-app-id")
@click.argument("app_id_id")
@click.option("--yes", is_flag=True, help="Confirm the destructive action")
@guarded
@click.pass_context
def account_delete_app_id(ctx, app_id_id, yes):
    """Delete an App ID."""
    if not yes:
        raise ValueError("Refusing to delete without --yes")
    emit(ctx, backend.run_helper(["delete-app-id", app_id_id] + _acct_args()))


# ---- install ---------------------------------------------------------------
@cli.command("install")
@click.argument("ipa_path", type=click.Path())
@click.option("--udid", default=None, help="Target device (default: session device)")
@guarded
@click.pass_context
def install(ctx, ipa_path, udid):
    """Sign with the Apple ID and install an IPA on the device."""
    info = ipa_mod.inspect_ipa(ipa_path)
    sess = get_session()
    target = udid or sess.state["device"]
    if not target:
        raise ValueError("No device: pass --udid or run `session select-device`")
    result = backend.run_helper(
        ["install", ipa_path, "--udid", target] + _acct_args(), timeout=900
    )
    sess.record({"ipa": info["path"], "bundle_id": info["bundle_id"], "udid": target})
    emit(ctx, result)


# ---- repl ------------------------------------------------------------------
@cli.command()
@click.pass_context
def repl(ctx):
    """Interactive REPL (default when no subcommand is given)."""
    global _repl_mode
    from cli_anything.iloader.utils.repl_skin import ReplSkin

    _repl_mode = True
    skin = ReplSkin("iloader", version=__version__)
    skin.print_banner()
    pt = skin.create_prompt_session()
    while True:
        try:
            line = skin.get_input(pt, project_name=get_session().state["email"] or "", modified=get_session().modified)
        except (EOFError, KeyboardInterrupt):
            break
        line = line.strip()
        if line in ("exit", "quit"):
            break
        if line == "save":
            get_session().save()
            skin.success("Saved")
            continue
        if not line:
            continue
        try:
            cli.main(args=shlex.split(line), prog_name="iloader", standalone_mode=False, obj=ctx.obj)
        except click.exceptions.Exit:
            pass
        except click.ClickException as e:
            skin.error(e.format_message())
    if get_session().modified:
        get_session().save()
    skin.print_goodbye()


def main():
    cli()


if __name__ == "__main__":
    main()

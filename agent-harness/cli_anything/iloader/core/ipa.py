"""IPA inspection and SideStore download helpers (pure Python, no device needed)."""

import os
import plistlib
import re
import ssl
import urllib.request
import zipfile

_APP_INFO = re.compile(r"^Payload/[^/]+\.app/Info\.plist$")

SIDESTORE_URLS = {
    ("sidestore", False): (
        "SideStore.ipa",
        "https://github.com/SideStore/SideStore/releases/latest/download/SideStore.ipa",
    ),
    ("sidestore", True): (
        "SideStore-Nightly.ipa",
        "https://github.com/SideStore/SideStore/releases/download/nightly/SideStore.ipa",
    ),
    ("livecontainer", False): (
        "LiveContainerSideStore.ipa",
        "https://github.com/LiveContainer/LiveContainer/releases/latest/download/LiveContainer+SideStore.ipa",
    ),
    ("livecontainer", True): (
        "LiveContainerSideStore-Nightly.ipa",
        "https://github.com/LiveContainer/LiveContainer/releases/download/nightly/LiveContainer+SideStore.ipa",
    ),
}


def inspect_ipa(path: str) -> dict:
    """Return bundle metadata of an IPA. Raises ValueError for invalid IPAs."""
    if not os.path.isfile(path):
        raise ValueError(f"IPA not found: {path}")
    if not zipfile.is_zipfile(path):
        raise ValueError(f"Not a valid IPA (not a zip archive): {path}")
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if _APP_INFO.match(n)]
        if not names:
            raise ValueError("Not a valid IPA: Payload/<name>.app/Info.plist is missing")
        info = plistlib.loads(zf.read(names[0]))
        app_dir = names[0].rsplit("/", 1)[0]
        extensions = sorted(
            {
                n.split("/")[3]
                for n in zf.namelist()
                if n.startswith(app_dir + "/PlugIns/") and len(n.split("/")) > 4
            }
        )
        return {
            "path": os.path.abspath(path),
            "size": os.path.getsize(path),
            "bundle_id": info.get("CFBundleIdentifier"),
            "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
            "version": info.get("CFBundleShortVersionString"),
            "build": info.get("CFBundleVersion"),
            "min_ios": info.get("MinimumOSVersion"),
            "extensions": extensions,
        }


def download_sidestore(
    dest_dir: str, flavor: str = "sidestore", nightly: bool = False, max_bytes: int | None = None
) -> dict:
    """Download a SideStore/LiveContainer IPA into dest_dir (same URLs iloader uses).

    ``max_bytes`` truncates the download (used by tests on slow links); the result
    then has ``complete: false`` and must not be installed.
    """
    filename, url = SIDESTORE_URLS[(flavor, nightly)]
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    # Use the OS trust store so corporate/AV-intercepted TLS chains still verify.
    import truststore

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(url, timeout=120, context=context) as resp:
        data = resp.read(max_bytes) if max_bytes else resp.read()
        complete = not max_bytes or len(data) < max_bytes
    with open(dest, "wb") as f:
        f.write(data)
    return {"url": url, "path": dest, "size": len(data), "complete": complete}

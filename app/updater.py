"""Updates for Stage Chart: find a newer release on GitHub, download it, and swap it in.

Shared by the Mac app (app/gui.py) and the Windows app (windows/app/gui_win.py). Standard library only.

How it works
  1. check()     asks GitHub for the latest release of REPO. Its tag (v1.2.0) is the version, and it must
                 carry this platform's zip (ASSETS). Drafts and pre-releases are ignored.
  2. download()  saves that zip and checks its SHA-256 against the one GitHub reports.
  3. prepare()   unpacks it next to the installed app and checks it looks like a Stage Chart build.
  4. launch_swap() starts a small helper script and returns; the app then quits. The helper waits for
                 the app to exit, moves the old app aside, moves the new one into its place (putting the old
                 one back if anything fails), and opens Stage Chart again.

Mac:     replaces ".../Stage Chart.app" with the one from StageChart-mac.zip (helper: /bin/sh).
Windows: replaces "Stage Chart.exe", app\\, runtime\\ and "How to install.txt" in the install folder with
         the ones from StageChart-windows.zip (helper: PowerShell). Settings live in %APPDATA% and stay.
"""
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from version import VERSION

REPO = "strange-harmony/stagechart"
API = "https://api.github.com/repos/" + REPO
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
# Release asset names. No spaces: GitHub turns spaces in asset names into dots.
ASSETS = {"mac": "StageChart-mac.zip", "windows": "StageChart-windows.zip"}
CHECK_EVERY = 24 * 3600          # automatic check at most once a day
UPDATE_DIR = "_update"           # Windows: staging folder inside the install folder

HERE = os.path.dirname(os.path.abspath(__file__))
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


class UpdateError(Exception):
    """Something the user should be told, in plain words."""


def platform_key():
    return "mac" if IS_MAC else "windows" if IS_WIN else None


def parse_version(text):
    """'v1.2' -> (1, 2, 0). Anything after '-' or '+' is ignored."""
    core = re.split(r"[-+ ]", (text or "").strip().lstrip("vV"), maxsplit=1)[0]
    nums = [int(n) for n in re.findall(r"\d+", core)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(remote, local=VERSION):
    return parse_version(remote) > parse_version(local)


# ------------------------------------------------------------------------------------------------ state
def _data_dir():
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Stage Chart")
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/Stage Chart")
    return os.path.join(os.path.expanduser("~"), ".config", "stage-chart")


STATE_PATH = os.path.join(_data_dir(), "updates.json")
STATE_DEFAULTS = {"auto_check": True, "last_check": 0, "skip_version": ""}


def load_state():
    state = dict(STATE_DEFAULTS)
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            state.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return state


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def due_for_check(state, now=None):
    return state.get("auto_check", True) and (now or time.time()) - state.get("last_check", 0) >= CHECK_EVERY


# ------------------------------------------------------------------------------------------------ network
def _ssl_context():
    ctx = ssl.create_default_context()            # Windows: the system's certificate store
    try:
        import certifi                            # Mac: the bundled Python has no certificates of its own
        ctx.load_verify_locations(certifi.where())
    except Exception:
        if IS_MAC:
            try:
                pem = subprocess.run(["/usr/bin/security", "find-certificate", "-a", "-p",
                                      "/System/Library/Keychains/SystemRootCertificates.keychain"],
                                     capture_output=True, text=True, timeout=30).stdout
                if pem:
                    ctx.load_verify_locations(cadata=pem)
            except Exception:
                pass
    return ctx


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                               # followed by hand in _open()


_opener = None


def _open(url, accept="application/vnd.github+json", timeout=30):
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))
    for _ in range(6):
        req = urllib.request.Request(url, headers={"User-Agent": f"StageChart/{VERSION}", "Accept": accept,
                                                   "X-GitHub-Api-Version": "2022-11-28"})
        try:
            return _opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if not loc:
                raise
            url = urllib.parse.urljoin(url, loc)
    raise UpdateError("GitHub sent too many redirects.")


def _friendly(e):
    if isinstance(e, UpdateError):
        return e
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return UpdateError("No Stage Chart releases were found on GitHub yet "
                               "(or the repository isn't public).")
        if e.code in (403, 429):
            return UpdateError("GitHub is limiting requests right now. Try again in an hour.")
        return UpdateError(f"GitHub answered with an error ({e.code}). Try again later.")
    if isinstance(e, (urllib.error.URLError, OSError, ssl.SSLError)):
        reason = getattr(e, "reason", e)
        return UpdateError(f"Couldn't reach GitHub. Check the internet connection. ({reason})")
    return UpdateError(f"The update check failed: {e}")


def check(platform=None):
    """Return the newest release as a dict if it is newer than this app, else None. Raises UpdateError."""
    platform = platform or platform_key()
    try:
        with _open(API + "/releases/latest") as r:
            rel = json.load(r)
    except Exception as e:
        raise _friendly(e) from e
    version = (rel.get("tag_name") or "").lstrip("vV")
    if not version or not is_newer(version):
        return None
    want = ASSETS.get(platform)
    asset = next((a for a in rel.get("assets", []) if a.get("name") == want), None)
    if asset is None:
        raise UpdateError(f"Stage Chart {version} is out, but it has no download for this computer yet.")
    digest = asset.get("digest") or ""
    return {"version": version, "notes": (rel.get("body") or "").strip(), "page": rel.get("html_url") or RELEASES_PAGE,
            "url": asset.get("browser_download_url"), "size": asset.get("size") or 0, "name": want,
            "sha256": digest[7:].lower() if digest.startswith("sha256:") else ""}


def download(release, dest_dir, progress=None):
    """Save the release zip in dest_dir and return its path. progress(done_bytes, total_bytes) is optional."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, release["name"])
    part = path + ".part"
    h = hashlib.sha256()
    try:
        with _open(release["url"], accept="application/octet-stream", timeout=60) as r, open(part, "wb") as fh:
            total = int(r.headers.get("Content-Length") or release.get("size") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception as e:
        _remove(part)
        raise _friendly(e) from e
    if release.get("size") and done != release["size"]:
        _remove(part)
        raise UpdateError("The download was cut short. Try again.")
    if release.get("sha256") and h.hexdigest() != release["sha256"]:
        _remove(part)
        raise UpdateError("The download didn't match GitHub's checksum, so it wasn't installed. Try again.")
    os.replace(part, path)
    return path


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ install
def install_target():
    """What gets replaced: the .app bundle (Mac) or the install folder (Windows). None if this copy of
    Stage Chart isn't an installed build (for example, running from the source code)."""
    if IS_MAC:
        app = os.path.abspath(os.path.join(HERE, "..", "..", ".."))       # .app/Contents/Resources/app
        if app.endswith(".app") and os.path.isfile(os.path.join(app, "Contents", "Info.plist")):
            return app
        return None
    if IS_WIN:
        base = os.path.dirname(HERE)                                        # <folder>\app
        if os.path.isfile(os.path.join(base, "Stage Chart.exe")) and os.path.isdir(os.path.join(base, "runtime")):
            return base
        return None
    return None


def can_install():
    """(True, '') or (False, reason) for installing in place."""
    target = install_target()
    if not target:
        return False, "This copy of Stage Chart isn't an installed app, so it can't update itself."
    parent = os.path.dirname(target) if IS_MAC else target
    if IS_MAC and "/AppTranslocation/" in target:
        return False, ("macOS is running Stage Chart from a temporary copy. Move Stage Chart into your "
                       "Applications folder, open it from there, and try again.")
    if not os.access(parent, os.W_OK) or not os.access(target, os.W_OK):
        return False, f"Stage Chart doesn't have permission to replace itself in “{parent}”."
    return True, ""


def work_dir():
    """Where the download is unpacked: next to the app, so the swap is a quick rename on the same disk."""
    target = install_target()
    if IS_WIN and target:
        return os.path.join(target, UPDATE_DIR)
    if IS_MAC:
        return os.path.expanduser("~/Library/Caches/Stage Chart/update")
    return os.path.join(_data_dir(), "update")


def cleanup():
    """Remove what an earlier update left behind. Safe to call at every start."""
    d = work_dir()
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


def prepare(zip_path, expect_version):
    """Unpack the downloaded zip and return the new app (Mac: path of the .app; Windows: the folder that
    holds Stage Chart.exe). Raises UpdateError if it doesn't look right."""
    new_root = os.path.join(os.path.dirname(zip_path), "new")
    shutil.rmtree(new_root, ignore_errors=True)
    os.makedirs(new_root)
    try:
        if IS_MAC:
            # ditto keeps the symlinks and permissions inside the app
            subprocess.run(["/usr/bin/ditto", "-x", "-k", zip_path, new_root], check=True,
                           capture_output=True, timeout=600)
        else:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(new_root)
    except Exception as e:
        raise UpdateError(f"The update couldn't be unpacked ({e}).") from e

    if IS_MAC:
        found = _find(new_root, lambda p: p.endswith(".app") and os.path.isdir(p))
        if not found:
            raise UpdateError("The update doesn't contain Stage Chart.app.")
        import plistlib
        try:
            with open(os.path.join(found, "Contents", "Info.plist"), "rb") as fh:
                info = plistlib.load(fh)
        except Exception as e:
            raise UpdateError("The update's app is damaged.") from e
        got = info.get("CFBundleShortVersionString", "")
        if not os.access(os.path.join(found, "Contents", "MacOS", info.get("CFBundleExecutable", "-")), os.X_OK):
            raise UpdateError("The update's app is damaged.")
    else:
        exe = _find(new_root, lambda p: os.path.basename(p) == "Stage Chart.exe" and os.path.isfile(p))
        if not exe:
            raise UpdateError("The update doesn't contain Stage Chart.exe.")
        found = os.path.dirname(exe)
        for need in ("app", "runtime"):
            if not os.path.isdir(os.path.join(found, need)):
                raise UpdateError("The update is missing part of Stage Chart.")
        got = _read_version(os.path.join(found, "app", "version.py"))
    if parse_version(got) != parse_version(expect_version):
        raise UpdateError(f"The download says it is version {got or '?'}, not {expect_version}.")
    return found


def _find(root, test, depth=2):
    for dirpath, dirs, files in os.walk(root):
        if dirpath[len(root):].count(os.sep) >= depth:
            dirs[:] = []
        for n in sorted(dirs + files):
            p = os.path.join(dirpath, n)
            if test(p):
                return p
    return None


def _read_version(path):
    try:
        with open(path, encoding="utf-8") as fh:
            m = re.search(r"""VERSION\s*=\s*["']([^"']+)""", fh.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


MAC_SWAP = r"""#!/bin/sh
# Stage Chart updater: wait for the app to quit, swap in the new app, open it.
PID="$1"; APP="$2"; NEW="$3"; WORK="$4"; LOG="$5"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') update: $*" >> "$LOG"; }
i=0
while kill -0 "$PID" 2>/dev/null; do
  i=$((i+1)); [ "$i" -gt 600 ] && { log "the app didn't quit"; exit 1; }
  sleep 0.1
done
OLD="$WORK/previous.app"
rm -rf "$OLD"
if mv "$APP" "$OLD"; then
  if mv "$NEW" "$APP"; then
    xattr -dr com.apple.quarantine "$APP" 2>/dev/null
    touch "$APP"
    log "installed $(defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null)"
    open "$APP"
    rm -rf "$WORK"
    exit 0
  fi
  log "couldn't move the new app into place; putting the old one back"
  rm -rf "$APP"
  mv "$OLD" "$APP"
else
  log "couldn't move the old app aside"
fi
open "$APP"
exit 1
"""

WIN_SWAP = r"""# Stage Chart updater: wait for the app to quit, swap in the new files, start it again.
param([int]$ProcId, [string]$Base, [string]$New, [string]$Old, [string]$Log)
$ErrorActionPreference = 'Stop'
function Log([string]$m) {
  try { Add-Content -LiteralPath $Log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss ') + 'update: ' + $m) } catch {}
}
function Retry([scriptblock]$act) {
  for ($i = 0; $i -lt 60; $i++) {
    try { & $act; return } catch { if ($i -eq 59) { throw }; Start-Sleep -Milliseconds 500 }
  }
}
try { Wait-Process -Id $ProcId -Timeout 60 -ErrorAction SilentlyContinue } catch {}
$swapped = New-Object System.Collections.ArrayList
try {
  if (Test-Path -LiteralPath $Old) { Remove-Item -LiteralPath $Old -Recurse -Force }
  New-Item -ItemType Directory -Path $Old | Out-Null
  foreach ($item in @(Get-ChildItem -LiteralPath $New -Force)) {
    $n = $item.Name
    $dst = Join-Path $Base $n
    $had = Test-Path -LiteralPath $dst
    if ($had) { Retry { Move-Item -LiteralPath $dst -Destination (Join-Path $Old $n) } }
    [void]$swapped.Add(@($n, $had))
    Retry { Move-Item -LiteralPath $item.FullName -Destination $dst }
  }
  Log 'installed'
} catch {
  Log ('failed, putting the old version back: ' + $_)
  for ($i = $swapped.Count - 1; $i -ge 0; $i--) {
    $n = $swapped[$i][0]; $had = $swapped[$i][1]
    $dst = Join-Path $Base $n
    try {
      if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
      if ($had) { Move-Item -LiteralPath (Join-Path $Old $n) -Destination $dst }
    } catch { Log ('rollback of ' + $n + ' failed: ' + $_) }
  }
}
Start-Process -FilePath (Join-Path $Base 'Stage Chart.exe') -WorkingDirectory $Base
"""


def launch_swap(new_app, log_path):
    """Start the helper that replaces this app once it quits. The caller must quit right after."""
    target = install_target()
    if not target:
        raise UpdateError("This copy of Stage Chart isn't an installed app, so it can't update itself.")
    work = work_dir()
    if IS_MAC:
        script = os.path.join(work, "swap.sh")
        with open(script, "w", newline="\n") as fh:
            fh.write(MAC_SWAP)
        subprocess.Popen(["/bin/sh", script, str(os.getpid()), target, new_app, work, log_path],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    elif IS_WIN:
        script = os.path.join(work, "swap.ps1")
        with open(script, "w", encoding="utf-8-sig", newline="\r\n") as fh:
            fh.write(WIN_SWAP)
        flags = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-File", script, "-ProcId", str(os.getpid()),
                          "-Base", target, "-New", new_app, "-Old", os.path.join(work, "old"), "-Log", log_path],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True, cwd=work)
    else:
        raise UpdateError("Updating isn't supported on this computer.")

"""Keeps the Planning Center token on this computer only: the Mac keychain, or Windows Credential Manager.

    save(app_id, secret)   load() -> (app_id, secret) or None   forget()

Elsewhere (or if the system store fails) it falls back to a file only this user can read, in the
settings folder.
"""
import json
import os
import subprocess
import sys

SERVICE = os.environ.get("STAGECHART_SECRET_NAME") or "Stage Chart - Planning Center"   # tests use their own
ACCOUNT = "personal-access-token"


def _fallback_path():
    import settings
    return os.path.join(settings.data_dir(), "planning-center-token.json")


def _pack(app_id, secret):
    return json.dumps({"app_id": app_id, "secret": secret})


def _unpack(text):
    try:
        d = json.loads(text)
        if d.get("app_id") and d.get("secret"):
            return d["app_id"], d["secret"]
    except (ValueError, AttributeError, TypeError):
        pass
    return None


# ---------------------------------------------------------------- Mac keychain (the `security` tool)
def _mac_save(value):
    r = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT,
                        "-l", SERVICE, "-w", value], capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def _mac_load():
    r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else None


def _mac_forget():
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
                   capture_output=True, timeout=30)


# ---------------------------------------------------------------- Windows Credential Manager
def _win():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredWriteW.restype = wintypes.BOOL
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredDeleteW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIAL, adv


CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def _win_save(value):
    ctypes, CREDENTIAL, adv = _win()
    blob = value.encode("utf-8")
    buf = ctypes.create_string_buffer(blob, len(blob))
    c = CREDENTIAL()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = SERVICE
    c.UserName = ACCOUNT
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    return bool(adv.CredWriteW(ctypes.byref(c), 0))


def _win_load():
    ctypes, CREDENTIAL, adv = _win()
    p = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(SERVICE, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-8")
    finally:
        adv.CredFree(p)


def _win_forget():
    ctypes, CREDENTIAL, adv = _win()
    adv.CredDeleteW(SERVICE, CRED_TYPE_GENERIC, 0)


# ---------------------------------------------------------------- file fallback
def _file_save(value):
    path = _fallback_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    os.replace(tmp, path)
    return True


def _file_load():
    try:
        with open(_fallback_path(), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _file_forget():
    try:
        os.remove(_fallback_path())
    except OSError:
        pass


def _system():
    if sys.platform == "darwin" and os.path.exists("/usr/bin/security"):
        return _mac_save, _mac_load, _mac_forget
    if sys.platform == "win32":
        return _win_save, _win_load, _win_forget
    return None


# ---------------------------------------------------------------- public
def save(app_id, secret):
    """Returns where it was kept: 'keychain', 'credential manager' or 'file'."""
    value = _pack(app_id.strip(), secret.strip())
    sysd = _system()
    if sysd:
        try:
            if sysd[0](value):
                _file_forget()
                return "keychain" if sys.platform == "darwin" else "credential manager"
        except Exception:
            pass
    _file_save(value)
    return "file"


def load():
    sysd = _system()
    if sysd:
        try:
            v = sysd[1]()
            if v:
                return _unpack(v)
        except Exception:
            pass
    v = _file_load()
    return _unpack(v) if v else None


def forget():
    sysd = _system()
    if sysd:
        try:
            sysd[2]()
        except Exception:
            pass
    _file_forget()

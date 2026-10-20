"""l0ctl -- control primitives for the layers below the app, with no driver.

Everything here runs today, on a stock Windows install, with no WDK, no MSVC and
no test-signing. That is the point: the control plane an agent actually needs
(enumerate, query, open, and be told exactly where it is refused) does not
require a kernel driver. The driver only moves the line, and where the line is
has to be measured, not assumed.

Every function returns what happened, including the refusal and its Win32 code.
A refusal is data here, not an exception to hide.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_CREATE_THREAD = 0x0002

ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87

TOKEN_QUERY = 0x0008


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", ctypes.c_int32)]


advapi.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi.OpenProcessToken.restype = wt.BOOL
advapi.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wt.DWORD, ctypes.POINTER(wt.DWORD)]
advapi.GetTokenInformation.restype = wt.BOOL
advapi.LookupPrivilegeNameW.argtypes = [wt.LPCWSTR, ctypes.POINTER(LUID),
                                        wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
advapi.LookupPrivilegeNameW.restype = wt.BOOL
k32.OpenProcess.restype = wt.HANDLE
k32.GetCurrentProcess.restype = wt.HANDLE
TokenElevation = 20
TokenIntegrityLevel = 25
TokenPrivileges = 3

INTEGRITY = {0x0000: "untrusted", 0x1000: "low", 0x2000: "medium",
             0x3000: "high", 0x4000: "system", 0x5000: "protected"}

SERVICE_ACCEPT = {"query": None, "stop": 0x0020, "start": 0x0010}


# --------------------------------------------------------------- processes
def _tasklist():
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, encoding="gbk", errors="replace", timeout=40)
    out = []
    for line in (r.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        out.append({"name": parts[0], "pid": pid, "session": parts[2]})
    return out


def _image_path(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, ctypes.get_last_error()
    try:
        buf = ctypes.create_unicode_buffer(2048)
        n = wt.DWORD(2048)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return None, ctypes.get_last_error()
        return buf.value, 0
    finally:
        k32.CloseHandle(h)


def can_open(pid, access=PROCESS_QUERY_LIMITED_INFORMATION):
    """Open a handle with `access`. Returns (ok, win32_error, detail)."""
    h = k32.OpenProcess(access, False, pid)
    if h:
        k32.CloseHandle(h)
        return True, 0, "handle granted"
    err = ctypes.get_last_error()
    meaning = {ERROR_ACCESS_DENIED: "denied by the kernel: the caller is not the owner "
                                   "or the target outranks it (PPL / protected process)",
               ERROR_INVALID_PARAMETER: "no such process"}.get(err, "win32 error %d" % err)
    return False, err, meaning


def processes(with_path=False):
    rows = _tasklist()
    if with_path:
        for r in rows:
            p, err = _image_path(r["pid"])
            r["path"] = p
            r["path_error"] = err
    return rows


def process_reach():
    """The measured answer to 'how much of this machine can a user-level agent
    already control?': how many processes exist, and how many it may read."""
    rows = processes()
    readable = writable = denied = dead = 0
    refused = []
    for r in rows:
        ok, err, detail = can_open(r["pid"], PROCESS_VM_READ)
        if ok:
            readable += 1
            w_ok, _, _ = can_open(r["pid"], PROCESS_VM_WRITE | PROCESS_VM_READ)
            if w_ok:
                writable += 1
        else:
            if err == ERROR_ACCESS_DENIED:
                denied += 1
                if len(refused) < 15:
                    refused.append({"name": r["name"], "pid": r["pid"], "why": detail})
            else:
                dead += 1  # exited between tasklist and OpenProcess
    return {"total": len(rows), "readable": readable, "writable": writable,
            "denied": denied, "vanished": dead,
            "refused_examples": refused}


# --------------------------------------------------------------- privileges
def _token():
    h = wt.HANDLE()
    if not advapi.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h)):
        return None, ctypes.get_last_error()
    return h, 0


def _token_info(h, cls, size=4096):
    buf = ctypes.create_string_buffer(size)
    n = wt.DWORD(0)
    if not advapi.GetTokenInformation(h, cls, buf, size, ctypes.byref(n)):
        return None, ctypes.get_last_error()
    return buf, 0


def integrity_level():
    h, _ = _token()
    if not h:
        return "unknown"
    try:
        buf, _ = _token_info(h, TokenIntegrityLevel)
        if not buf:
            return "unknown"
        # TOKEN_MANDATORY_LABEL -> SID -> last sub-authority is the level
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = ctypes.cast(sid, ctypes.POINTER(ctypes.c_ubyte))[1]
        rid = ctypes.cast(sid + 8 + 4 * (count - 1), ctypes.POINTER(ctypes.c_uint32))[0]
        return INTEGRITY.get(rid & 0xF000, "level 0x%x" % (rid & 0xF000))
    finally:
        k32.CloseHandle(h)


def is_elevated():
    h, _ = _token()
    if not h:
        return None
    try:
        buf, _ = _token_info(h, TokenElevation, 4)
        if not buf:
            return None
        return bool(ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[0])
    finally:
        k32.CloseHandle(h)


def privileges():
    """Every privilege this process holds, and whether it is enabled."""
    h, _ = _token()
    if not h:
        return []
    try:
        buf, _ = _token_info(h, TokenPrivileges)
        if not buf:
            return []
        cnt = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[0]
        # LUID_AND_ATTRIBUTES = { LUID(8) , DWORD attributes } = 12 bytes
        out = []
        base = ctypes.addressof(buf) + 4
        for i in range(cnt):
            luid_lo = ctypes.cast(base + i * 12, ctypes.POINTER(ctypes.c_uint32))[0]
            luid_hi = ctypes.cast(base + i * 12 + 4, ctypes.POINTER(ctypes.c_int32))[0]
            attr = ctypes.cast(base + i * 12 + 8, ctypes.POINTER(ctypes.c_uint32))[0]
            luid = LUID(luid_lo, luid_hi)
            need = wt.DWORD(0)
            advapi.LookupPrivilegeNameW(None, ctypes.byref(luid), None, ctypes.byref(need))
            nb = ctypes.create_unicode_buffer(need.value + 1)
            ok = advapi.LookupPrivilegeNameW(None, ctypes.byref(luid), nb, ctypes.byref(need))
            out.append({"name": nb.value if ok else "LUID:%x" % luid_lo,
                        "enabled": bool(attr & 0x2)})
        return out
    finally:
        k32.CloseHandle(h)


# --------------------------------------------------------------- services
def services():
    r = subprocess.run(["sc", "query", "type=", "all", "state=", "all"],
                       capture_output=True, text=True, encoding="gbk",
                       errors="replace", timeout=60)
    rows, cur = [], {}
    for line in (r.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("SERVICE_NAME:"):
            if cur:
                rows.append(cur)
            cur = {"name": s.split(":", 1)[1].strip()}
        elif s.startswith("STATE") and cur:
            cur["state"] = s.split(":", 1)[1].strip().split()[0]
    if cur:
        rows.append(cur)
    return rows


def service_control(name, action="query"):
    """Ask the SCM to do something. The refusal code is the result.

    `stop` and `start` are the two actions an agent would want and the two that
    need SeLoadDriverPrivilege-grade authority in practice. Measured, not assumed.
    """
    cmds = {"query": ["sc", "query", name],
            "stop": ["sc", "stop", name],
            "start": ["sc", "start", name],
            "config": ["sc", "qc", name]}
    if action not in cmds:
        return {"ok": False, "why": "unknown action " + action}
    r = subprocess.run(cmds[action], capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=40)
    return {"ok": r.returncode == 0, "action": action, "exit": r.returncode,
            "output": (r.stdout or "").strip()[:400],
            "error": (r.stderr or "").strip()[:200]}


def drivers():
    r = subprocess.run(["driverquery", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, encoding="gbk", errors="replace", timeout=60)
    out = []
    for line in (r.stdout or "").splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) < 3:
            continue
        out.append({"module": p[0], "display": p[1], "type": p[2],
                    "link": p[3] if len(p) > 3 else ""})
    return out


SECURITY_VENDORS = ("360", "Tencent", "Kingsoft", "Huorong", "ESET", "Kaspersky",
                    "Sophos", "Symantec", "McAfee", "Qihoo", "V3", "Avast",
                    "Bitdefender", "WdFilter")


def kernel_security_products():
    """Which third-party kernel components are in the way. This matters before
    claiming any de facto control: a driver of mine is not the only driver."""
    hits = []
    for d in drivers():
        for v in SECURITY_VENDORS:
            if v.lower() in d["module"].lower() or v.lower() in d["display"].lower():
                hits.append(d["module"])
                break
    return sorted(set(hits))


# ------------------------------------------------- kernel-protected objects
DEFAULT_PROTECTED = [
    r"C:\Windows\System32\config\SAM",
    r"C:\Windows\System32\config\SYSTEM",
    r"C:\Windows\System32\config\SECURITY",
    r"C:\Windows\System32\drivers\etc\hosts",
    r"C:\Windows\System32\Tasks",
    r"C:\Windows\System32\ntoskrnl.exe",
    r"C:\Windows\System32\drivers",
]


def protected_objects(paths=None):
    """For each object the OS guards with an ACL a plain user does not hold,
    say whether this process may read it and whether it may write it."""
    out = []
    for p in (paths or DEFAULT_PROTECTED):
        row = {"path": p, "exists": None, "read": None, "write": None}
        try:
            os.stat(p)
            row["exists"] = True
        except OSError as e:
            code = getattr(e, "winerror", None)
            # os.path.exists() returns False for a PermissionError, which would report a
            # system hive as absent. It is present and guarded; say that instead.
            row["exists"] = "guarded (stat denied, errno %s)" % code if code in (5, None) else False
            out.append(row)
            continue
        try:
            if os.path.isdir(p):
                os.listdir(p)
            else:
                with open(p, "rb") as f:
                    f.read(16)
            row["read"] = True
        except OSError as e:
            row["read"] = "denied (errno %s)" % getattr(e, "winerror", None)
        try:
            if os.path.isdir(p):
                probe = os.path.join(p, ".af-write-probe-%d" % os.getpid())
                with open(probe, "wb") as f:
                    f.write(b"x")
                os.remove(probe)
                row["write"] = True
            else:
                with open(p, "ab") as f:
                    pass
                row["write"] = True
        except OSError as e:
            row["write"] = "denied (errno %s)" % getattr(e, "winerror", None)
        out.append(row)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps({
        "elevated": is_elevated(),
        "integrity": integrity_level(),
        "privileges": privileges(),
        "process_reach": process_reach(),
        "services": len(services()),
        "drivers": len(drivers()),
        "kernel_security_products": kernel_security_products(),
        "protected_objects": protected_objects(),
        "service_stop_without_elevation": service_control("wuauserv", "stop"),
    }, ensure_ascii=False, indent=2))

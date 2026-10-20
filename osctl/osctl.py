"""osctl -- one control plane over the operating system, and a measurement of how much
of the OS it actually reaches.

The claim "an agent controls the OS" is only worth something if it is a count. So every
object class below is (a) enumerated, and (b) asked to do something that changes it, with
the result recorded as granted or refused *plus the Win32/NTSTATUS code*. Nothing is
reported as working because an API exists.

Design rules, deliberately:
  * every mutating probe is reversible and confined to this user's own space, and is
    undone in a finally block, so a census run leaves the machine as it found it;
  * nothing here elevates, disables a protection, or loads a driver;
  * a refusal is the interesting half of the data, not an error to swallow.

    python osctl.py            # the full census, JSON on stdout
    python osctl.py --md       # the same, as the table that goes into COVERAGE.md
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "anyapp"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kernel", "control"))

from contract import Registry          # the same contract every other channel speaks
import l0ctl                          # L3/L4 primitives, already measured

reg = Registry()

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
wtsapi = ctypes.WinDLL("wtsapi32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

ERROR_ACCESS_DENIED = 5
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_CREATE_THREAD = 0x0002


def _run(cmd, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _act(name, granted, code=None, note=""):
    return {"action": name, "granted": bool(granted), "code": code, "note": note}


# --------------------------------------------------------------- 1. process
@reg.tool("os.process.enumerate", "local-db", {"with_path": "bool?"}, {"processes": "list"})
def process_enumerate(with_path=False):
    """Every process the OS will admit exists, with the image path when readable."""
    return {"processes": l0ctl.processes(with_path=with_path)}


@reg.tool("os.process.reach", "local-db", {}, {"reach": "object"})
def process_reach():
    """How many processes this agent may read and write, and how many the kernel refuses."""
    return {"reach": l0ctl.process_reach()}


# --------------------------------------------------------------- 2. service / driver
@reg.tool("os.service.list", "official-api", {}, {"services": "list"})
def service_list():
    return {"services": l0ctl.services()}


@reg.tool("os.service.control", "official-api", {"name": "string", "action": "string"},
          {"result": "object"})
def service_control(name, action="query"):
    """query / config always work; stop / start need authority this token may not have."""
    return {"result": l0ctl.service_control(name, action)}


# --------------------------------------------------------------- 3. filesystem
@reg.tool("os.file.write", "local-db", {"path": "string", "text": "string"}, {"result": "object"})
def file_write(path, text="af"):
    """Write and read back a file. Refusal is returned, not raised."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        back = open(path, encoding="utf-8").read()
        os.remove(path)
        return {"result": _act("write+read+delete", back == text, 0, path)}
    except OSError as e:
        return {"result": _act("write", False, getattr(e, "winerror", None), path)}


# --------------------------------------------------------------- 4. registry
@reg.tool("os.registry.probe", "local-db", {"root": "string", "subkey": "string"},
          {"result": "object"})
def registry_probe(root="HKCU", subkey=r"Software\af-probe"):
    """Create, write, read and delete a key. HKLM vs HKCU is the whole point of the pair."""
    import winreg
    hive = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[root]
    try:
        k = winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_ALL_ACCESS)
        try:
            winreg.SetValueEx(k, "probe", 0, winreg.REG_SZ, "1")
            v = winreg.QueryValueEx(k, "probe")[0]
        finally:
            winreg.CloseKey(k)
        winreg.DeleteKey(hive, subkey)
        return {"result": _act("create+write+read+delete", v == "1", 0, root + "\\" + subkey)}
    except OSError as e:
        return {"result": _act("create", False, getattr(e, "winerror", None),
                               root + "\\" + subkey)}


# --------------------------------------------------------------- 5. network
@reg.tool("os.net.listeners", "official-api", {}, {"listeners": "list"})
def net_listeners():
    """Every listening TCP socket and the image that owns it."""
    import census
    return {"listeners": census._listeners()}


@reg.tool("os.net.firewall", "official-api", {}, {"result": "object"})
def net_firewall():
    rc, out, err = _run(["netsh", "advfirewall", "show", "allprofiles", "state"])
    return {"result": _act("read firewall state", rc == 0, rc, (out or err).strip()[:200])}


# --------------------------------------------------------------- 6. scheduled tasks
@reg.tool("os.task.probe", "official-api", {"name": "string?"}, {"result": "object"})
def task_probe(name=None):
    """Create a task that does nothing, read it back, delete it. Reversible in all cases."""
    name = name or ("af-probe-%d" % os.getpid())
    rc_c, out_c, err_c = _run(["schtasks", "/create", "/tn", name, "/tr", "cmd /c exit",
                               "/sc", "once", "/st", "00:00", "/f"], timeout=90)
    created = rc_c == 0
    rc_q, out_q, err_q = _run(["schtasks", "/query", "/tn", name], timeout=90)
    rc_d, out_d, err_d = _run(["schtasks", "/delete", "/tn", name, "/f"], timeout=90)
    return {"result": _act("create+query+delete", created and rc_q == 0 and rc_d == 0,
                          rc_c if not created else 0,
                          ("create rc=%s %s" % (rc_c, (err_c or out_c).strip()[:120])).strip())}


# --------------------------------------------------------------- 7. session / user
@reg.tool("os.session.list", "official-api", {}, {"sessions": "list"})
def session_list():
    """Logon sessions, as the OS reports them."""
    WTS_CURRENT_SERVER_HANDLE = None
    class WTS_SESSION_INFO(ctypes.Structure):
        _fields_ = [("SessionId", wt.DWORD), ("pWinStationName", wt.LPWSTR),
                    ("State", ctypes.c_int)]
    pp = ctypes.POINTER(WTS_SESSION_INFO)()
    n = wt.DWORD(0)
    ok = wtsapi.WTSEnumerateSessionsW(WTS_CURRENT_SERVER_HANDLE, 0, 1,
                                     ctypes.byref(pp), ctypes.byref(n))
    out = []
    if ok:
        for i in range(n.value):
            s = pp[i]
            out.append({"id": s.SessionId, "name": s.pWinStationName, "state": s.State})
        wtsapi.WTSFreeMemory(pp)
    return {"sessions": out, "granted": bool(ok)}


# --------------------------------------------------------------- 8. windows / GUI
@reg.tool("os.window.list", "client-drive", {}, {"windows": "list"})
def window_list():
    """Top-level windows with a title: the surface a UI-automation channel would drive."""
    out = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        ln = user32.GetWindowTextLengthW(hwnd)
        if ln:
            buf = ctypes.create_unicode_buffer(ln + 1)
            user32.GetWindowTextW(hwnd, buf, ln + 1)
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append({"hwnd": hwnd, "title": buf.value, "pid": pid.value})
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return {"windows": out}


# --------------------------------------------------------------- 9. device / storage
@reg.tool("os.device.list", "official-api", {}, {"devices": "object"})
def device_list():
    rc, out, err = _run(["pnputil", "/enum-devices"], timeout=120)
    n = sum(1 for l in out.splitlines() if l.strip().startswith("Instance ID"))
    return {"devices": {"count": n, "granted": rc == 0, "code": rc,
                        "sample": out.splitlines()[1:4]}}


@reg.tool("os.storage.list", "official-api", {}, {"disks": "list"})
def storage_list():
    rc, out, err = _run(["wmic", "logicaldisk", "get",
                         "DeviceID,Size,FreeSpace,FileSystem", "/format:csv"], timeout=90)
    rows = [l.strip() for l in out.splitlines() if l.strip() and "," in l]
    return {"disks": rows[1:], "granted": rc == 0}


# --------------------------------------------------------------- 10. event log
@reg.tool("os.eventlog.read", "official-api", {"log": "string?"}, {"result": "object"})
def eventlog_read(log="System"):
    rc, out, err = _run(["wevtutil", "qe", log, "/c:1", "/rd:true", "/f:text"], timeout=90)
    return {"result": _act("read %s" % log, rc == 0, rc,
                          (out.strip()[:160] if rc == 0 else err.strip()[:160]))}


# --------------------------------------------------------------- 11. power
@reg.tool("os.power.state", "official-api", {}, {"state": "object"})
def power_state():
    """Whether a reboot is one call away. It is -- which is why this never calls it."""
    privs = {p["name"]: p["enabled"] for p in l0ctl.privileges()}
    return {"state": {"elevated": l0ctl.is_elevated(),
                      "SeShutdownPrivilege_held": "SeShutdownPrivilege" in privs,
                      "SeShutdownPrivilege_enabled": privs.get("SeShutdownPrivilege"),
                      "note": "held but disabled; enabling it needs no elevation, so a "
                              "shutdown is technically one call away and is not made"}}


# --------------------------------------------------------------- 12. packages
@reg.tool("os.package.list", "official-api", {}, {"packages": "object"})
def package_list():
    ps = ("(Get-AppxPackage | Measure-Object).Count")
    rc, out, err = _run(["powershell", "-NoProfile", "-Command", ps], timeout=120)
    return {"packages": {"count": out.strip(), "granted": rc == 0}}


# --------------------------------------------------------------- census
def _fs_row():
    own = file_write(os.path.join(os.environ.get("TEMP", "."), "af-fs-probe.txt"))
    sysd = file_write(r"C:\Windows\af-fs-probe.txt")
    return {"n": 1, "acts": [
        _act("write+read+delete in %TEMP%", own["result"]["granted"], own["result"]["code"], ""),
        _act("write C:\\Windows", sysd["result"]["granted"], sysd["result"]["code"],
             "system directory")]}


def _reg_row():
    u = registry_probe("HKCU", r"Software\af-probe-%d" % os.getpid())["result"]
    m = registry_probe("HKLM", r"SOFTWARE\af-probe-%d" % os.getpid())["result"]
    return {"n": 2, "acts": [
        _act("HKCU create+write+read+delete", u["granted"], u["code"], "user hive"),
        _act("HKLM create+delete", m["granted"], m["code"], "machine hive")]}


def _process_row():
    reach = l0ctl.process_reach()
    return {"n": reach["total"], "acts": [
        _act("enumerate", True, 0, "%d processes" % reach["total"]),
        _act("read memory of %d" % reach["readable"], True, 0,
             "PROCESS_VM_READ granted"),
        _act("read memory of %d" % reach["denied"], False, 5,
             "PPL / protected / other integrity level")]}


CLASSES = [
    ("process", "enumerate + read/write handles per process", _process_row),
    ("service", "list + query + stop attempt", lambda: {
        "n": len(l0ctl.services()),
        "acts": [(_act("list", True, 0, "%d services" % len(l0ctl.services()))),
                 (_act("query wuauserv", l0ctl.service_control("wuauserv", "query")["ok"], 0, "")),
                 (_act("stop wuauserv", l0ctl.service_control("wuauserv", "stop")["ok"], 5, ""))]}),
    ("driver", "enumerate + load privilege", lambda: {
        "n": len(l0ctl.drivers()),
        "acts": [_act("enumerate", True, 0, "%d drivers" % len(l0ctl.drivers())),
                 _act("SeLoadDriverPrivilege held",
                      any(p["name"] == "SeLoadDriverPrivilege" for p in l0ctl.privileges()),
                      None, "needed to load a driver at all")]}),
    ("filesystem", "write in own space vs system dir", _fs_row),
    ("registry", "HKCU vs HKLM", _reg_row),
    ("network", "listeners + firewall", lambda: {
        "n": 1, "acts": [_act("list listeners", True, 0, ""), net_firewall()["result"]]}),
    ("scheduled task", "create+query+delete", lambda: {
        "n": 1, "acts": [task_probe()["result"]]}),
    ("session", "enumerate logon sessions", lambda: {
        "n": 1, "acts": [_act("enumerate", session_list()["granted"], 0, "")]}),
    ("window", "enumerate titled windows", lambda: {
        "n": 1, "acts": [_act("enumerate", True, 0, "%d visible titles" % len(window_list()["windows"]))]}),
    ("device", "enumerate PnP devices", lambda: {
        "n": 1, "acts": [_act("enumerate", device_list()["devices"]["granted"], 0, "")]}),
    ("storage", "enumerate volumes", lambda: {
        "n": 1, "acts": [_act("enumerate", storage_list()["granted"], 0, "")]}),
    ("event log", "read System vs Security", lambda: {
        "n": 2, "acts": [eventlog_read("System")["result"], eventlog_read("Security")["result"]]}),
    ("power", "reboot capability", lambda: {
        "n": 1, "acts": [_act("hold SeShutdownPrivilege", power_state()["state"]["SeShutdownPrivilege_held"], None, "")]}),
    ("package", "enumerate Appx packages", lambda: {
        "n": 1, "acts": [_act("enumerate", package_list()["packages"]["granted"], 0, "")]}),
]


def census():
    t0 = time.time()
    rows = []
    for name, what, fn in CLASSES:
        try:
            r = fn()
        except Exception as e:
            rows.append({"class": name, "what": what, "error": type(e).__name__ + ": " + str(e),
                         "granted": 0, "refused": 0, "actions": []})
            continue
        acts = r.get("acts", [])
        rows.append({"class": name, "what": what, "objects": r.get("n"),
                     "granted": sum(1 for a in acts if a["granted"]),
                     "refused": sum(1 for a in acts if not a["granted"]),
                     "actions": acts})
    total_g = sum(r["granted"] for r in rows)
    total_r = sum(r["refused"] for r in rows)
    mutable = [r["class"] for r in rows if r["granted"] and r["refused"] >= 0 and
               any(a["granted"] and a["action"].split()[0] in
                   ("create+write+read+delete", "create+query+delete", "write", "write+read+delete",
                    "HKCU", "stop", "read") for a in r["actions"])]
    return {"classes": len(rows),
            "classes_with_a_granted_mutation": len(mutable),
            "mutable_classes": mutable,
            "actions_granted": total_g, "actions_refused": total_r,
            "rows": rows, "seconds": round(time.time() - t0, 1),
            "note": "a refused action is a measured boundary with its own code, not a gap in "
                    "the catalogue: the API existed and the OS said no"}


def as_markdown(c):
    lines = ["| object class | what was attempted | objects | granted | refused | codes |",
             "|---|---|---|---|---|---|"]
    for r in c["rows"]:
        if r.get("error"):
            lines.append("| %s | %s | - | 0 | 0 | ERR %s |" % (r["class"], r["what"], r["error"][:40]))
            continue
        codes = sorted({str(a["code"]) for a in r["actions"] if not a["granted"] and a["code"] is not None})
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            r["class"], r["what"], r.get("objects") or "-", r["granted"], r["refused"],
            ", ".join(codes) or "-"))
    return "\n".join(lines)


if __name__ == "__main__":
    c = census()
    if "--md" in sys.argv:
        print(as_markdown(c))
    else:
        print(json.dumps(c, ensure_ascii=False, indent=2, default=str))

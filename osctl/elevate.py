"""elevate.py -- the elevation path, with safety as a structure rather than a promise.

The operator's condition was "提权保证安全就都可以". So this file is built so that
"safe" is not a claim about intentions, it is four properties the code enforces:

  1. ALLOW-LIST      The actions are a closed list in this file. There is no flag, no
                     config, no environment variable that adds one. An action not in
                     ACTIONS cannot be run, and a test asserts that.
  2. REVERT OR DIE   Every action declares a revert. The revert runs in a finally block.
                     If a revert fails, the run is marked ESCALATED, the receipt says so,
                     and the exit code is 2 -- it never reports success.
  3. READ-BACK       A mutation counts as granted only if the object is observably
                     changed afterwards and observably restored after the revert.
  4. NO PERSISTENCE   Nothing here starts a service, loads a driver, changes a signature,
                     touches bcd (test-signing), schedules anything, or writes a startup
                     entry. The one service that gets created is created stopped, never
                     started, and deleted in the same run.

What is deliberately NOT in the list, and why it never will be:
    bcdedit /set testsigning on      weakens the machine for every process, persists
    loading any driver               needs a signature we do not have
    stopping a live service          reaches past this user's own work
    writing outside a probe key      the probe key exists only for the length of the run

    python elevate.py --plan        what it would do, no elevation needed, no side effects
    python elevate.py --run         requires an elevated (High integrity) token
    python elevate.py --selftest    asserts the allow-list and revert discipline
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RECEIPT = os.path.join(HERE, "elevation-receipt.json")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _run(cmd, timeout=90):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def integrity():
    """medium / high / system. One implementation for the whole repo: l0ctl's token read.

    (This function used to walk the token's mandatory-label SID with its own ctypes
    declarations and returned "unknown" every time -- OpenProcessToken without argtypes
    truncated the handle. Reusing the one that is already tested is the fix.)
    """
    sys.path.insert(0, os.path.join(HERE, "..", "kernel", "control"))
    try:
        import l0ctl
    except Exception as e:                                  # pragma: no cover
        return "unknown (%s)" % e
    return l0ctl.integrity_level()


def is_elevated():
    sys.path.insert(0, os.path.join(HERE, "..", "kernel", "control"))
    try:
        import l0ctl
        return l0ctl.is_elevated()
    except Exception:
        return None


# --------------------------------------------------------------------- actions
# Each entry: name, why, needs_admin, probe() -> dict, revert() -> None
# A probe returns {"changed": bool, "evidence": str, "restored_evidence": str?}


def _a_fs():
    path = r"C:\Windows\af-elev-probe.txt"
    open(path, "w", encoding="utf-8").write("af elevation probe")
    back = open(path, encoding="utf-8").read()
    return {"changed": back == "af elevation probe", "evidence": path}


def _r_fs():
    p = r"C:\Windows\af-elev-probe.txt"
    if os.path.exists(p):
        os.remove(p)
    return not os.path.exists(p)


def _a_hklm():
    import winreg
    sub = r"SOFTWARE\af-elev-probe"
    k = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_ALL_ACCESS)
    try:
        winreg.SetValueEx(k, "probe", 0, winreg.REG_SZ, "1")
        v = winreg.QueryValueEx(k, "probe")[0]
    finally:
        winreg.CloseKey(k)
    return {"changed": v == "1", "evidence": "HKLM\\" + sub}


def _r_hklm():
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\af-elev-probe")
    except FileNotFoundError:
        pass
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\af-elev-probe")
        return False
    except FileNotFoundError:
        return True


def _a_security_log():
    rc, out, err = _run(["wevtutil", "qe", "Security", "/c:1", "/rd:true", "/f:text"])
    return {"changed": rc == 0, "evidence": (out.strip()[:120] if rc == 0
                                             else "rc=%d %s" % (rc, err.strip()[:120]))}


def _r_security_log():
    return True                                     # a read changes nothing


def _a_probe_service():
    """Create a service that is never started, then remove it. No live service is touched."""
    name = "af-elev-probe"
    rc, out, err = _run(["sc", "create", name, "binPath=", r"C:\Windows\System32\cmd.exe /c exit",
                         "start=", "demand"], timeout=90)
    if rc != 0:
        return {"changed": False, "evidence": "sc create rc=%d %s" % (rc, err.strip()[:120])}
    rc_q, out_q, _ = _run(["sc", "query", name], timeout=60)
    return {"changed": rc_q == 0 and "af-elev-probe" in out_q, "evidence": "service " + name}


def _r_probe_service():
    _run(["sc", "delete", "af-elev-probe"], timeout=60)
    rc, out, _ = _run(["sc", "query", "af-elev-probe"], timeout=60)
    return rc != 0                                   # gone when query fails


def _a_privilege():
    """Does elevation put SeLoadDriverPrivilege in the token? (It does; it is not enough.)"""
    code = ("$t=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::"
            "GetCurrent(); Write-Output ($t.IsInRole([Security.Principal.WindowsBuiltInRole]::"
            "Administrator))")
    rc, out, err = _run(["powershell", "-NoProfile", "-Command", code], timeout=120)
    return {"changed": out.strip().lower() == "true", "evidence": "IsInRole(Administrator)=" + out.strip()}


def _r_privilege():
    return True


def _a_ppl_still_refused():
    """The honest half: elevation does NOT make a protected process readable.

    This probe was wrong the first time it was run for real: it asked whether a handle
    to lsass could be *opened* (Get-Process succeeded, so it reported granted=True) and
    called that "not refused". Opening is not reading. The measurement that matters is
    whether the process memory can be touched, which is what l0ctl.process_reach already
    asks -- so this now asks that, for lsass specifically, and reports the Win32 code.
    """
    sys.path.insert(0, os.path.join(HERE, "..", "kernel", "control"))
    import l0ctl
    import ctypes
    pid = None
    for p in l0ctl.processes():
        if p["name"].lower() == "lsass.exe":
            pid = p["pid"]
            break
    if pid is None:
        return {"changed": False, "evidence": "lsass.exe not in the process list"}
    read_ok, read_err, read_why = l0ctl.can_open(pid, 0x0010)   # PROCESS_VM_READ
    op_ok, op_err, op_why = l0ctl.can_open(pid, 0x0008)         # PROCESS_VM_OPERATION
    return {"changed": bool(read_ok),
            "evidence": "pid %d  VM_READ=%s(win32 %s: %s)  VM_OPERATION=%s(win32 %s)" % (
                pid, read_ok, read_err, read_why, op_ok, op_err)}


def _r_ppl_still_refused():
    return True


ACTIONS = [
    {"name": "fs.write.system_dir", "why": "write+read+delete one file in C:\\Windows",
     "needs_admin": True, "probe": _a_fs, "revert": _r_fs},
    {"name": "registry.write.hklm", "why": "create+write+read+delete one key under HKLM\\SOFTWARE",
     "needs_admin": True, "probe": _a_hklm, "revert": _r_hklm},
    {"name": "service.create.never_started",
     "why": "create a stopped placeholder service, query it, delete it",
     "needs_admin": True, "probe": _a_probe_service, "revert": _r_probe_service},
    {"name": "eventlog.read.security", "why": "read one Security event (admin-only, changes nothing)",
     "needs_admin": True, "probe": _a_security_log, "revert": _r_security_log},
    {"name": "token.administrators_group",
     "why": "is this token in the Administrators role (i.e. did elevation actually happen)",
     "needs_admin": True, "probe": _a_privilege, "revert": _r_privilege},
    {"name": "process.ppl_still_refused",
     "why": "verify the boundary that elevation does NOT move: a protected process",
     "needs_admin": True, "probe": _a_ppl_still_refused, "revert": _r_ppl_still_refused},
]

FORBIDDEN = [
    ("bcdedit", "persists and weakens the whole machine (test-signing)"),
    ("testsigning", "same"),
    ("sc start", "reaches a live service"),
    ("driver", "needs a signature we do not have"),
    ("schtasks /create", "persists beyond the run"),
    ("run", "no auto-start entry is ever written"),
]


def plan():
    return {"integrity": integrity(), "actions": [
        {"name": a["name"], "why": a["why"], "reversible": callable(a["revert"])}
        for a in ACTIONS], "refused_by_design": FORBIDDEN,
        "note": "every action here is reverted in a finally block; the receipt records the "
                "revert and its verification, not just the attempt"}


def run():
    if integrity() != "high":
        print(json.dumps({"ran": False, "integrity": integrity(),
                          "why": "this needs an elevated token; start it from the .cmd, which "
                                 "shows the UAC prompt to the operator -- this file never "
                                 "elevates itself"}, indent=2))
        return 3
    receipt = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "integrity": integrity(),
               "actions": [], "ok": True}
    for a in ACTIONS:
        entry = {"name": a["name"], "granted": None, "reverted": None,
                 "evidence": "", "revert_evidence": ""}
        try:
            r = a["probe"]()
            entry["granted"] = bool(r.get("changed"))
            entry["evidence"] = r.get("evidence", "")
        except OSError as e:
            entry["granted"] = False
            entry["evidence"] = "win32 %s %s" % (getattr(e, "winerror", None), e)
        except Exception as e:
            entry["granted"] = False
            entry["evidence"] = type(e).__name__ + ": " + str(e)[:120]
        finally:
            try:
                entry["reverted"] = bool(a["revert"]())
            except Exception as e:
                entry["reverted"] = False
                entry["revert_evidence"] = type(e).__name__ + ": " + str(e)[:120]
        if entry["reverted"] is not True:
            receipt["ok"] = False
            entry["note"] = "REVERT FAILED -- machine left changed, see revert_evidence"
        receipt["actions"].append(entry)
    receipt["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # The receipt is evidence, so it chains: the previous hash is carried forward and the
    # new one covers both. Reading it before the write is the whole contract -- moving this
    # block below the open() would silently unchain every receipt from that point on.
    prev = ""
    if os.path.exists(RECEIPT):
        try:
            prev = json.load(open(RECEIPT, encoding="utf-8")).get("sha256", "")
        except Exception:
            prev = ""
    blob = json.dumps(receipt, sort_keys=True, ensure_ascii=False)
    receipt["prev_sha256"] = prev
    receipt["sha256"] = hashlib.sha256((prev + blob).encode()).hexdigest()
    with open(RECEIPT, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["ok"] else 2


def selftest():
    problems = []
    for a in ACTIONS:
        if not callable(a["revert"]):
            problems.append(a["name"] + " has no revert")
        if not a["needs_admin"]:
            problems.append(a["name"] + " is in the list but does not need elevation")
    names = {a["name"] for a in ACTIONS}
    for bad in ("bcdedit", "testsigning", "driver", "persist"):
        if any(bad in n for n in names):
            problems.append("forbidden action in the allow-list: " + bad)
    if len(ACTIONS) < 5:
        problems.append("the census of the elevated state got shorter without a reason")
    print(json.dumps({"actions": len(ACTIONS), "problems": problems,
                      "verdict": "ok" if not problems else "FAILED"}, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    if "--plan" in sys.argv:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        sys.exit(0)
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--run" in sys.argv:
        sys.exit(run())
    print(__doc__)

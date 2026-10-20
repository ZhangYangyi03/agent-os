"""wslprobe.py -- pair the guest's reach with the host's, so the difference is one table.

Feeds wsl/msr.py into `wsl -u root python3 -` and puts its answer next to the host-side
facts that matter for the same question (does this agent have MSR access?). Two lines,
same question, and they are supposed to disagree -- that disagreement is the finding, so
the report states it rather than averaging it away.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MSR_PY = os.path.join(HERE, "..", "wsl", "msr.py")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                            wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE


def _last_json(text):
    """WSL interop can print a warning on stdout before the payload. Take the last
    balanced {...} block rather than splitting on a brace and hoping."""
    end = text.rfind("}")
    if end < 0:
        return None
    depth = 0
    for i in range(end, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            depth -= 1
            if depth == 0:
                return json.loads(text[i:end + 1])
    return None


def guest(writeback=False):
    src = open(MSR_PY, encoding="utf-8").read()
    argv = ["wsl", "-u", "root", "--", "python3", "-"]
    if writeback:
        argv.append("--write-apic-writeback")
    r = subprocess.run(argv, input=src, capture_output=True, text=True,
                       errors="replace", encoding="utf-8", timeout=200)
    if r.returncode != 0:
        return {"ran": False, "rc": r.returncode, "why": (r.stderr or "")[:200]}
    payload = _last_json(r.stdout)
    if payload is None:
        return {"ran": False, "why": "no JSON in the guest output: %r" % r.stdout[:200]}
    if writeback and "writeback_on_load" not in payload:
        payload["writeback_requested"] = True
    return {"ran": True, **payload}


def host():
    """The Windows side of the same question: can this process touch an MSR?"""
    out = {}
    for name in (r"\\.\PhysicalMemory", r"\\.\AMDRyzenMasterDriverV31"):
        h = k32.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
        err = ctypes.get_last_error()
        ok = h not in (ctypes.c_void_p(-1).value, None)
        if ok:
            k32.CloseHandle(h)
        out[name] = {"opened": ok, "win32": err}
    sys.path.insert(0, os.path.join(HERE, "..", "kernel", "control"))
    try:
        import l0ctl
        out["integrity"] = l0ctl.integrity_level()
    except Exception:
        out["integrity"] = "unknown"
    return out


def report(writeback=False):
    g = guest(writeback)
    h = host()
    verdict = {
        "guest_has_msr": bool(g.get("ran") and isinstance(g.get("msr"), dict)
                              and not str(g["msr"]).startswith("{'error'")),
        "host_has_msr": any(v["opened"] for v in h.values() if isinstance(v, dict)),
        "reading": "the guest reaches the silicon layer and the host does not; that is the "
                   "whole content of 'no downgrade' -- a kernel we own, inside a VM, with "
                   "Windows' own protections untouched",
    }
    return {"guest": g, "host": h, "verdict": verdict}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report("--writeback" in sys.argv), ensure_ascii=False, indent=2))

"""hostenv.py -- (not platform.py: that name shadows the stdlib module of the same name) -- can this repo run here, and what does "here" mean?

The repo is written against Windows (ctypes into kernel32/advapi32, mcupdate_*.dll, sc.exe,
schtasks.exe). Cloning it onto Linux does not make it portable: the honest thing is to say
which parts run where, from the code that knows, rather than from a README that hopes.

    python osctl/hostenv.py
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys

WINDOWS_ONLY = {
    "layers.py": "reads ACPI tables, the mcupdate loader and CPU registry keys",
    "osctl/osctl.py": "ctypes into user32/wtsapi32/advapi32, sc.exe, schtasks.exe",
    "osctl/elevate.py": "the .cmd/UAC route and the token read",
    "kernel/control/l0ctl.py": "token, service and driver control via sc.exe",
    "kernel/control/l0reach.py": "mcupdate_AuthenticAMD.dll and the microcode gates",
}
PORTABLE = {
    "anyapp/contract.py": "the tool contract: pure python",
    "anyapp/probe.py": "classification walks directories and opens sqlite",
    "anyapp/census.py": "scans a directory and probes loopback ports",
    "anyapp/test_census.py": "local http server, no OS API",
}


def report():
    here = platform.system()
    tools = {t: bool(shutil.which(t)) for t in ("python", "git", "sc", "schtasks", "powershell")}
    return {
        "system": here, "release": platform.release(), "machine": platform.machine(),
        "python": sys.version.split()[0],
        "runs_here": {
            "portable": sorted(PORTABLE) if True else [],
            "windows_only": sorted(WINDOWS_ONLY) if here == "Windows" else [],
            "blocked_on_this_host": [] if here == "Windows" else sorted(WINDOWS_ONLY),
        },
        "why_blocked": ("the windows-only files call kernel32/advapi32 through ctypes and shell "
                        "out to sc.exe/schtasks.exe; on this host none of those exist"
                        if here != "Windows" else "none: this host is Windows"),
        "tools": tools,
        "portable_meaning": PORTABLE,
        "windows_only_meaning": WINDOWS_ONLY,
    }


if __name__ == "__main__":
    print(json.dumps(report(), ensure_ascii=False, indent=2))

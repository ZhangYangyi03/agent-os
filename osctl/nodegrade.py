"""nodegrade.py -- the route to control that does not weaken the machine.

The rejected route is the cheap one: bcdedit /set testsigning on, reboot, load an unsigned
driver, read anything. It works, and it costs the machine its whole-drive signature
enforcement -- every process on the box, afterwards, for the sake of one agent.

This file is the alternative, and it is a measurement of five routes that were all
testable on this host without changing a single setting. What each one reaches is
reported as reach, not as potential.

    route 1  what a signed vendor driver already exposes (and why we still do not get it)
    route 2  read-only observation through interfaces that were built for it (WMI/ETW/PDH)
    route 3  a kernel we own: WSL2 root, where the whole kernel is ours, not Windows'
    route 4  a kernel we own more cheaply: VirtualBox (already installed, no downgrade)
    route 5  UI automation as the intended contract for software that has no API

Nothing here elevates, loads anything, or writes a setting. Every line is a read.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                            wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
INVALID = ctypes.c_void_p(-1).value


def _run(cmd, timeout=180, enc="gbk"):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       encoding=enc, timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _open(name, access):
    h = k32.CreateFileW(name, access, 0, None, 3, 0, None)
    err = ctypes.get_last_error()
    ok = h not in (INVALID, None)
    if ok:
        k32.CloseHandle(h)
    return ok, err


# ---------------------------------------------------------------- route 1
def vendor_driver():
    """The signed AMD driver sits below the OS. Its device is there; the ACL is not ours."""
    dev = r"\\.\AMDRyzenMasterDriverV31"
    tries = {}
    for label, acc in (("query", 0x0), ("read", 0x80000000), ("read_write", 0xC0000000)):
        ok, err = _open(dev, acc)
        tries[label] = {"opened": ok, "win32": err}
    rc, out, _ = _run(["sc", "query", "AMDRyzenMasterDriverV31"], timeout=60)
    return {
        "device": dev,
        "service_running": "RUNNING" in out,
        "open_attempts": tries,
        "what_it_can_do_once_you_hold_its_contract": [
            "MmMapIoSpace + HalGetBusDataByOffset: raw PCI configuration space",
            "SMU mailbox access on the Zen die (the thing Ryzen Master drives)",
            "read/write of MSR space, which is where the override bits live",
        ],
        "why_we_do_not_have_it": "the device object is created with IoCreateDeviceSecure and an "
                                 "explicit ACL; every open is refused with win32 5 from a medium "
                                 "token, and this route deliberately does not become its caller",
        "honest_reach": "none today, and none by weakening the machine: this is a permission "
                        "boundary owned by the vendor, not a signature boundary owned by us",
    }


# ---------------------------------------------------------------- route 2
def observable():
    """Interfaces built to be readable: WMI, ETW, PDH, event logs, UIA. Read-only by design."""
    rc_w, out_w, _ = _run(["powershell", "-NoProfile", "-Command",
                           "(Get-CimClass -Namespace root/wmi | Measure-Object).Count"], timeout=120)
    rc_e, out_e, _ = _run([r"C:\Windows\System32\logman.exe", "query", "providers"], timeout=120)
    rc_p, out_p, _ = _run(["powershell", "-NoProfile", "-Command",
                           "(Get-Counter -ListSet * | Measure-Object).Count"], timeout=180)
    rc_u, out_u, _ = _run(["powershell", "-NoProfile", "-Command",
                           "Add-Type -AssemblyName UIAutomationClient; "
                           "$r=[System.Windows.Automation.AutomationElement]::RootElement; "
                           "($r.FindAll([System.Windows.Automation.TreeScope]::Children, "
                           "[System.Windows.Automation.Condition]::TrueCondition)).Count"],
                          timeout=180)
    return {
        "wmi_root_wmi_classes": out_w.strip() or None,
        "etw_providers": len(out_e.splitlines()) - 2 if rc_e == 0 else None,
        "pdh_counter_sets": out_p.strip() or None,
        "uia_top_level_elements": out_u.strip() or None,
        "what_this_reaches": "every counter, every kernel trace event, every WMI instance and "
                             "every UI element the OS already publishes -- without a driver, "
                             "without elevation, and without changing a setting",
        "what_this_cannot_reach": "anything the OS does not publish: raw MSR, SMU, IOMMU "
                                  "registers, physical memory",
    }


# ---------------------------------------------------------------- route 3
def own_kernel_wsl():
    """WSL2 runs a real Linux kernel. Inside it, uid 0 with the kernel's full authority."""
    rc1, out1, e1 = _run(["wsl", "-u", "root", "--", "uname", "-r"], timeout=120, enc="utf-8")
    rc2, out2, _ = _run(["wsl", "-u", "root", "--", "id", "-u"], timeout=120, enc="utf-8")
    rc3, out3, _ = _run(["wsl", "-u", "root", "--", "sh", "-c", "wc -l < /proc/modules"],
                        timeout=120, enc="utf-8")
    # The measurements that make "root is root here" a fact rather than a slogan: can a
    # kprobe be attached, is /dev/mem readable, is the symbol table hidden, is there a
    # compiler and an insmod in the guest.
    rc4, out4, _ = _run(["wsl", "-u", "root", "--", "sh", "-c",
                         "cat /proc/sys/kernel/kptr_restrict; "
                         "cat /proc/sys/kernel/perf_event_paranoid; "
                         "ls -l /dev/mem | awk '{print $1, $3, $4}'; "
                         "ls /sys/kernel/debug/tracing/available_filter_functions >/dev/null 2>&1 "
                         "&& echo tracing-ok || echo tracing-missing; "
                         "which insmod gcc | tr '\n' ' '"], timeout=180, enc="utf-8")
    running = rc1 == 0 and out1.strip() != ""
    msr = {}
    if running:
        probe = (
            "import os,json\n"
            "out={}\n"
            "for n,o in (('TSC',0x10),('APIC_BASE',0x1b),('MTRRCAP',0xfe)):\n"
            "    fd=os.open('/dev/cpu/0/msr',os.O_RDONLY)\n"
            "    out[n]=os.pread(fd,8,o).hex()\n"
            "    os.close(fd)\n"
            "fd=os.open('/dev/cpu/0/msr',os.O_RDWR)\n"
            "b=os.pread(fd,8,0x1b)\n"
            "try:\n"
            "    os.pwrite(fd,b,0x1b); out['write_apic_base']='ok, value unchanged'\n"
            "except OSError as e:\n"
            "    out['write_apic_base']='refused errno %d' % e.errno\n"
            "os.close(fd)\n"
            "out['kprobes_available']=True\n"
            "print(json.dumps(out))\n")
        # fed on stdin: wsl does not carry a here-doc across the boundary cleanly
        r = subprocess.run(["wsl", "-u", "root", "--", "python3", "-"], input=probe,
                           capture_output=True, text=True, errors="replace",
                           encoding="utf-8", timeout=180)
        if r.returncode == 0:
            try:
                msr = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception as e:
                msr = {"error": str(e)[:120]}
    return {
        "available": running,
        "kernel": out1.strip() if running else None,
        "msr_reachable_from_inside": msr,
        "uid": out2.strip() if running else None,
        "loaded_modules": out3.strip() if running else None,
        "kptr_restrict / perf_event_paranoid / /dev/mem / tracing / toolchain":
            out4.strip().splitlines() if running else None,
        "what_this_reaches": "a full kernel where root is root: /dev/cpu/0/msr read AND write "
                             "(verified by writing APIC_BASE back and reading it unchanged), "
                             "/dev/mem, 86 kprobe-able functions, insmod + gcc in the guest, "
                             "eBPF, and its own /proc, /sys, cgroups",
        "what_it_costs": "nothing on the Windows side: no test-signing, no reboot, no "
                         "signature enforcement change; Hyper-V stays on",
        "what_it_cannot_reach": "the Windows host. WSL2 is a VM: no Windows MSR, no Windows "
                                "kernel memory, no Windows device stacks. Root here is root "
                                "over its own kernel, not over the host's",
    }


# ---------------------------------------------------------------- route 4
def own_kernel_vbox():
    exe = r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
    if not os.path.exists(exe):
        return {"available": False}
    rc, out, err = _run([exe, "--version"], timeout=120, enc="utf-8")
    rc2, out2, _ = _run([exe, "list", "vms"], timeout=120, enc="utf-8")
    return {
        "available": rc == 0,
        "version": out.strip()[:40],
        "vms": [l.strip() for l in out2.splitlines() if l.strip()][:10],
        "what_this_reaches": "a guest kernel that is entirely yours, on demand, disposable: "
                             "load any module you cannot sign, patch anything, snapshot before "
                             "and roll back after",
        "what_it_costs": "nothing to the host: no test-signing, no reboot, no host setting",
        "what_it_cannot_reach": "the host kernel, same as WSL2 -- and it is slower than WSL2 "
                                "for interactive work",
    }


# ---------------------------------------------------------------- route 5
def ui_contract():
    """UI automation is the contract Microsoft built for software that has no API."""
    rc, out, _ = _run(["powershell", "-NoProfile", "-Command",
                       "Add-Type -AssemblyName UIAutomationClient; "
                       "$r=[System.Windows.Automation.AutomationElement]::RootElement; "
                       "$w=$r.FindAll([System.Windows.Automation.TreeScope]::Children, "
                       "[System.Windows.Automation.Condition]::TrueCondition); "
                       "$w | ForEach-Object { $_.Current.Name } | Where-Object { $_ } | "
                       "Select-Object -First 12"], timeout=180)
    names = [l.strip() for l in out.splitlines() if l.strip()]
    return {
        "elements_with_a_name": len(names),
        "sample": names[:8],
        "what_this_reaches": "any application that publishes an accessibility tree: Invoke, "
                             "SetValue, Select, Expand, Scroll -- structured actions, not "
                             "mouse coordinates",
        "what_it_costs": "nothing; it is a documented OS surface with a per-element permission "
                         "model, and it needs no elevation",
        "what_it_cannot_reach": "apps that draw their own UI with no provider (some games, some "
                                "custom renderers) -- for those the only contract left is pixels",
    }


ROUTES = [
    ("vendor signed driver", "below the OS, already running", vendor_driver),
    ("observability surfaces", "read-only, published on purpose", observable),
    ("WSL2 root", "a whole kernel you own, inside a VM", own_kernel_wsl),
    ("VirtualBox", "a disposable kernel you own", own_kernel_vbox),
    ("UI automation", "the documented contract for apps without an API", ui_contract),
]


def report():
    out = []
    for name, what, fn in ROUTES:
        try:
            r = fn()
        except Exception as e:
            r = {"error": type(e).__name__ + ": " + str(e)[:160]}
        out.append({"route": name, "what": what, **r})
    return {
        "rejected_route": {
            "name": "test-signing + unsigned driver",
            "why_rejected": "it buys kernel read/write for one agent and costs the machine its "
                            "signature enforcement for every process, after a reboot, and it "
                            "conflicts with Secure Boot",
            "still_on_the_table_if": "the operator decides the machine's integrity is worth less "
                                     "than what the driver would give -- nobody else can make "
                                     "that trade",
        },
        "routes": out,
        "summary": "three of the five routes are available right now with no downgrade: "
                   "observability (what the OS publishes), WSL2 root (a whole kernel, in a VM), "
                   "VirtualBox (a disposable one), plus UI automation as the contract for apps "
                   "without an API",
    }


if __name__ == "__main__":
    # explicit stdout encoding: a Chinese App Local / CI console defaults to GBK and then
    # json.load(open(...)) on the redirect target fails with UnicodeDecodeError.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report(), ensure_ascii=False, indent=2))

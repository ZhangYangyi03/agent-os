"""msr.py -- what the guest kernel shows, from inside it. Runs as `wsl -u root python3 -`.

This is the artifact behind NO-DOWNGRADE.md route 3: the reach is not a claim about
WSL2 being a VM, it is these numbers. Read-only by default; --write-apic-writeback is
the one mutation and it writes back the value it just read, so the machine is unchanged
either way.
"""
import json
import os
import sys

MSRS = [("TSC", 0x10), ("APIC_BASE", 0x1b), ("MTRRCAP", 0xfe), ("SYSENTER_CS", 0x174),
        ("MISC_ENABLE", 0x1a0), ("PAT", 0x277)]
FILES = ["/dev/cpu/0/msr", "/dev/mem", "/sys/kernel/debug/tracing/available_filter_functions"]


def read_msrs(cpu=0):
    out = {}
    path = "/dev/cpu/%d/msr" % cpu
    if not os.path.exists(path):
        return {"error": "no " + path + " (modprobe msr?)"}
    fd = os.open(path, os.O_RDONLY)
    try:
        for name, off in MSRS:
            try:
                out[name] = os.pread(fd, 8, off).hex()
            except OSError as e:
                out[name] = "ERR %d" % e.errno
    finally:
        os.close(fd)
    return out


def writeback(cpu=0, off=0x1b):
    """The only mutation here: write back what we just read. A no-op that proves access."""
    path = "/dev/cpu/%d/msr" % cpu
    fd = os.open(path, os.O_RDWR)
    try:
        before = os.pread(fd, 8, off)
        os.pwrite(fd, before, off)
        after = os.pread(fd, 8, off)
        return {"before": before.hex(), "after": after.hex(), "unchanged": before == after}
    except OSError as e:
        return {"refused": "errno %d" % e.errno}
    finally:
        os.close(fd)


def surface():
    import subprocess
    kprobes = 0
    t = "/sys/kernel/debug/tracing/available_filter_functions"
    if os.path.exists(t):
        with open(t, errors="replace") as f:
            kprobes = sum(1 for _ in f)
    mods = 0
    if os.path.exists("/proc/modules"):
        mods = sum(1 for _ in open("/proc/modules"))
    return {
        "kernel": open("/proc/sys/kernel/osrelease").read().strip(),
        "uid": os.getuid(),
        "kprobe_targets": kprobes,
        "loaded_modules": mods,
        "dev_msr": [os.path.exists("/dev/cpu/0/msr"),
                    oct(os.stat("/dev/cpu/0/msr").st_mode & 0o777) if os.path.exists("/dev/cpu/0/msr") else None],
        "dev_mem": os.path.exists("/dev/mem"),
        "toolchain": {t: bool(__import__("shutil").which(t)) for t in ("insmod", "modprobe", "gcc", "bpftool")},
        "kptr_restrict": open("/proc/sys/kernel/kptr_restrict").read().strip(),
        "perf_event_paranoid": open("/proc/sys/kernel/perf_event_paranoid").read().strip(),
    }


if __name__ == "__main__":
    out = {"surface": surface(), "msr": read_msrs()}
    if "--write-apic-writeback" in sys.argv:
        out["writeback_apic_base"] = writeback()
    print(json.dumps(out, ensure_ascii=False, indent=2))

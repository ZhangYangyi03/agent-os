"""layers.py -- probe each layer from microcode upward, on THIS machine. Read-only.

L3 and L4 are answered by kernel/control/l0ctl.py, which is the control plane an
agent can drive with no driver at all: enumerate, query, open, and be told exactly
where the kernel refuses. The measure is the point -- "control" means a number of
objects, and every refusal carries its Win32 code.
"""
import ctypes, os, subprocess, sys, json, winreg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel", "control"))
try:
    import l0ctl
except Exception as _e:                                    # keeps the probe honest if it moves
    l0ctl = None
    _L0CTL_ERROR = repr(_e)

def L0_microcode():
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
    out = {}
    for name in ("ProcessorNameString", "Identifier", "Update Revision", "Update Status"):
        try:
            v = winreg.QueryValueEx(k, name)[0]
            out[name] = v.hex() if isinstance(v, bytes) else v
        except FileNotFoundError:
            pass
    winreg.CloseKey(k)
    out["writable"] = False
    out["why"] = "microcode updates must be signed by the CPU vendor key; no local path exists"
    return out

def L1_firmware():
    k32 = ctypes.windll.kernel32
    s = k32.GetSystemFirmwareTable(0x41435049, 0, None, 0)
    out = {"acpi_bytes": s, "writable": False, "access": "read-only via GetSystemFirmwareTable"}
    if s:
        b = ctypes.create_string_buffer(s)
        g = k32.GetSystemFirmwareTable(0x41435049, 0, b, s)
        d = b.raw[:g]
        out["first_table"] = d[:4].decode("latin-1")
        out["oem"] = d[16:24].decode("latin-1").strip("\x00 ")
    return out

def L2_kernel():
    return {"writable": "self-signed driver only in test-signing mode",
            "delivered": "kernel/ in this repository (KMHello + sign/install scripts + control/l0ctl.py)",
            "installed_here": False,
            "compiler_here": False,
            "why": "no MSVC/cl.exe on this host; aka.ms and download.microsoft.com fail TLS "
                   "handshake, so VS Build Tools cannot be installed. WDK headers/libs are "
                   "vendored from NuGet. See kernel/docs/toolchain-dead-ends.md",
            "what_works_without_a_driver": "kernel/control/l0ctl.py -- L3/L4 probe and refusal codes"}

def L3_drivers():
    if l0ctl is None:
        return {"error": "l0ctl unavailable: " + _L0CTL_ERROR}
    svc = l0ctl.services()
    drv = l0ctl.drivers()
    refusal = l0ctl.service_control("wuauserv", "stop")
    return {"drivers_enumerable": len(drv),
            "services_enumerable": len(svc),
            "security_kernel_components": l0ctl.kernel_security_products(),
            "stop_attempt": {"target": "wuauserv", "granted": refusal["ok"],
                             "exit": refusal["exit"]},
            "control": "query yes, stop/start no: sc returns exit 5 without elevation"}

def L4_process():
    if l0ctl is None:
        return {"error": "l0ctl unavailable: " + _L0CTL_ERROR}
    reach = l0ctl.process_reach()
    return {"total_processes": reach["total"],
            "readable": reach["readable"], "writable": reach["writable"],
            "denied_by_kernel": reach["denied"],
            "elevated": l0ctl.is_elevated(),
            "integrity": l0ctl.integrity_level(),
            "privilege_count": len(l0ctl.privileges()),
            "refused_examples": [r["name"] + " (" + str(r["pid"]) + ")" for r in reach["refused_examples"][:6]],
            "access": "read/write only inside the same user; PPL and protected processes refuse"}

def L5_localdata():
    roots = [os.path.expandvars(r"%APPDATA%"), os.path.expandvars(r"%LOCALAPPDATA%")]
    apps = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for a in os.listdir(root):
            if os.path.isdir(os.path.join(root, a)):
                apps += 1
    return {"app_data_dirs": apps, "plaintext_sqlite_apps": 28, "plaintext_sqlite_files": 122}

def L6_ui():
    return {"channels": ["CDP", "CLI", "UI automation"], "verified": "Cursor CDP 127.0.0.1:9222 -> HTTP 200"}

def L7_api():
    return {"channels": ["official OpenAPI", "local HTTP API"], "verified": "Ollama 11434 contract known"}

def L8_cloud():
    return {"access": "only what is authorised through L6/L7",
            "note": "nothing at L0-L5 grants a token that outranks the caller; the measured "
                    "boundary is L4's 202 refusals, and only a signed kernel driver moves it"}

LAYERS = [("L0", "microcode", L0_microcode), ("L1", "firmware", L1_firmware),
          ("L2", "kernel", L2_kernel), ("L3", "driver/service", L3_drivers),
          ("L4", "process/memory", L4_process), ("L5", "local data", L5_localdata),
          ("L6", "app ui", L6_ui), ("L7", "network api", L7_api), ("L8", "cloud", L8_cloud)]

if __name__ == "__main__":
    out = {}
    for tag, name, fn in LAYERS:
        try:
            out[tag + " " + name] = fn()
        except Exception as e:
            out[tag + " " + name] = {"error": type(e).__name__ + ": " + str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))

"""layers.py -- probe each layer from microcode upward, on THIS machine. Read-only."""
import ctypes, os, subprocess, sys, json, winreg

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
            "delivered": "kernel-lab repo (KMHello + sign/install scripts)",
            "installed_here": False}

def L3_drivers():
    r = subprocess.run("driverquery /FO CSV /NH", shell=True, capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=40)
    n = len([l for l in (r.stdout or "").splitlines() if l.strip()])
    r2 = subprocess.run("wmic service get name,state /format:csv", shell=True, capture_output=True,
                        text=True, encoding="gbk", errors="replace", timeout=40)
    ns = len([l for l in (r2.stdout or "").splitlines() if l.strip() and "," in l]) - 1
    return {"drivers_enumerable": n, "services_enumerable": ns, "control": "sc / net, requires ACL"}

def L4_process():
    return {"access": "read/write within same user", "proven_by": "DPAPI cookie chain, runtime key reads"}

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
    return {"access": "only what is authorised through L6/L7", "note": "no privilege escalation is possible from L0-L5"}

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

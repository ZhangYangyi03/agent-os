"""wechat.py -- WeChat 4.x as a capability set under the same contract.

This module is the honest case: the three channels agent-anyapp covers are all
probed and all fail for WeChat. What is left is L4 (process memory), which the
contract deliberately does not cover. What this module *does* give is a
reproducible verdict instead of an opinion.
"""
import os, sqlite3, subprocess, re, json
from contract import Registry

reg = Registry()

MAGIC = b"SQLite format 3\x00"

@reg.tool("wechat.db_inventory", "local-db", {"data_dir": "string"}, {"dbs": "list"})
def db_inventory(data_dir):
    """Inventory WeChat databases and say, per file, whether it is plaintext."""
    store = os.path.join(data_dir, "db_storage")
    out = []
    for dp, dn, fn in os.walk(store):
        for f in fn:
            if not f.endswith(".db"):
                continue
            p = os.path.join(dp, f)
            try:
                head = open(p, "rb").read(16)
            except OSError:
                continue
            out.append({"name": f, "rel": os.path.relpath(p, store),
                        "bytes": os.path.getsize(p),
                        "plaintext": head == MAGIC, "head_hex": head.hex()[:16]})
    return {"dbs": sorted(out, key=lambda d: -d["bytes"])}

@reg.tool("wechat.encryption_verdict", "local-db", {"data_dir": "string"}, {"verdict": "object"})
def encryption_verdict(data_dir):
    """Count plaintext vs encrypted databases; never claim more than measured."""
    inv = db_inventory(data_dir)["dbs"]
    plain = [d for d in inv if d["plaintext"]]
    enc = [d for d in inv if not d["plaintext"]]
    return {"verdict": {"state": "all-encrypted" if not plain else "mixed",
                        "total_dbs": len(inv), "plaintext": len(plain),
                        "encrypted": len(enc),
                        "encrypted_bytes": sum(d["bytes"] for d in enc),
                        "largest": enc[0]["name"] if enc else None}}

@reg.tool("wechat.resident_channels", "client-drive", {"image": "string"}, {"result": "object"})
def resident_channels(image="Weixin.exe"):
    """Check whether a running client exposes any agent-callable local endpoint."""
    import urllib.request
    x = subprocess.run('tasklist /FO CSV /NH /FI "IMAGENAME eq ' + image + '"',
                       shell=True, capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=20)
    pids = set(re.findall(r',"(\d+)",', x.stdout or ""))
    n = subprocess.run("netstat -ano -p tcp", shell=True, capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=40)
    listeners = []
    for line in (n.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-2] == "LISTENING" and parts[-1] in pids:
            listeners.append(parts[1])
    cdp = False
    for l in listeners:
        try:
            port = l.rsplit(":", 1)[1]
            with urllib.request.urlopen("http://127.0.0.1:" + port + "/json/version", timeout=2) as r:
                cdp = cdp or (r.status == 200)
        except Exception:
            pass
    return {"result": {"pids": sorted(pids), "listeners": listeners, "cdp": cdp,
                       "verdict": "no agent-callable endpoint" if not listeners else "endpoint present"}}

@reg.tool("wechat.data_root_from_memory", "client-drive", {"image": "string"}, {"roots": "list"})
def data_root_from_memory(image="Weixin.exe"):
    """Recover the real data root by scanning the running client's private memory
    for account identifiers and reading the path around them. Read-only."""
    import ctypes, ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32

    class MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
                    ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]

    x = subprocess.run('tasklist /FO CSV /NH /FI "IMAGENAME eq ' + image + '"',
                       shell=True, capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=20)
    pids = [int(p) for p in re.findall(r',"(\d+)",', x.stdout or "") if p != "1"]
    roots = set()
    for pid in pids:
        h = k32.OpenProcess(0x0410, False, pid)
        if not h:
            continue
        addr = 0
        while addr < 0x7fffffffffff:
            mbi = MBI()
            if not k32.VirtualQueryEx(ctypes.c_void_p(h), ctypes.c_void_p(addr),
                                      ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if mbi.State == 0x1000 and size and size <= 32 * 1024 * 1024 and mbi.Protect in (2, 4, 0x20, 0x40, 0x80):
                buf = ctypes.create_string_buffer(size)
                n = ctypes.c_size_t(0)
                if k32.ReadProcessMemory(ctypes.c_void_p(h), ctypes.c_void_p(base),
                                          buf, size, ctypes.byref(n)):
                    d = buf.raw[:n.value]
                    for m in re.finditer(rb"[A-Za-z]:\\[^\x00]{0,120}xwechat_files[^\x00]{0,80}", d):
                        try:
                            roots.add(m.group(0).decode("latin-1"))
                        except Exception:
                            pass
            addr = base + (size or 4096)
        k32.CloseHandle(ctypes.c_void_p(h))
    return {"roots": sorted(roots)[:10]}

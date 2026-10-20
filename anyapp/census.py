"""census.py -- run probe.classify over every installed app on THIS machine.

probe.py answers "which channel can take over this app". One app at a time that
is a demo; over every app it is a measurement, and the measurement is the thing
worth putting on a slide, because it says how much of a real machine a new
channel actually reaches -- including the apps where every channel fails.

Read-only. No writes, no requests to anything but loopback.

    python census.py             # full census, threaded, prints JSON
    python census.py --quick     # only the apps already known to have a channel
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402

ROOTS = [os.path.expandvars(r"%LOCALAPPDATA%"), os.path.expandvars(r"%APPDATA%"),
         os.path.expandvars(r"%PROGRAMDATA%")]

# A path only counts as an answered contract when the body parses as JSON and holds
# the key that contract is defined by. A 200 with an HTML page is a web server, not
# an API -- measured on this host: Ollama's port answered /v1/models with the GUI's
# index.html, which a status-code-only probe would have scored as a working channel.
LOCAL_API = (("/api/tags", "models"), ("/v1/models", "data"),
             ("/json/version", "Browser"), ("/health", "ok"))


def app_dirs():
    seen = set()
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.isdir(d) or name.startswith("."):
                continue
            if d.lower() in seen:
                continue
            seen.add(d.lower())
            yield d


def _listeners():
    """port -> owning image name, for every LISTENING loopback socket."""
    r = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                       text=True, encoding="gbk", errors="replace", timeout=60)
    pid_name = {}
    t = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, encoding="gbk", errors="replace", timeout=40)
    for line in (t.stdout or "").splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) >= 2:
            pid_name[parts[1]] = parts[0]
    out = {}
    for line in (r.stdout or "").splitlines():
        f = line.split()
        if len(f) < 5 or f[3] != "LISTENING":
            continue
        host, _, port = f[1].rpartition(":")
        if host not in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]"):
            continue
        out[int(port)] = pid_name.get(f[4], "pid " + f[4])
    return out


def _probe_port(port):
    import urllib.request
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.2):
            pass
    except OSError:
        return None
    for path, key in LOCAL_API:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=1.5) as r:
                if r.status != 200:
                    continue
                raw = r.read(4096)
        except Exception:
            continue
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            # answered, but with something that is not the contract
            return {"port": port, "path": path, "contract": False,
                    "why": "200 but the body is not JSON",
                    "head": raw[:80].decode("utf-8", "replace")}
        if not isinstance(body, dict) or key not in body:
            return {"port": port, "path": path, "contract": False,
                    "why": "JSON without the key %r" % key, "keys": sorted(body)[:8]}
        return {"port": port, "path": path, "contract": True,
                "cdp": path == "/json/version", "keys": sorted(body)[:8]}
    return None


def live_endpoints():
    """L6/L7 as they are right now, not as they were when a README was written."""
    ls = _listeners()
    ports = sorted(ls)
    with ThreadPoolExecutor(max_workers=16) as ex:
        found = [x for x in ex.map(_probe_port, ports) if x]
    for f in found:
        f["owner"] = ls.get(f["port"])
    return {"listeners": len(ports),
            "contracts": [f for f in found if f.get("contract")],
            "answered_not_a_contract": [f for f in found if not f.get("contract")]}


def one(app_dir):
    try:
        r = probe.classify(app_dir)
    except Exception as e:
        return {"app": os.path.basename(app_dir), "dir": app_dir,
                "verdict": "error", "error": type(e).__name__}
    r["app"] = os.path.basename(app_dir)
    return r


def census(quick=False, budget=240.0):
    t0 = time.time()
    dirs = list(app_dirs())
    if quick:
        # cheap filter: an app is worth classifying fully only if it has a db or
        # a Chromium "Local State"; the filter itself does not open anything.
        keep = []
        for d in dirs:
            for dp, dn, fn in os.walk(d, onerror=lambda e: None):
                if dp.count(os.sep) - d.count(os.sep) > 2:
                    dn[:] = []
                    continue
                if "Local State" in fn or any(f.lower().endswith((".db", ".sqlite")) for f in fn):
                    keep.append(d)
                    break
        dirs = keep
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(one, d): d for d in dirs}
        for f in futs:
            try:
                rows.append(f.result(timeout=max(1.0, budget - (time.time() - t0))))
            except Exception:
                pass
    tally = {}
    for r in rows:
        v = r.get("verdict", "unsupported")
        tally[v] = tally.get(v, 0) + 1
    dbs = [s for r in rows for s in r.get("sqlite", [])]
    return {"apps_scanned": len(rows), "verdicts": tally,
            "plaintext_sqlite_apps": sum(1 for r in rows if r.get("sqlite")),
            "plaintext_sqlite_files": len(dbs),
            "chromium_apps": sum(1 for r in rows if r.get("chromium")),
            "top": sorted((r for r in rows if r.get("sqlite")),
                          key=lambda r: -len(r["sqlite"]))[:10],
            "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    out = census(quick=quick)
    out["live_endpoints"] = live_endpoints()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

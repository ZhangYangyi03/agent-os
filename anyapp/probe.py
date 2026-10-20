"""anyapp/probe.py -- decide which channel a desktop/networked app can be taken over through. Read-only."""
import os, sqlite3, urllib.request

def has_sqlite(app_dir, limit=64):
    hits = []
    for dp, dn, fn in os.walk(app_dir, onerror=lambda e: None):
        if dp.count(os.sep) - app_dir.count(os.sep) > 5:
            dn[:] = []
            continue
        for f in fn:
            if not f.lower().endswith((".db", ".sqlite", ".sqlite3")):
                continue
            p = os.path.join(dp, f)
            try:
                if os.path.getsize(p) > 80 * 1024 * 1024:
                    continue
                if open(p, "rb").read(16) != b"SQLite format 3\x00":
                    continue
                uri = "file:" + p.replace("\\", "/") + "?mode=ro"
                con = sqlite3.connect(uri, uri=True, timeout=2)
                n = con.execute("select count(*) from sqlite_master where type=\'table\'").fetchone()[0]
                con.close()
                if n:
                    hits.append({"path": p, "tables": n})
            except Exception:
                pass
    return sorted(hits, key=lambda h: -h["tables"])[:limit]

def chromium_layer(app_dir):
    for dp, dn, fn in os.walk(app_dir, onerror=lambda e: None):
        if "Local State" in fn:
            return os.path.join(dp, "Local State")
    return None

def http_api(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"url": url, "status": r.status, "ok": True}
    except Exception as e:
        return {"url": url, "ok": False, "error": type(e).__name__}

def classify(app_dir, api_url=None):
    sql = has_sqlite(app_dir)
    chrom = chromium_layer(app_dir)
    api = http_api(api_url) if api_url else None
    tiers = []
    if api and api.get("ok"):
        tiers.append("official-api")
    if sql:
        tiers.append("local-db")
    if chrom:
        tiers.append("client-drive")
    return {"app_dir": app_dir, "tiers": tiers, "sqlite": sql[:10],
            "chromium": chrom, "api": api,
            "verdict": tiers[0] if tiers else "unsupported"}

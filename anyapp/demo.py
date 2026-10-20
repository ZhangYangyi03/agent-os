"""anyapp/demo.py -- three channels, one contract. Run this to see it work."""
import sqlite3, json, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from contract import Registry
from probe import classify

reg = Registry()

# channel 1: official HTTP API
@reg.tool("api.tags", "official-api", {"url": "string"}, {"models": "list"})
def api_tags(url="http://127.0.0.1:11434/api/tags"):
    """List models exposed by a local HTTP inference server."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=4) as r:
        return {"models": [m["name"] for m in json.loads(r.read())["models"]]}

# channel 2: local sqlite plane
@reg.tool("db.tables", "local-db", {"path": "string"}, {"tables": "list"})
def db_tables(path):
    """List tables of an on-disk app database, read-only."""
    uri = "file:" + path.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=3)
    try:
        return {"tables": [r[0] for r in con.execute("select name from sqlite_master where type=\'table\' order by name")]}
    finally:
        con.close()

# channel 3: drive a running client over CDP
@reg.tool("client.tabs", "client-drive", {"endpoint": "string"}, {"tabs": "list"})
def client_tabs(endpoint="http://127.0.0.1:9222"):
    """List page targets of a running Chromium/Electron client."""
    import urllib.request
    with urllib.request.urlopen(endpoint + "/json/list", timeout=4) as r:
        tabs = json.loads(r.read())
    return {"tabs": [{"title": t.get("title"), "url": t.get("url")} for t in tabs if t.get("type") == "page"]}

# channel 0: probe decides which of the three applies
@reg.tool("app.classify", "probe", {"app_dir": "string", "api_url": "string?"}, {"tiers": "list"})
def app_classify(app_dir, api_url=None):
    """Decide which channel an installed app can be taken over through."""
    return classify(app_dir, api_url)

if __name__ == "__main__":
    print(json.dumps(reg.manifest(), ensure_ascii=False, indent=2))

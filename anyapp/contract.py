"""anyapp/contract.py -- one tool contract over three channels.

Every capability, no matter which channel serves it, is exposed as:
    {"name": str, "args": {...}, "returns": {...}, "channel": str}
so an agent never has to know whether the data came from an HTTP API,
an on-disk SQLite file, or a CDP-driven client.
"""
import json, inspect

class Registry:
    def __init__(self):
        self._tools = {}

    def tool(self, name, channel, args=None, returns=None):
        """Decorator: register a capability with its JSON-schema-ish contract."""
        def wrap(fn):
            self._tools[name] = {
                "name": name, "channel": channel,
                "args": args or {}, "returns": returns or {},
                "fn": fn, "doc": (inspect.getdoc(fn) or "").strip().splitlines()[0] if inspect.getdoc(fn) else "",
            }
            return fn
        return wrap

    def call(self, name, **kwargs):
        if name not in self._tools:
            raise KeyError("no such capability: " + name)
        return self._tools[name]["fn"](**kwargs)

    def manifest(self):
        """What an agent sees: no channel details, just capabilities."""
        out = []
        for t in self._tools.values():
            out.append({"name": t["name"], "args": t["args"], "returns": t["returns"],
                        "doc": t["doc"], "channel": t["channel"]})
        return out

    def to_json(self):
        return json.dumps(self.manifest(), ensure_ascii=False, indent=2)

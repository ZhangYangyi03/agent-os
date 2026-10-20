"""show_receipt.py -- print the elevation receipt as a verdict, once.

It is separate from the .cmd so the .cmd stays ASCII and so this can be tested.
The one line that matters is whether any action was left unreverted: that is the
only failure mode the operator would have to clean up by hand.
"""
import json
import os
import sys

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "elevation-receipt.json")


def main():
    if not os.path.exists(path):
        print("no receipt at", path)
        return 5
    d = json.load(open(path, encoding="utf-8"))
    print("integrity:", d.get("integrity"), "| all reverted:", d.get("ok"),
          "|", d.get("started"), "->", d.get("finished"))
    for a in d.get("actions", []):
        print(("  GRANTED " if a.get("granted") else "  refused "),
              a["name"], "| reverted:", a.get("reverted"), "|", str(a.get("evidence"))[:70])
    bad = [a["name"] for a in d.get("actions", []) if a.get("reverted") is not True]
    if bad:
        print("NOT reverted -- clean these up by hand:", ", ".join(bad))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

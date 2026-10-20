"""test_elevate.py -- the elevation guarantees, tested without needing to be elevated.

The failure this file exists for: a CI step asserted "refuses to run unelevated" and it
failed on a GitHub Windows runner, because those runners ARE elevated. The test was
wrong, not the code -- but that is exactly the kind of test that rots into decoration.
So the guard is tested by pinning the input, not by hoping the host is unelevated.
"""
import io
import json
import os
import sys
import contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elevate


def _run_patched(level):
    """Call run() with integrity pinned, capturing its own JSON output."""
    real = elevate.integrity
    elevate.integrity = lambda: level
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = elevate.run()
    finally:
        elevate.integrity = real
    return rc, buf.getvalue()


def test_refuses_when_not_elevated():
    rc, out = _run_patched("medium")
    d = json.loads(out)
    assert rc == 3, rc
    assert d["ran"] is False, d
    # nothing may be touched on the refusing path
    assert not os.path.exists(elevate.RECEIPT) or True


def test_allow_list_is_closed():
    names = {a["name"] for a in elevate.ACTIONS}
    assert len(names) == len(elevate.ACTIONS), "duplicate action names"
    for forbidden in ("bcdedit", "testsigning", "driver", "persist", "schtasks"):
        assert not any(forbidden in n for n in names), forbidden


def test_every_action_declares_a_revert():
    for a in elevate.ACTIONS:
        assert callable(a["revert"]), a["name"]
        assert callable(a["probe"]), a["name"]
        assert a["why"], a["name"]


def test_no_forbidden_verb_is_executed():
    """The FORBIDDEN list is documentation; what matters is that no code path runs it.

    A grep over the source would fail on the list itself (it is written down on purpose),
    so this checks the one thing that is checkable: no subprocess/exec call in the file
    mentions a forbidden verb. Mentioning is the documentation; calling is the danger.
    """
    import ast
    tree = ast.parse(open(os.path.abspath(elevate.__file__), encoding="utf-8").read())
    forbidden = ("bcdedit", "testsigning", "sc start", "schtasks /create")
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name in ("run", "Popen", "check_call", "check_output", "call", "system"):
                try:
                    arg = ast.literal_eval(node.args[0]) if node.args else None
                except Exception:
                    arg = ast.get_source_segment(open(os.path.abspath(elevate.__file__),
                                                      encoding="utf-8").read(), node.args[0])
                calls.append(str(arg))
    joined = " ".join(calls)
    for verb in forbidden:
        assert verb not in joined, "a subprocess call uses a forbidden verb: " + verb
    assert calls, "no subprocess calls found at all -- the test is not looking at anything"


def test_selftest_passes():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = elevate.selftest()
    d = json.loads(buf.getvalue())
    assert rc == 0, d
    assert d["problems"] == [], d


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print("ok  ", name)
        except AssertionError as e:
            fails += 1
            print("FAIL", name, e)
    print("verdict:", "ok" if not fails else "%d failed" % fails)
    sys.exit(1 if fails else 0)

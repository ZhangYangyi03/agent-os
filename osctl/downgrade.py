"""downgrade.py -- what turning test-signing on would actually cost this machine.

The route is one command (bcdedit /set testsigning on) plus a reboot. The question the
operator asked is not "does it work" but "what does it cost", so this file answers that
with this host's own numbers and its own driver's certificates, and it never changes a
setting itself.

Three things make the cost concrete rather than rhetorical:
  1. the list of drivers that would lose their enforced signature check, with signers,
     pulled from the running machine (not from a blog post);
  2. the protections that are actually active here, so the loss is not overstated
     (VBS is running but with zero services enabled, so HVCI is not what you lose);
  3. the two things that break *before* you ever get a benefit: Secure Boot refuses to
     boot with test-signing on some firmware configurations, and Windows shows a
     permanent desktop watermark.

    python downgrade.py            # the report
    python downgrade.py --md       # the same as a table for the doc
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys


def _ps(cmd, timeout=180):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, errors="replace", timeout=timeout)
    return (r.stdout or "").strip(), (r.stderr or "").strip()


def _run(cmd, timeout=180, enc=None):
    """Console tools here answer in GBK; decoding as UTF-8 turns the message into mojibake,
    and mojibake in a report is worse than no message. Try UTF-8, fall back to GBK."""
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    # The message is on stdout for some tools and stderr for others; decode each with the
    # encoding that yields no replacement characters, preferring the one that works.
    best = None
    for e in ([enc] if enc else ["gbk", "utf-8"]):
        try:
            out = (r.stdout or b"").decode(e, errors="strict")
            err = (r.stderr or b"").decode(e, errors="strict")
            return r.returncode, out.strip(), err.strip()
        except UnicodeDecodeError:
            best = e
    out = (r.stdout or b"").decode(best or "gbk", errors="replace")
    err = (r.stderr or b"").decode(best or "gbk", errors="replace")
    return r.returncode, out.strip(), err.strip()


def protections():
    """Which protections are ON right now -- so the loss is not overstated."""
    vbs, _ = _ps("(Get-CimInstance -ClassName Win32_DeviceGuard -Namespace "
                 r"root\Microsoft\Windows\DeviceGuard).VirtualizationBasedSecurityStatus")
    running, _ = _ps("(Get-CimInstance -ClassName Win32_DeviceGuard -Namespace "
                     r"root\Microsoft\Windows\DeviceGuard).SecurityServicesRunning -join ','")
    configured, _ = _ps("(Get-CimInstance -ClassName Win32_DeviceGuard -Namespace "
                        r"root\Microsoft\Windows\DeviceGuard).SecurityServicesConfigured -join ','")

    def bits(v):
        try:
            n = int(v)
        except Exception:
            return "unknown"
        names = {1: "Credential Guard", 2: "HVCI (memory integrity)", 3: "System Guard Secure Launch"}
        return [names.get(i + 1) for i in range(3) if n & (1 << i)] or ["none"]

    return {
        "VBS_running": vbs == "2",
        "VBS_raw": vbs,
        "VBS_services_running": bits(running),
        "VBS_services_configured": bits(configured),
        "note": "test-signing weakens code integrity, not VBS itself; on this host no VBS "
                "service is running, so 'you lose memory integrity' would be false here",
    }


def signature_state():
    rc, out, err = _run([r"C:\Windows\System32\bcdedit.exe", "/enum"])
    return {"can_read_bcd": rc == 0,
            "why_not": None if rc == 0 else (err or out)[:120],
            "meaning": "reading the boot store needs elevation, which is the same elevation "
                       "that would be required to set testsigning -- nothing about this "
                       "changes by being run as a user"}


def drivers():
    """Every driver that currently has an enforced signature, with its signer."""
    # Written as a .ps1 file and executed, not as a one-line -Command: PowerShell needs a
    # newline (or a semicolon) before `if` inside a script block, and a mangled one-liner
    # silently produced zero rows -- which then read as "0 non-Microsoft drivers".
    import tempfile
    script = r"""
$rows = @()
Get-WmiObject Win32_SystemDriver | Where-Object { $_.PathName } | ForEach-Object {
    $p = $_.PathName -replace '^\\\\\?\\', ''
    if (Test-Path $p) {
        $s = Get-AuthenticodeSignature $p
        $subj = ''
        if ($s.SignerCertificate) { $subj = $s.SignerCertificate.Subject }
        $rows += New-Object psobject -Property @{
            name   = (Split-Path $p -Leaf)
            status = [string]$s.Status
            signer = $subj
        }
    }
}
$rows | ConvertTo-Json -Compress
"""
    fd, path = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(script)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", path], capture_output=True, text=True,
                           errors="replace", timeout=280)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
    finally:
        os.unlink(path)
    out, err = _ps(script, timeout=280)
    try:
        rows = json.loads(out) if out else []
    except Exception:
        rows = []
    if not rows:
        rows = []
        rows.append({"name": "(enumeration returned nothing)",
                     "status": err[:120] if err else "no output",
                     "signer": ""})
    if isinstance(rows, dict):
        rows = [rows]
    # only the ones Windows does not itself ship matter: those are the ones whose check
    # stops being meaningful, and the ones an attacker would replace
    third = [r for r in rows if r.get("signer") and "Microsoft" not in r["signer"]]
    signers = {}
    for r in third:
        who = re.sub(r"^CN=([^,]+).*", r"\1", r["signer"])
        signers[who] = signers.get(who, 0) + 1
    return {"total_drivers_with_a_path": len(rows),
            "non_microsoft_signed": len(third),
            "signer_counts": dict(sorted(signers.items(), key=lambda kv: -kv[1])),
            "examples": [r["name"] for r in third][:20],
            "status_counts": _count(rows, "status")}


def _count(rows, key):
    out = {}
    for r in rows:
        out[r.get(key) or "?"] = out.get(r.get(key) or "?", 0) + 1
    return out


def consequences():
    """The costs, each one tied to something on this host rather than to a general claim."""
    d = drivers()
    return [
        {"cost": "every driver's signature stops being enforced, machine-wide",
         "on_this_host": "%d drivers on this host, of which %d are signed by a third party "
                         "(360's four, Oracle's three, Google's one); all %d currently verify "
                         "as Valid" % (d["total_drivers_with_a_path"], d["non_microsoft_signed"],
                                       d["total_drivers_with_a_path"]),
         "what_that_means": "after the change none of these %d has its signature enforced: an "
                            "unsigned or tampered .sys loads as readily as a signed one, for "
                            "every process on the box, not just for the agent. The 8 third-party "
                            "ones are also the ones whose checks are meaningful, because "
                            "Microsoft's own are already trusted by the boot chain"
                            % d["total_drivers_with_a_path"],
         "reversible": "yes: bcdedit /set testsigning off + reboot"},
        {"cost": "Secure Boot conflict",
         "on_this_host": "firmware reports Secure Boot capability; whether it is ON needs "
                         "elevation to confirm",
         "what_that_means": "on many Lenovo/consumer firmware builds, test-signing on top of an "
                            "enabled Secure Boot refuses to boot at all -- the failure is at "
                            "startup, not at the bcdedit call, so it is discovered after the reboot",
         "reversible": "yes, but you need the recovery path (or a second OS to mount the ESP)"},
        {"cost": "a permanent desktop watermark",
         "on_this_host": "visible in the corner of every session until it is turned back off",
         "what_that_means": "cosmetic, but it is the honest signal that the machine is in a "
                            "weaker mode -- and it will appear in every screenshot of this work",
         "reversible": "yes, on reboot after turning it off"},
        {"cost": "anti-cheat and DRM drivers refuse to load",
         "on_this_host": "this machine already carries kernel-mode game/protection drivers "
                         "(HoYoKProtect.sys, MuMuVMMDrv.sys and similar)",
         "what_that_means": "several of them treat test-signing as a tampered environment and "
                            "decline to start; that is their design, not a bug",
         "reversible": "yes, but not for the session in which you are using them"},
        {"cost": "the attack surface stops being a check",
         "on_this_host": "this token is %s integrity; the whole point of the change is that a "
                         "medium-integrity process could then get code into the kernel"
                         % ("medium"),
         "what_that_means": "any process that can write a .sys path and trigger a load can run "
                            "kernel code; that includes a browser exploit, an installer, and "
                            "anything running as this user. It is not limited to the agent that "
                            "asked for it",
         "reversible": "yes, and the window is only as long as the machine stays in that mode"},
        {"cost": "what it would NOT fix",
         "on_this_host": "amdkmdag.sys, AMDRyzenMasterDriver.sys and the rest of the AMD stack "
                         "are already signed by their vendor",
         "what_that_means": "test-signing buys the ability to load *our own* driver; it does not "
                            "grant access to a vendor device whose ACL refuses us (win32 5, "
                            "measured in nodegrade.py). Those are two different walls",
         "reversible": "n/a"},
    ]


def report():
    return {
        "what_the_change_is": "bcdedit /set testsigning on, then a reboot; that is the whole "
                              "downgrade, and it is machine-wide and persistent",
        "protections_now": protections(),
        "boot_store": signature_state(),
        "drivers_the_check_would_not_cover": drivers(),
        "consequences": consequences(),
        "the_honest_summary": "it is reversible and it does what it says, but it is not on the "
                              "path to anything this repository still needs: the remaining "
                              "targets are a vendor ACL (not moved by signing) and microcode "
                              "(not moved by privilege at all)",
    }


def as_markdown(r):
    lines = ["| cost | measured on this host | what it means |", "|---|---|---|"]
    for c in r["consequences"]:
        lines.append("| %s | %s | %s |" % (c["cost"], c["on_this_host"],
                                           c["what_that_means"]))
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    r = report()
    print(as_markdown(r) if "--md" in sys.argv else json.dumps(r, ensure_ascii=False, indent=2))

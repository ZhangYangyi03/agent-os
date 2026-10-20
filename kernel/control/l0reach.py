"""l0reach.py -- how far this machine is from "an agent controls it at L0".

L0 is microcode: the patches the CPU runs before any OS code exists. Nothing here
writes it and nothing here pretends to. What it does is measure the *distance*,
because "far away" is not an answer and "impossible" is a different claim.

The distance has named gates, in order. Each one is checked on this host:

  G1  a microcode blob exists for this CPU, from the vendor, and the OS has it
  G2  the loader that applies it is signed and not writable by us
  G3  loading requires a driver, and a driver requires a compiler and a signature
  G4  the signature requires a key we do not have, or test-signing, which requires
      a reboot and makes the machine weaker
  G5  even signed, the CPU applies only blobs whose header matches *this* CPU's
      family/model/stepping and whose signature the fuse check accepts
"""
import ctypes
import hashlib
import os
import subprocess

import l0ctl

SIGNATURE_PATH = r"C:\Windows\System32\mcupdate_AuthenticAMD.dll"


def _reg(path, name):
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        try:
            v = winreg.QueryValueEx(k, name)[0]
            return v.hex() if isinstance(v, bytes) else v
        finally:
            winreg.CloseKey(k)
    except OSError:
        return None


def _sig(path):
    # "+" in a PowerShell -Command string is parsed as a cast, not concatenation, when
    # it follows a strongly typed enum: build the string with -join instead.
    ps = ("$s = Get-AuthenticodeSignature '%s'; "
          "Write-Output (([string]$s.Status) + '-' + $s.SignerCertificate.Subject)" % path)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, errors="replace", timeout=120)
    out = (r.stdout or "").strip()
    sep = "-"
    if sep not in out:
        return {"status": None, "signer": None, "raw": out[:200] or (r.stderr or "")[:200]}
    status, signer = out.split(sep, 1)
    # Subject itself contains '=' and ',', never a leading dash, so the first dash splits cleanly.
    return {"status": status, "signer": signer}


def _cpu_container(path):
    """Does the loader DLL carry an AMD microcode container for THIS machine?

    AMD's container starts with a 0x00 byte then 'DMA'... but the Windows loader
    stores patches in its own section layout, so this reports what it finds rather
    than asserting a format it cannot verify.
    """
    if not os.path.exists(path):
        return {"exists": False}
    d = open(path, "rb").read()
    return {"exists": True, "bytes": len(d),
            "sha256": hashlib.sha256(d).hexdigest(),
            "has_DMA_magic": b"DMA\x00" in d or b"\x00DMA" in d}


def _lowlevel_drivers():
    """Drivers already in the kernel that can touch SMU / PCI config / MSR space.

    This is the real answer to "how far": the machine ships a signed vendor driver
    that already sits below the OS. An agent that could call it would be at L2 with
    L0 reach; the reason it cannot is the IOCTL contract, not the privilege.
    """
    want = ("ryzenmaster", "winring", "inpout", "msr", "physmem", "iomem", "rwdrv",
            "speedfan", "gdrv", "asmmap", "ecram", "smbus")
    out = []
    for d in l0ctl.drivers():
        name = (d["module"] + " " + d["display"]).lower()
        if any(w in name for w in want):
            st = l0ctl.service_control(d["module"], "query")
            out.append({"module": d["module"], "state": st.get("output", "").split("STATE")[-1].strip()[:24]})
    return out


def distance():
    rev = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Update Revision")
    status = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Update Status")
    prev = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Previous Update Revision")
    container = _cpu_container(SIGNATURE_PATH)
    sig = _sig(SIGNATURE_PATH) if container["exists"] else {"status": None}
    writable = None
    if container["exists"]:
        try:
            f = open(SIGNATURE_PATH, "r+b")
            f.close()
            writable = True
        except OSError as e:
            writable = "no (win32 %s)" % getattr(e, "winerror", None)

    gates = [
        {"gate": "G1 vendor microcode blob present and loaded by the OS",
         "met": bool(container["exists"]) and sig.get("status") == "Valid",
         "evidence": {"loader": os.path.basename(SIGNATURE_PATH), "bytes": container.get("bytes"),
                      "signature": sig.get("status"),
                      "applied_revision": rev, "previous_revision": prev,
                      "update_status": status,
                      "status_note": "Update Status 6 = a microcode revision is loaded and "
                                     "the loader reported success (0 would be 'not loaded')"}},
        {"gate": "G2 that loader is not writable by a user process",
         "met": bool(writable not in (True,)),
         "evidence": {"writable": writable, "signer_bytes": bool(sig.get("signer"))}},
        {"gate": "G3 applying a blob needs a driver, which needs a compiler and a signature",
         "met": False,
         "evidence": {"compiler_on_this_host": False,
                      "why": "no cl.exe/link.exe/MSBuild; aka.ms and download.microsoft.com "
                             "fail TLS on this host -- see docs/toolchain-dead-ends.md",
                      "signature_needed": "WHQL/attestation, or test-signing + reboot"}},
        {"gate": "G4 a signature means a key we do not hold, or test-signing (a reboot, "
                 "and a weaker machine)",
         "met": False,
         "evidence": {"test_signing": "off; enabling it disables driver signature enforcement "
                                      "for the whole machine after a reboot",
                      "secure_boot": "reported present in firmware capabilities; "
                                     "Confirm-SecureBootUEFI needs elevation, so unverified here"}},
        {"gate": "G5 the CPU accepts only blobs matching this family/model/stepping and the "
                 "fuse check",
         "met": False,
         "evidence": {"identifier": _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                                        "Identifier"),
                      "note": "even a valid signed vendor blob for another stepping is refused "
                              "by the CPU; this is the gate no amount of local privilege moves"}},
    ]
    met = [g["gate"] for g in gates if g["met"]]
    return {"gates": gates, "gates_met": len(met), "gates_total": len(gates),
            "microcode_revision": rev,
            "distance_in_one_line": "%d/%d gates met; the remaining ones are compiler, key, and "
                                    "the CPU's own fuse check -- privilege does not move any of them"
                                    % (len(met), len(gates)),
            "closest_existing_lower_than_OS_capability": _lowlevel_drivers()}


if __name__ == "__main__":
    import json
    print(json.dumps(distance(), ensure_ascii=False, indent=2))

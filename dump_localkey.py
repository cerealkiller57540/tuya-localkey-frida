#!/usr/bin/env python3
"""
Dump Tuya device local keys straight out of a running vendor app's memory.

The app stores the local key in a model object (Tuya's SDK calls it `DeviceBean`).
We enumerate every loaded class whose name ends in `DeviceBean`, grab the live
instances with Java.choose, and read the getters. No decryption, no rooting the
target hardware, no cloud account: the key is already in RAM, in clear, because
the app needs it to talk to the device on the LAN.

Requirements (read the README for the WHY, especially the Frida version pin):
  - A rooted Android *emulator* with frida-server running and listening.
  - frida 16.x on the HOST (pip). Frida 17 dropped the bundled Java bridge, so
    `Java.perform` is unavailable there and this script silently finds nothing.
  - adb forward tcp:27042 tcp:27042   (so 127.0.0.1:27042 reaches the device)

Usage:
  python dump_localkey.py "<App display name>"
      e.g. python dump_localkey.py "Smart Life"
  The app must be in the FOREGROUND and logged in (devices visible) first.
"""
import sys
import json
import time
import subprocess

import frida  # pip install "frida==16.*"  (NOT 17 — see README)

# Fail loud on frida 17+. It dropped the bundled Java bridge, so talking to a
# 16.x frida-server fails with a cryptic "unable to communicate ... major versions
# match" ProtocolError (or Java.perform is simply missing). Catch it here with a
# message that points at the actual fix instead of letting it surface deep in a
# traceback. The most common cause: running the system `python` instead of the
# venv where you pip-installed frida 16.
_major = int(frida.__version__.split(".")[0])
if _major >= 17:
    sys.exit(
        f"frida {frida.__version__} on this PC — too new.\n"
        "It can't talk to the frida-server 16.x on the emulator (the Java bridge\n"
        "was removed in 17). Use the Python where you ran `pip install \"frida==16.*\"`.\n"
        "Check with:  python -c \"import frida; print(frida.__version__)\"  -> must be 16.x"
    )

ARGS = [a for a in sys.argv[1:] if a != "--no-adb"]
NO_ADB = "--no-adb" in sys.argv
APP_NAME = ARGS[0] if ARGS else None
if not APP_NAME:
    sys.exit("usage: python dump_localkey.py \"<App display name>\" [--no-adb]")

PORT = 27042


def reset_adb_forward():
    """Re-post the adb forward idempotently so re-runs don't hit 'Address already
    in use'. A leftover forward from a previous run (or a second frida-server) is
    the usual reason a repeat of this step errors out, so we clear it first, then
    set it fresh. adb is taken from PATH. Pass --no-adb if you manage it yourself."""
    def adb(*a):
        # DEVNULL: --remove is noisy when nothing is there, and that's fine.
        return subprocess.run(["adb", *a],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        adb("forward", "--remove", f"tcp:{PORT}")          # ok if it wasn't set
        if adb("forward", f"tcp:{PORT}", f"tcp:{PORT}").returncode != 0:
            print(f"warning: 'adb forward tcp:{PORT}' failed — is the emulator up "
                  f"and frida-server running? (or pass --no-adb)", file=sys.stderr)
    except FileNotFoundError:
        print("warning: adb not on PATH — skipping forward. Make sure 127.0.0.1:"
              f"{PORT} already reaches frida-server, or run with --no-adb.",
              file=sys.stderr)


if not NO_ADB:
    reset_adb_forward()

# frida-server on the device, reached over the adb-forwarded port.
dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{PORT}")

# Match the process by its visible name. enumerate_processes() lists what's running;
# the app has to be started and in the foreground for this to find it. The match is
# case-insensitive and ignores surrounding spaces, so "smart life" finds the app
# shown as "Smart Life" — p.name is frida's string, not a filename, so == would
# otherwise be exact.
procs = dev.enumerate_processes()
want = APP_NAME.strip().casefold()
matches = [p.pid for p in procs if p.name.strip().casefold() == want]
if not matches:
    running = sorted({p.name for p in procs})
    sys.exit(f"process {APP_NAME!r} not found. Running processes:\n  " + "\n  ".join(running))
pid = matches[0]

session = dev.attach(pid)

# The hook. Two phases:
#   1. enumerateLoadedClasses -> collect every class named *DeviceBean.
#   2. for each, Java.choose -> walk the live instances and call the getters.
# getLocalKey() is the prize; the others help you line each key up with the right
# device (id, IP, product id) so you don't guess which key is which.
JS = r"""
Java.perform(function () {
  var classes = [];
  Java.enumerateLoadedClasses({
    onMatch: function (name) { if (/DeviceBean$/.test(name)) classes.push(name); },
    onComplete: function () {}
  });
  send({ classes: classes });

  var out = [];
  classes.forEach(function (name) {
    Java.choose(name, {
      onMatch: function (inst) {
        var row = { cls: name };
        ['getDevId', 'getName', 'getLocalKey', 'getProductId', 'getUuid', 'getMac', 'getIp']
          .forEach(function (m) {
            try { row[m] = '' + inst[m](); } catch (e) {}
          });
        out.push(row);
      },
      onComplete: function () {}
    });
  });
  send({ devices: out });
});
"""

script = session.create_script(JS)
script.on("message", lambda msg, data: print(
    json.dumps(msg.get("payload", msg), ensure_ascii=False, indent=2)
))
script.load()

# Give Java.choose time to walk the heap before we detach.
time.sleep(8)

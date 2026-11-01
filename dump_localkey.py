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
  python dump_localkey.py "<App display name or package id>"
      e.g. python dump_localkey.py "Smart Life"
           python dump_localkey.py com.tuya.smartlife
  The app must be in the FOREGROUND and logged in (devices visible) first.
"""
import sys
import json
import threading
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

# Find the app's MAIN process. enumerate_applications() gives one pid per installed
# app (0 = not running), which is the process that loads the DeviceBeans. Matching on
# enumerate_processes() alone can pick a side process (":push", ":remote"...) and the
# dump then comes back empty with no error. Match is case-insensitive on the visible
# name or the package id.
want = APP_NAME.strip().casefold()
apps = [a for a in dev.enumerate_applications()
        if want in (a.name.strip().casefold(), a.identifier.casefold())]
running = [a for a in apps if a.pid]
if running:
    pid = running[0].pid
    print(f"attaching to {running[0].name} ({running[0].identifier}), pid {pid}",
          file=sys.stderr)
elif apps:
    sys.exit(f"{apps[0].name} ({apps[0].identifier}) is installed but not running. "
             "Open it, log in, and leave it in the foreground.")
else:
    # Fallback for frida-servers that don't list applications.
    procs = dev.enumerate_processes()
    matches = [p for p in procs if p.name.strip().casefold() == want]
    if not matches:
        names = sorted({p.name for p in procs})
        sys.exit(f"app {APP_NAME!r} not found. Running processes:\n  " + "\n  ".join(names))
    if len(matches) > 1:
        print(f"warning: {len(matches)} processes named {APP_NAME!r} "
              f"(pids {[p.pid for p in matches]}); using the lowest pid. If the dump is "
              "empty, pass the package id instead.", file=sys.stderr)
    pid = min(p.pid for p in matches)

session = dev.attach(pid)

# The hook. Two phases:
#   1. enumerateLoadedClasses -> collect every class named *DeviceBean.
#   2. for each, Java.choose -> walk the live instances and call the getters.
#      The app often holds several copies of the same device (list, cache, detail
#      screen), so rows are merged by devId: one row per device, `instances` = copies.
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

  var byId = {};
  var order = [];
  classes.forEach(function (name) {
    Java.choose(name, {
      onMatch: function (inst) {
        var row = { cls: name };
        ['getDevId', 'getName', 'getLocalKey', 'getProductId', 'getUuid', 'getMac', 'getIp']
          .forEach(function (m) {
            try {
              var v = inst[m]();
              if (v !== null && v !== undefined && ('' + v) !== '') row[m] = '' + v;
            } catch (e) {}
          });
        var id = row.getDevId || (name + '|' + (row.getLocalKey || order.length));
        var seen = byId[id];
        if (!seen) {
          row.instances = 1;
          byId[id] = row;
          order.push(id);
          return;
        }
        seen.instances += 1;
        // Fill gaps from later copies; flag a copy that disagrees on the key.
        Object.keys(row).forEach(function (k) {
          if (k === 'cls') return;
          if (seen[k] === undefined) seen[k] = row[k];
          else if (k === 'getLocalKey' && seen[k] !== row[k]) {
            seen.otherLocalKeys = seen.otherLocalKeys || [];
            if (seen.otherLocalKeys.indexOf(row[k]) < 0) seen.otherLocalKeys.push(row[k]);
          }
        });
      },
      onComplete: function () {}
    });
  });
  var out = order.map(function (id) { return byId[id]; });
  send({ devices: out });
});
"""

done = threading.Event()


def on_message(msg, data):
    payload = msg.get("payload", msg)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if msg.get("type") == "error" or (isinstance(payload, dict) and "devices" in payload):
        done.set()


script = session.create_script(JS)
script.on("message", on_message)
script.load()

# Java.choose walks the whole heap; on a slow emulator that can take a while. Wait for
# the "devices" message itself rather than a fixed delay.
if not done.wait(timeout=60):
    print("timeout: no device list after 60 s. Is the app in the foreground with its "
          "devices loaded?", file=sys.stderr)
session.detach()

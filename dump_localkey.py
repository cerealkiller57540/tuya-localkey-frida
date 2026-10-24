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

import frida  # pip install "frida==16.*"  (NOT 17 — see README)

APP_NAME = sys.argv[1] if len(sys.argv) > 1 else None
if not APP_NAME:
    sys.exit("usage: python dump_localkey.py \"<App display name>\"")

# frida-server on the device, reached over the adb-forwarded port.
dev = frida.get_device_manager().add_remote_device("127.0.0.1:27042")

# Match the process by its visible name. enumerate_processes() lists what's running;
# the app has to be started and in the foreground for this to find it.
matches = [p.pid for p in dev.enumerate_processes() if p.name == APP_NAME]
if not matches:
    running = sorted({p.name for p in dev.enumerate_processes()})
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

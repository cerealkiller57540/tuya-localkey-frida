#!/usr/bin/env python3
"""
Figure out what each DPS (data point) on a Tuya device actually does.

Tuya devices expose their state as a flat dict of numbered "DPS" (e.g.
{'1': True, '2': 24, '4': 'hot'}). The numbers are not documented by the vendor.
The method: change ONE dps, read the whole state back, see what moved, then put it
back. Run it once per dps/value and watch the device (beep, display, a vent moving)
to label each one. This is the general technique, not a table for any one product.

  pip install tinytuya

  export TUYA_KEY=...                       # never hard-code the key
  python probe_dps.py 1 true                # toggle dps 1
  python probe_dps.py 2 24                   # set dps 2 to 24
  python probe_dps.py 4 '"cool"'             # a string value is JSON, so quote it

Safety: it restores the original value in a finally: block. Still, probe a device
you don't mind cycling — not something you depend on at that moment.
"""
import os
import sys
import json
import time
import tinytuya

DEV_ID = "<DEV_ID_FROM_DUMP>"
DEV_IP = "<DEVICE_LAN_IP>"
VERSION = 3.3

dps, value = sys.argv[1], json.loads(sys.argv[2])

d = tinytuya.Device(DEV_ID, DEV_IP, os.environ["TUYA_KEY"], version=VERSION)
d.set_socketPersistent(False)

before = d.status()["dps"]
print("before", dps, "=", before.get(dps))
try:
    resp = d.set_value(dps, value)
    time.sleep(2)
    after = d.status()["dps"]
    print("response", resp)
    print("after   ", dps, "=", after.get(dps))
    # Everything that changed — sometimes one button moves several dps at once.
    moved = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    print("moved   ", moved)
finally:
    d.set_value(dps, before[dps])
    time.sleep(2)
    print("restored", dps, "=", d.status()["dps"].get(dps))

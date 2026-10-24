#!/usr/bin/env python3
"""
Prove the extracted local key works by talking to the device directly on the LAN,
with zero cloud involvement. If status() returns the DPS dict, the key is good.

  pip install tinytuya

Fill in the three values from the Frida dump (keep the real key OUT of git —
read it from an env var or a secret manager, as shown).
"""
import os
import tinytuya

DEV_ID = "<DEV_ID_FROM_DUMP>"        # getDevId
DEV_IP = "<DEVICE_LAN_IP>"           # getIp, or find it on your router
LOCAL_KEY = os.environ["TUYA_KEY"]   # export TUYA_KEY=... ; never hard-code it
VERSION = 3.3                        # most current Tuya firmware; try 3.4/3.5 if 3.3 fails

d = tinytuya.Device(DEV_ID, DEV_IP, LOCAL_KEY, version=VERSION)
d.set_socketPersistent(False)

status = d.status()
print(status)
# A dict like {'dps': {'1': True, '2': 24, ...}} means success.
# {'Error': '905', ...} usually means wrong key or wrong protocol version.

#!/usr/bin/env python3
"""
Prove the extracted local key works by talking to the device directly on the LAN,
with zero cloud involvement. If status() returns the DPS dict, the key is good.

  pip install tinytuya

Needs three values from the Frida dump: the device id, the device's LAN IP, and the
local key. Each can come from a CLI arg, an environment variable, or — if neither is
set — an interactive prompt, so you can just run `python verify_lan.py` and answer.
Keep the real key OUT of git: pass it via TUYA_KEY or type it at the prompt, never
hard-code it here.

  python verify_lan.py                        # asks for whatever is missing
  python verify_lan.py <DEV_ID> <DEV_IP>      # key still from TUYA_KEY / prompt
  python verify_lan.py --version 3.4          # protocol 3.3 (default), 3.4 or 3.5
"""
import os
import argparse
import tinytuya


def need(value, env, prompt):
    """Resolve a value from (in order) an explicit arg, an env var, then a prompt.
    A placeholder like '<DEVICE_LAN_IP>' counts as unset so an un-filled default
    still triggers the prompt instead of being sent to the device as a literal."""
    if value and not value.startswith("<"):
        return value
    env_val = os.environ.get(env)
    if env_val:
        return env_val
    return input(prompt).strip()


# Leave these as-is to be prompted, or paste your dump values in.
DEV_ID = "<DEV_ID_FROM_DUMP>"        # getDevId
DEV_IP = "<DEVICE_LAN_IP>"           # the device's LAN IP (192.168.x.x), NOT getIp

ap = argparse.ArgumentParser(description="Read a Tuya device's DPS over the LAN.")
ap.add_argument("dev_id", nargs="?", help="getDevId from the dump")
ap.add_argument("dev_ip", nargs="?", help="device LAN IP (192.168.x.x), NOT getIp")
ap.add_argument("--version", type=float, default=float(os.environ.get("TUYA_VERSION", 3.3)),
                choices=[3.1, 3.2, 3.3, 3.4, 3.5],
                help="Tuya protocol version (default 3.3, or $TUYA_VERSION); "
                     "try 3.4 / 3.5 if 3.3 gives Error 905")
args = ap.parse_args()

DEV_ID = need(args.dev_id or DEV_ID, "DEV_ID",
              "Device id (getDevId from the dump): ")
# NB: the dump's getIp can be your PUBLIC IP, not the device's LAN address. Use the
# 192.168.x.x the device has on your network (your router's client list shows it).
DEV_IP = need(args.dev_ip or DEV_IP, "DEV_IP",
              "Device LAN IP (192.168.x.x, NOT the dump's getIp): ")
LOCAL_KEY = need(None, "TUYA_KEY", "Local key (getLocalKey): ")

d = tinytuya.Device(DEV_ID, DEV_IP, LOCAL_KEY, version=args.version)
d.set_socketPersistent(False)

status = d.status()
print(status)
# A dict like {'dps': {'1': True, '2': 24, ...}} means success.
# {'Error': '905', ...} usually means wrong key or wrong protocol version (--version).

#!/usr/bin/env python3
"""
Learn what each DPS does by OBSERVING, not by writing.

Tuya devices report their state as a flat dict of numbered "DPS" (data points),
e.g. {'1': True, '2': 24, '4': 'hot'}. The numbers aren't documented by the
vendor. Instead of writing guessed values from the PC (which can push the device
into a bad state), this listens: a Tuya device PUSHES a dps update whenever a
setting changes, no matter the source — the physical/IR remote, a wall button,
or the app. So you operate the device the normal way and watch which number moves.

Two modes:

  # interactive (default): label an action, then perform it
  python learn_dps.py
      label> temp +1
      ... now press +1 on the remote, then Enter ...
      -> moved: {'2': (24, 25)}            # dps 2 is the setpoint

  # watch: just stream every change with a timestamp, Ctrl-C to stop
  python learn_dps.py --watch

Requirements:  pip install tinytuya ; export TUYA_KEY=...  (never hard-code it)

How it connects: same as verify_lan.py — straight to the device on the LAN via
tinytuya, using DEV_ID, DEV_IP and the key from the environment. No cloud. It opens
a TCP socket to the device on Tuya's local port (6668), encrypted with the local_key.
The one difference from verify_lan.py is set_socketPersistent(True) below: instead of
a single status() read, it holds the socket open so the device's spontaneous pushes
keep arriving, and reads them with d.receive().

ONE local connection at a time: a Tuya device accepts a single local socket, so this
script and the vendor app can't both be connected. Drive the device from its
IR/physical remote (which uses no LAN socket) while this runs; if you use the app
instead, close it first — otherwise the two fight over the device.
"""
import os
import sys
import time
import tinytuya

DEV_ID = "<DEV_ID_FROM_DUMP>"
DEV_IP = "<DEVICE_LAN_IP>"     # the device's LAN IP (192.168.x.x), NOT the dump's getIp
VERSION = 3.3                 # try 3.4 / 3.5 if 3.3 fails

WATCH = "--watch" in sys.argv


def need(value, env, prompt):
    """Resolve from an explicit value, then an env var, then an interactive prompt.
    A '<placeholder>' counts as unset, so an un-filled default triggers the prompt."""
    if value and not value.startswith("<"):
        return value
    env_val = os.environ.get(env)
    if env_val:
        return env_val
    return input(prompt).strip()


def diff(old, new):
    """dps that changed; pushes may carry only a subset, so compare to last-known."""
    return {k: (old.get(k), new[k]) for k in new if old.get(k) != new[k]}


def connect():
    # Same three values as verify_lan.py; each falls back to an env var, then a prompt,
    # so TUYA_KEY/DEV_ID/DEV_IP all work and nothing has to be hard-coded or committed.
    dev_id = need(DEV_ID, "DEV_ID", "Device id (getDevId from the dump): ")
    dev_ip = need(DEV_IP, "DEV_IP", "Device LAN IP (192.168.x.x, NOT the dump's getIp): ")
    key = need(None, "TUYA_KEY", "Local key (getLocalKey): ")
    d = tinytuya.Device(dev_id, dev_ip, key, version=VERSION)
    d.set_socketPersistent(True)   # keep the socket open so pushes arrive
    return d


def drain(d, state, timeout=1.0):
    """Read whatever the device pushes until it goes quiet; update state in place."""
    moved = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = d.receive()          # returns None on timeout, a dict on data
        if msg and "dps" in msg:
            moved.update(diff(state, msg["dps"]))
            state.update(msg["dps"])
            deadline = time.time() + timeout   # keep listening after each burst
    return moved


def main():
    d = connect()
    state = d.status().get("dps", {})
    print("baseline dps:", state)

    if WATCH:
        print("watching — operate the device, Ctrl-C to stop")
        try:
            while True:
                moved = drain(d, state, timeout=5.0)
                if moved:
                    print(time.strftime("%H:%M:%S"), moved)
        except KeyboardInterrupt:
            print("\nstopped.")
        return

    print("interactive — label an action, press it on the remote, then Enter.")
    print("blank label or Ctrl-C to finish. Here's the table so far:\n")
    table = {}
    try:
        while True:
            label = input("label> ").strip()
            if not label:
                break
            drain(d, state, timeout=0.3)      # flush anything stale first
            input(f"  do '{label}' now, then press Enter...")
            moved = drain(d, state, timeout=1.5)
            print(f"  -> moved: {moved or 'nothing (try again / slower)'}")
            for dps, (_, after) in moved.items():
                table.setdefault(dps, []).append(f"{label}={after}")
    except KeyboardInterrupt:
        print()

    print("\n=== DPS table (yours, specific to this product) ===")
    for dps in sorted(table, key=lambda x: (len(x), x)):
        print(f"  dps {dps}: {', '.join(table[dps])}")


if __name__ == "__main__":
    main()

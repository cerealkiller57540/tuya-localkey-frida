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

ONE local connection at a time: a Tuya device accepts a single local socket. Use
the IR/physical remote (no LAN connection) while this runs, or close the vendor
app first — otherwise the app and this script fight over the device.
"""
import os
import sys
import time
import tinytuya

DEV_ID = "<DEV_ID_FROM_DUMP>"
DEV_IP = "<DEVICE_LAN_IP>"
VERSION = 3.3                 # try 3.4 / 3.5 if 3.3 fails

WATCH = "--watch" in sys.argv


def diff(old, new):
    """dps that changed; pushes may carry only a subset, so compare to last-known."""
    return {k: (old.get(k), new[k]) for k in new if old.get(k) != new[k]}


def connect():
    d = tinytuya.Device(DEV_ID, DEV_IP, os.environ["TUYA_KEY"], version=VERSION)
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

#!/usr/bin/env python3
"""
Learn what each DPS does by OBSERVING, not by writing.

Tuya devices report their state as a flat dict of numbered "DPS" (data points),
e.g. {'1': True, '2': 24, '4': 'hot'}. The numbers aren't documented by the
vendor. Instead of writing guessed values from the PC (which can push the device
into a bad state), this watches: change one setting the normal way, see which
number moves.

Two modes:

  # interactive (default): label an action, then perform it
  python learn_dps.py
      label> temp +1
      ... now press +1 on the device, then Enter ...
      -> moved: {'2': (24, 25)}            # dps 2 is the setpoint

  # watch: just stream every change with a timestamp, Ctrl-C to stop
  python learn_dps.py --watch

  # poll: for firmwares that never push (common on AC modules), read status()
  # every N seconds and diff instead of waiting for pushes. Combines with --watch.
  python learn_dps.py --poll        # every 1 s
  python learn_dps.py --watch --poll 2

  # protocol version: 3.3 by default; try 3.4 / 3.5 if the first read gives Err 914
  python learn_dps.py --version 3.4

Requirements:  pip install tinytuya ; export TUYA_KEY=...  (never hard-code it)
Run it from the repo folder: it reuses need() and explain() from verify_lan.py.

How it connects: same as verify_lan.py — straight to the device on the LAN via
tinytuya, using DEV_ID, DEV_IP and the key from the environment. No cloud. It opens
a TCP socket to the device on Tuya's local port (6668), encrypted with the local_key,
and keeps it open (set_socketPersistent(True)) so the device's spontaneous pushes
keep arriving; it reads them with d.receive(). With --poll it calls status() instead.

What the device can see — this decides what you can use to change a setting:
  - ONE local connection at a time. While this script holds it, the vendor app and
    any integration (Home Assistant's tuya_local...) can't use the LAN link: close
    or disable them first, or the script reads one frozen baseline and nothing else.
  - The device's own buttons or a wall panel wired to the Tuya module: seen.
  - An IR/RF remote that talks to the APPLIANCE, not to the Tuya Wi-Fi module, can
    be invisible: the unit changes, the Tuya module never learns about it.
  - Not every firmware pushes on its own; if nothing moves, retry with --poll.
"""
import time
import argparse
import tinytuya

from verify_lan import need, explain, version_arg, default_version

DEV_ID = "<DEV_ID_FROM_DUMP>"
DEV_IP = "<DEVICE_LAN_IP>"     # the device's LAN IP (192.168.x.x), NOT the dump's getIp


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Learn what each Tuya DPS does by watching it change.")
    ap.add_argument("--watch", action="store_true", help="stream every change, Ctrl-C to stop")
    ap.add_argument("--poll", nargs="?", type=float, const=1.0, default=None, metavar="SECONDS",
                    help="read status() every SECONDS (default 1) instead of waiting for pushes")
    ap.add_argument("--version", type=version_arg, default=None,
                    help="Tuya protocol version (default 3.3, or $TUYA_VERSION)")
    args = ap.parse_args(argv)
    if args.poll is not None and args.poll <= 0:
        ap.error("--poll needs a positive number of seconds")
    if args.version is None:
        try:
            args.version = default_version()
        except argparse.ArgumentTypeError as e:
            ap.error(f"TUYA_VERSION: {e}")
    return args


def diff(old, new):
    """dps that changed; pushes may carry only a subset, so compare to last-known."""
    return {k: (old.get(k), new[k]) for k in new if old.get(k) != new[k]}


def apply(state, msg, moved):
    """Fold one tinytuya reply into state/moved. Ignores what isn't a dps update:
    None (nothing received), heartbeats, error dicts, a dps that isn't a dict."""
    if isinstance(msg, dict) and isinstance(msg.get("dps"), dict):
        moved.update(diff(state, msg["dps"]))
        state.update(msg["dps"])
        return True
    if isinstance(msg, dict) and "Err" in msg:
        print("  device error:", explain(msg)[1])
    return False


def connect(version):
    # Same three values as verify_lan.py; each falls back to an env var, then a prompt,
    # so TUYA_KEY/DEV_ID/DEV_IP all work and nothing has to be hard-coded or committed.
    dev_id = need(DEV_ID, "DEV_ID", "Device id (getDevId from the dump): ")
    dev_ip = need(DEV_IP, "DEV_IP", "Device LAN IP (192.168.x.x, NOT the dump's getIp): ")
    key = need(None, "TUYA_KEY", "Local key (getLocalKey): ")
    d = tinytuya.Device(dev_id, dev_ip, key, version=version)
    d.set_socketPersistent(True)   # keep the socket open so pushes arrive
    return d


def poll(d, state, timeout, every):
    """Polling mode: call status() every `every` seconds until timeout."""
    moved = {}
    deadline = time.time() + timeout
    while True:
        apply(state, d.status(), moved)
        if time.time() + every > deadline:
            return moved
        time.sleep(every)


def drain(d, state, timeout=1.0, every=None):
    """Collect changes for `timeout` seconds: pushes by default, status() polls if
    `every` is set. Updates state in place, returns {dps: (before, after)}."""
    if every:
        return poll(d, state, timeout, every)
    moved = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        if apply(state, d.receive(), moved):      # receive() -> None on timeout
            deadline = time.time() + timeout      # keep listening after each burst
    return moved


def main(argv=None):
    args = parse_args(argv)
    every = args.poll
    d = connect(args.version)

    first = d.status()
    ok, message = explain(first)
    if not ok:
        # An empty baseline would make every later dps look "moved"; stop here.
        print("first read failed:", message)
        return 1
    state = dict(first["dps"])
    print("baseline dps:", state)

    if args.watch:
        how = f"polling every {every:g} s" if every else "listening for pushes"
        print(f"watching ({how}) — operate the device, Ctrl-C to stop")
        try:
            while True:
                moved = drain(d, state, timeout=5.0, every=every)
                if moved:
                    print(time.strftime("%H:%M:%S"), moved)
        except KeyboardInterrupt:
            print("\nstopped.")
        return 0

    print("interactive — label an action, do it on the device, then Enter.")
    print("blank label or Ctrl-C to finish. Here's the table so far:\n")
    table = {}
    try:
        while True:
            label = input("label> ").strip()
            if not label:
                break
            drain(d, state, timeout=0.3, every=every)      # flush anything stale first
            input(f"  do '{label}' now, then press Enter...")
            # A poll needs at least two reads after the change to catch a slow update.
            moved = drain(d, state, timeout=max(1.5, 2 * every) if every else 1.5,
                          every=every)
            print(f"  -> moved: {moved or 'nothing (try again / slower, or --poll)'}")
            for dps, (_, after) in moved.items():
                table.setdefault(dps, []).append(f"{label}={after}")
    except KeyboardInterrupt:
        print()

    print("\n=== DPS table (yours, specific to this product) ===")
    for dps in sorted(table, key=lambda x: (len(x), x)):
        print(f"  dps {dps}: {', '.join(table[dps])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

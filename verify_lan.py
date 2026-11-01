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

Exit code: 0 = key works, 1 = the device answered with an error, 2 = bad arguments.
"""
import os
import sys
import argparse
import tinytuya

# Leave these as-is to be prompted, or paste your dump values in.
DEV_ID = "<DEV_ID_FROM_DUMP>"        # getDevId
DEV_IP = "<DEVICE_LAN_IP>"           # the device's LAN IP (192.168.x.x), NOT getIp

VERSIONS = [3.1, 3.2, 3.3, 3.4, 3.5]

# tinytuya doesn't raise on network/protocol failures: status() returns
# {'Error': ..., 'Err': '<code>', 'Payload': ...}. These are its codes (tinytuya
# core/error_helper.py) with what they mean for THIS use, i.e. a fresh local key.
HINTS = {
    "901": "can't open TCP 6668 on that IP. Wrong IP, device off, or another client "
           "(the vendor app, Home Assistant's tuya_local) already holds the device's "
           "single local connection.",
    "902": "the device accepted the connection but never answered. Retry; if it "
           "persists, try another --version.",
    "904": "the device answered but the reply couldn't be decoded. Usually the wrong "
           "--version (try 3.4, then 3.5), sometimes the wrong key.",
    "905": "nothing reachable at that address. Check the IP (the dump's getIp is often "
           "your PUBLIC IP, not the device's LAN one) and that the PC can reach that "
           "subnet.",
    "914": "wrong local key or wrong protocol version. Re-check the key from the dump "
           "(no spaces), then try --version 3.4 / 3.5.",
}


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


def explain(status):
    """Turn a tinytuya status() reply into (ok, message). Handles the incomplete
    shapes too: None, an error dict, or a dict without 'dps'."""
    if not isinstance(status, dict):
        return False, f"no reply from the device ({status!r})."
    if isinstance(status.get("dps"), dict):
        return True, f"OK, the key works. dps = {status['dps']}"
    if "Err" in status or "Error" in status:
        code = str(status.get("Err", ""))
        hint = HINTS.get(code, "see tinytuya's error codes.")
        return False, f"Err {code or '?'} ({status.get('Error', 'unknown')}): {hint}"
    return False, f"unexpected reply, no 'dps' in it: {status!r}"


def version_arg(text):
    """argparse type for --version: accepts the numbers tinytuya speaks."""
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}")
    if v not in VERSIONS:
        raise argparse.ArgumentTypeError(f"{text} not in {VERSIONS}")
    return v


def default_version():
    return version_arg(os.environ.get("TUYA_VERSION", "3.3"))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Read a Tuya device's DPS over the LAN.")
    ap.add_argument("dev_id", nargs="?", help="getDevId from the dump")
    ap.add_argument("dev_ip", nargs="?", help="device LAN IP (192.168.x.x), NOT getIp")
    ap.add_argument("--version", type=version_arg, default=None,
                    help="Tuya protocol version (default 3.3, or $TUYA_VERSION); "
                         "try 3.4 / 3.5 if 3.3 gives Err 914 or 904")
    args = ap.parse_args(argv)
    if args.version is None:
        try:
            args.version = default_version()
        except argparse.ArgumentTypeError as e:
            ap.error(f"TUYA_VERSION: {e}")
    return args


def main(argv=None):
    args = parse_args(argv)
    dev_id = need(args.dev_id or DEV_ID, "DEV_ID", "Device id (getDevId from the dump): ")
    dev_ip = need(args.dev_ip or DEV_IP, "DEV_IP",
                  "Device LAN IP (192.168.x.x, NOT the dump's getIp): ")
    key = need(None, "TUYA_KEY", "Local key (getLocalKey): ")

    d = tinytuya.Device(dev_id, dev_ip, key, version=args.version)
    d.set_socketPersistent(False)

    ok, message = explain(d.status())
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

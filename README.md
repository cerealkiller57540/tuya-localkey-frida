# Extracting a Tuya `local_key` from a vendor app with Frida

*A walkthrough for the awkward case: a Tuya-based device you **cannot pair in Tuya
Smart / Smart Life**, so none of the usual ways to get its local key apply.*

Some smart devices run on Tuya's platform but ship inside a **vendor's own app** (a
rebranded white-label build) instead of the generic Tuya Smart app. A climate /
air-conditioner controller is a typical example: the vendor app pairs it with an
extra setup step that the stock Tuya Smart app doesn't perform, so the device never
shows up in a Tuya Smart account at all.

That blocks every common route to the `local_key` you need for local control:

- **Tuya IoT cloud (developer account)** — works only for devices linked to a Tuya
  Smart / Smart Life account you can attach to a cloud project. This device isn't in
  one.
- **`tinytuya wizard`** — same dependency on the Tuya cloud link.
- **`tuya-convert` / flashing** — firmware-dependent, increasingly patched, and
  overkill when you only want to read a key.

But the key has to exist *somewhere the app can reach it*, because the app talks to
the device over your LAN. On Tuya's Android SDK it lives in a model object
(`DeviceBean`) **in cleartext in the app's memory** once you're logged in. So we read
it out of RAM with [Frida](https://frida.re/) — no decryption, no touching the device
hardware, no cloud.

---

## ⚠️ Scope and ethics

This is for **devices you own**, so that **you** can run them locally instead of
depending on someone's cloud. That's a legitimate interoperability use.

- Only do this on hardware you own and an app account that is yours.
- You are reading *your own* key out of *your own* session on *your own* emulator.
- Don't use this to attack other people's devices, bypass someone else's license, or
  redistribute keys/credentials.
- **Never commit the extracted key, device id, or app credentials** to a repo. Every
  example below uses placeholders; keep it that way.

---

## How it works (one paragraph)

The Tuya Android SDK keeps each device's metadata — id, name, product id, and the
`local_key` — in an object whose class name ends in `DeviceBean`. Frida attaches to
the running app, enumerates loaded classes to find those beans, walks the live
instances on the Java heap (`Java.choose`), and calls the getters. `getLocalKey()`
returns the key as a plain string. That's the whole trick.

---

## Prerequisites

- An **Android emulator** (AVD), image **Android 14, x86_64, google_apis**. An
  emulator is `su`-able out of the box, which is what frida-server needs — you don't
  have to root a physical phone. ARM-only apps still run via the emulator's ARM
  translation layer.
- **frida-server** on the device (match the server version to your host's major, but
  see the pin below), pushed to `/data/local/tmp` and started as root.
- **`frida` 16.x on the host** — this is the one that bites people. See the next
  section.
- `adb`, and `pip install "frida==16.*" tinytuya`.

### 🔴 Pin host Frida to 16.x — 17 silently finds nothing

Frida **17** removed the **bundled Java bridge** from the core. On 17, `Java.perform`
/ `Java.choose` are not available in the default runtime, so the hook loads, runs, and
reports **zero devices** with no obvious error — you'll think the app doesn't hold the
key when in fact your tooling can't see Java at all.

Use **`frida` 16.x** on the host (`pip install "frida==16.*"`) with a matching
**frida-server 16.x** on the device, and the Java bridge is there. (If you must stay on
17, you now have to add the external `frida-java-bridge` yourself; pinning 16 is far
less trouble for a one-off extraction.)

---

## For Windows users (no Linux background needed)

This whole thing runs fine on Windows — nothing here needs a Linux box. A few terms
that the steps take for granted:

- **AVD / emulator** — the **Android Virtual Device**, a phone that runs as a window on
  your PC. It ships with **Android Studio** (free). In Android Studio: *More Actions →
  Virtual Device Manager → Create device*, pick any phone, and for the system image
  choose **Android 14, x86_64, "Google APIs"** (the plain *Google APIs* image, **not**
  "Google Play" — the Play image locks out `su`, which you need). `emulator` and `adb`
  are then under `%LOCALAPPDATA%\Android\Sdk\platform-tools\` and
  `...\emulator\`; add those two folders to your `PATH` so the commands below work from
  any terminal.
- **`adb`** — *Android Debug Bridge*, the command-line cable between your PC and the
  phone/emulator. `adb push` copies a file onto the device, `adb shell` runs a command
  on it, `adb install` sideloads an APK.
- **`su` / "rooted"** — administrator (`root`) on the Android side. frida-server has to
  run as root to read another app's memory. The emulator's *Google APIs* image gives
  you `su` for free, which is exactly why we use an emulator instead of trying to root a
  real phone.
- **frida-server** — a small Linux binary **for Android** (the ARM/x86 build) that you
  copy onto the emulator and run there. It's the counterpart to the `frida` Python
  package on your PC. Download the one matching your host `frida` version (16.x) and the
  emulator's architecture (`x86_64`) from Frida's GitHub releases, and un-`.xz` it first
  (7-Zip opens `.xz`).

### Which terminal — and the `MSYS_NO_PATHCONV` thing

The commands are written for a **Bash-style** shell. On Windows you have two easy ways
to get one:

- **Git Bash** (installed with *Git for Windows*) — closest to what's written here.
- **WSL** (*Windows Subsystem for Linux*) — also fine; `adb`/`emulator` on your PATH are
  still callable from inside it.

You can run it all from **PowerShell** too, but mind two differences:

- `export TUYA_KEY=...` (Bash) becomes `$env:TUYA_KEY = '...'` in PowerShell.
- Backgrounding with a trailing `&` is a Bash thing; in PowerShell start frida-server
  with `Start-Process` or just leave its `adb shell` running in its own window.

**The `MSYS_NO_PATHCONV=1` prefix is only for Git Bash.** Git Bash helpfully "fixes"
any argument that looks like a Unix path — so `/data/local/tmp/frida-server` silently
becomes `C:/Program Files/Git/data/local/tmp/...` and the push lands in the wrong place
with no error. `MSYS_NO_PATHCONV=1` in front of the command turns that rewriting off.
In **PowerShell or WSL this problem doesn't exist**, so drop the prefix there.

---

## Step by step

### 1. Start the emulator and frida-server

```bash
# Start the AVD (headless-ish, modest resources — don't starve your workstation):
emulator -avd <your_avd> -gpu swiftshader_indirect -cores 4 -memory 4096

# Push and launch frida-server (download the build matching your host frida 16.x).
# MSYS_NO_PATHCONV=1 is a Git Bash workaround (see "For Windows users" above); drop it
# in PowerShell or WSL.
MSYS_NO_PATHCONV=1 adb push frida-server /data/local/tmp/frida-server
MSYS_NO_PATHCONV=1 adb shell "su 0 chmod 755 /data/local/tmp/frida-server"
MSYS_NO_PATHCONV=1 adb shell "su 0 /data/local/tmp/frida-server &"

# Make the device's frida port reachable at 127.0.0.1:27042 on the host:
adb forward tcp:27042 tcp:27042
```

The exact same thing in **PowerShell** (no `MSYS_NO_PATHCONV`, and keep frida-server in
its own window so it stays alive):

```powershell
emulator -avd <your_avd> -gpu swiftshader_indirect -cores 4 -memory 4096
adb push frida-server /data/local/tmp/frida-server
adb shell "su 0 chmod 755 /data/local/tmp/frida-server"
Start-Process adb -ArgumentList 'shell','su 0 /data/local/tmp/frida-server'
adb forward tcp:27042 tcp:27042
```

### 2. Install the vendor app and log in

Install the vendor APK in the emulator (drag-and-drop, or `adb install`). Open it,
sign in with your own account, and pair / let it discover the device so it appears in
the app's device list. **The key is only in memory once the app has loaded the device**,
so get to the screen where you can see it before dumping.

> If the app is split (XAPK / `config.*.apk`), install the base + the matching ABI
> split together (`adb install-multiple base.apk config.arm64_v8a.apk`).

### 3. Dump the key

With the app in the **foreground**, run [`dump_localkey.py`](dump_localkey.py) and pass
the app's visible process name:

```bash
python dump_localkey.py "<App display name>"
```

You'll get the list of `*DeviceBean` classes it found, then a row per live device:

```json
{
  "devices": [
    {
      "cls": "com.<vendor>.<...>.DeviceBean",
      "getDevId": "<DEVICE_ID>",
      "getName": "<Device name>",
      "getLocalKey": "<THIS IS THE LOCAL KEY>",
      "getProductId": "<product id>",
      "getIp": "<device LAN IP>"
    }
  ]
}
```

`getLocalKey` is what you came for. `getDevId` and `getIp` let you match each key to
the right device when you have several.

> **The output contains a live secret.** Don't paste it into a terminal you log, a
> screenshot, or a commit. Pipe it into a secret store, or copy the one field you need
> by hand.

### 4. Verify it works, locally

Confirm the key against the device on the LAN with no cloud in the loop, using
[`verify_lan.py`](verify_lan.py):

```bash
export TUYA_KEY='<the local key>'   # from the dump; keep it out of the script
python verify_lan.py
```

In PowerShell the env var is set differently: `$env:TUYA_KEY = '<the local key>'`, then
`python verify_lan.py`.

A `{'dps': {...}}` dict means success. `Error 905` almost always means a wrong key or
the wrong protocol `version` (try `3.4` / `3.5` if `3.3` fails).

### 5. (Method, not solution) Map the DPS

Tuya reports device state as numbered **DPS** (data points) with no vendor
documentation: `{'1': True, '2': 24, '4': 'hot', ...}`. To learn what each one does,
change one, read the whole state back, see what moved, and restore it —
[`probe_dps.py`](probe_dps.py) does exactly that in a safe apply/read/restore loop:

```bash
python probe_dps.py 1 true        # a boolean dps
python probe_dps.py 2 24          # an integer (e.g. a setpoint)
python probe_dps.py 4 '"cool"'    # a string enum — JSON, so quote it
```

Watch the device while you do it (display, a beep, a vent moving) and write down what
each DPS and each enum value means. That label table is specific to *your* product —
the reusable part is the probing method, not the numbers.

### 6. Use it locally, then clean up

Point a local integration at the device with the key — e.g. Home Assistant's
[`tuya_local`](https://github.com/make-all/tuya-local) or LocalTuya — and you're off
the cloud. Then:

- **Delete any file that held the key in cleartext** (dump output, scratch JSON).
- Store the key in a password/secret manager, not in a dotfile next to your configs.
- **Shut the emulator down** and stop frida-server when you're done.

---

## Files in this repo

| File | What it is |
| --- | --- |
| [`dump_localkey.py`](dump_localkey.py) | The Frida script: hooks `*DeviceBean`, prints id / name / `local_key` / ip. |
| [`verify_lan.py`](verify_lan.py) | Confirms the key by reading device state over the LAN with `tinytuya`. |
| [`probe_dps.py`](probe_dps.py) | Apply / read / restore loop to reverse-engineer what each DPS does. |

## A note on stability

The `local_key` **rotates** if you re-pair the device or reset it. If local control
suddenly stops, the key changed — dump it again. And a Tuya device accepts only **one
local connection at a time**: the vendor app and your local integration will fight over
it if both poll at once.

## Credits

Built on the shoulders of [Frida](https://frida.re/) and
[`tinytuya`](https://github.com/jasonacox/tinytuya).

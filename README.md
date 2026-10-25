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

> Not comfortable doing all this by hand? Feed your AI assistant in VS Code these files
> and let the magic happen.

---

## How it works (one paragraph)

The Tuya Android SDK keeps each device's metadata — id, name, product id, and the
`local_key` — in an object whose class name ends in `DeviceBean`. Frida attaches to
the running app, enumerates loaded classes to find those beans, walks the live
instances on the Java heap (`Java.choose`), and calls the getters. `getLocalKey()`
returns the key as a plain string. That's the whole trick.

---

## Prerequisites

- **Python 3** (3.8+) on your PC — the scripts here are Python, and `frida` / `tinytuya`
  install with `pip`. On Windows, grab it from [python.org](https://www.python.org/downloads/)
  and tick **"Add python.exe to PATH"** in the installer, or run `winget install
  Python.Python.3.12`; check with `python --version`.
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

A subtler trap, if you installed 16 into a **virtualenv**: running plain `python`
(or `python3`) can still pick up a system-wide frida 17 instead of your venv's 16, and
then the dump fails with a cryptic `frida.ProtocolError: unable to communicate with
remote frida-server … major versions match`. That error *is* the version mismatch.
Confirm which frida you're actually running before you dump:

```bash
python -c "import frida; print(frida.__version__)"   # must print 16.x
```

If it prints 17, activate your venv (or call its python by full path). `dump_localkey.py`
also checks this itself and exits early with a clear message rather than that traceback.

---

## For Windows users (no Linux background needed)

This whole thing runs fine on Windows — nothing here needs a Linux box. A few terms
that the steps take for granted:

- **AVD / emulator** — the **Android Virtual Device**, a phone that runs as a window on
  your PC. You get it either from **Android Studio** (free, big GUI) or from the SDK
  command-line tools alone (smaller, scripted). Whichever route, use the system image
  **Android 14, x86_64, "Google APIs"** — the plain *Google APIs* image, **not** "Google
  Play", because the Play image locks out `su`, which you need. Starting from nothing?
  Follow **"From zero on Windows (PowerShell)"** just below — it installs everything and
  creates the AVD for you.
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

### From zero on Windows (PowerShell): install the SDK and make an AVD

No Android Studio, nothing installed? This gets you from a bare Windows box to a running
emulator, entirely in **PowerShell** (the blue terminal — press `Win`, type *PowerShell*,
Enter). Copy each block as-is. It installs into `C:\Android` to keep paths simple.

**1. Java.** The SDK tools need a JDK. If `java -version` prints nothing, install one
(`winget install Microsoft.OpenJDK.17`) and reopen PowerShell.

**2. Download the command-line tools** and lay them out the way `sdkmanager` insists on
(it must live in `cmdline-tools\latest\`):

```powershell
$SDK = "C:\Android"
New-Item -ItemType Directory -Force "$SDK\cmdline-tools" | Out-Null
# Grab "Command line tools only" for Windows from https://developer.android.com/studio#command-line-tools-only
# (the .zip near the bottom of that page), then point $zip at your download:
$zip = "$HOME\Downloads\commandlinetools-win-latest.zip"
Expand-Archive $zip "$SDK\cmdline-tools" -Force
# the zip unpacks to a folder called "cmdline-tools" — rename it to "latest":
Rename-Item "$SDK\cmdline-tools\cmdline-tools" "latest"
```

You should now have `C:\Android\cmdline-tools\latest\bin\sdkmanager.bat`.

**3. Install the pieces** — platform tools (`adb`), the emulator, and the exact image
this guide needs (**Android 14 = API 34, `google_apis`, `x86_64`** — the `google_apis`
image, *not* `google_apis_playstore`, because Play Store images block `su`):

```powershell
$mgr = "$SDK\cmdline-tools\latest\bin\sdkmanager.bat"
& $mgr --sdk_root=$SDK "platform-tools" "emulator" "platform-tools" `
       "system-images;android-34;google_apis;x86_64"
& $mgr --sdk_root=$SDK --licenses     # press y at each prompt
```

**4. Put `adb` and `emulator` on your PATH** so the commands in the steps below just work,
in this window and in every new one:

```powershell
# this window, right now:
$env:Path = "$SDK\platform-tools;$SDK\emulator;$env:Path"
# and permanently, for future windows (then reopen PowerShell once):
setx Path "$SDK\platform-tools;$SDK\emulator;$([Environment]::GetEnvironmentVariable('Path','User'))"
```

Check both resolve: `adb --version` and `emulator -version` should each print something.

**5. Create the AVD** — a virtual phone using that image. Name it `tuya_avd` (the steps
below use that name):

```powershell
$avd = "$SDK\cmdline-tools\latest\bin\avdmanager.bat"
& $avd create avd -n tuya_avd -k "system-images;android-34;google_apis;x86_64" -d pixel_6
# "Do you wish to create a custom hardware profile?" -> just press Enter (no)
emulator -list-avds        # should print: tuya_avd
```

That's the one-time setup. From here, **Step 1** starts that AVD and everything follows.

> Already have Android Studio? Then the SDK is at `%LOCALAPPDATA%\Android\Sdk` instead of
> `C:\Android` — add *its* `platform-tools` and `emulator` folders to your PATH (step 4),
> make the AVD from *Device Manager → Create device* (same image: Android 14, x86_64,
> **Google APIs**), and skip the rest of this section.

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

Pick **one** shell and use its block — don't mix lines from both. If you followed the
PowerShell setup above, use the PowerShell block. First, the file you need on hand:
**frida-server for Android**, the **16.x** build matching your host `frida` and the `x86_64`
architecture (from [Frida's releases](https://github.com/frida/frida/releases) — the
`frida-server-16.*-android-x86_64.xz`; un-`.xz` it with 7-Zip so you have a plain
`frida-server` file). Run these from the folder that file is in.

**PowerShell** (keep frida-server in its own window so it stays alive):

```powershell
# Start the AVD (modest resources — don't starve your workstation). This window stays
# busy running the emulator; open a NEW PowerShell window for the adb lines below.
emulator -avd tuya_avd -gpu swiftshader_indirect -cores 4 -memory 4096

# --- in a second PowerShell window: ---
adb wait-for-device                                    # wait until the phone is up
adb push frida-server /data/local/tmp/frida-server
adb shell "su 0 chmod 755 /data/local/tmp/frida-server"
Start-Process adb -ArgumentList 'shell','su 0 /data/local/tmp/frida-server'  # its own window
adb forward tcp:27042 tcp:27042                        # frida port -> 127.0.0.1:27042
```

<details><summary><b>Git Bash / WSL</b> (same thing, Bash syntax) — click to expand</summary>

```bash
# MSYS_NO_PATHCONV=1 is a Git Bash workaround (see "For Windows users" above); drop it
# in WSL (and it's harmless there anyway).
emulator -avd tuya_avd -gpu swiftshader_indirect -cores 4 -memory 4096

# --- in a second terminal: ---
adb wait-for-device
MSYS_NO_PATHCONV=1 adb push frida-server /data/local/tmp/frida-server
MSYS_NO_PATHCONV=1 adb shell "su 0 chmod 755 /data/local/tmp/frida-server"
MSYS_NO_PATHCONV=1 adb shell "su 0 /data/local/tmp/frida-server &"
adb forward tcp:27042 tcp:27042
```

</details>

Quick sanity check that the PC can see the device's Frida: `frida-ps -U` should list the
emulator's running apps. Empty list or an error → frida-server isn't running as root, or
you're on frida 17 (see the pin above).

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

The script re-posts the `adb forward` for the frida port itself (removing any stale
one first), so you can re-run it as often as you like without the `Address already in
use` you'd get from setting the forward twice by hand. If you'd rather manage the
forward yourself, add `--no-adb`.

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

### 5. (Method, not solution) Map the DPS — by watching, not writing

Tuya reports device state as numbered **DPS** (data points) with no vendor
documentation: `{'1': True, '2': 24, '4': 'hot', ...}`. You *could* write guessed
values from the PC, but that means guessing each one's type and range and can push the
device into a bad state. The safer method is **observation**: the device pushes a dps
update whenever a setting changes — *including when the change comes from the IR/physical
remote or the app* — so you operate it the normal way and watch which number moved.
[`learn_dps.py`](learn_dps.py) listens and does exactly that:

```bash
# interactive: label an action, perform it, see what moved — builds the table for you
python learn_dps.py
#   label> temp +1
#     do 'temp +1' now, then press Enter...
#     -> moved: {'2': (24, 25)}        # dps 2 is the setpoint

# or just stream every change with a timestamp (Ctrl-C to stop)
python learn_dps.py --watch
```

**How it connects (and why the remote matters).** `learn_dps.py` talks to the device
exactly like `verify_lan.py` in step 4 — straight to it on the LAN with `tinytuya`,
using the same three things from the dump (`DEV_ID`, `DEV_IP`, and `TUYA_KEY` from the
environment). No cloud is involved. It opens a TCP connection to the device on Tuya's
local port (6668); the `local_key` encrypts that conversation (protocol 3.3).

The one line that makes it a *listener* rather than a one-shot read is
`set_socketPersistent(True)`: `verify_lan.py` opens the socket, reads the state once,
and closes it, whereas `learn_dps.py` holds the connection open. While it stays open,
the device **pushes** a `dps` message of its own accord every time a setting changes —
and the script reads those with `d.receive()` and diffs them against the last state it
saw.

Here's the catch that makes your idea work: a Tuya device accepts **only one local
connection at a time**, so the script's connection and the vendor app's connection
can't both be up. Driving the device from its **IR / physical remote** sidesteps this
completely — the remote uses no LAN socket at all, so it can change settings while the
script listens, with nothing to fight over. (Operate it from the app instead and you'd
have to close the app first — at which point you couldn't operate it.)

This assumes the device is reachable directly on your LAN (same subnet, not walled off
on a guest VLAN) — the normal case for a home Tuya device, and already proven the moment
`verify_lan.py` got a reply in step 4. The label table the script prints is specific to
*your* product; the reusable part is the observe-and-diff method, not the numbers.

### 6. Turn the table into a device config

So you've watched the remote and you have a table: dps 1 is on/off, dps 2 is the
setpoint, dps 4 is the mode, and so on. **Now what?** That table *is* the device
config — you just write it down in the shape your integration expects. For Home
Assistant's [`tuya_local`](https://github.com/make-all/tuya-local) that's a small YAML
file, one entry per dps, each saying what the number *is* (a boolean? a temperature? a
mode name?) and, where the raw value isn't obvious, how it maps to a human value.

Here's a **generic** heat/cool unit. The values are placeholders that show the shape —
replace them with the numbers from *your own* `learn_dps` table:

```yaml
name: Generic AC
products:
  - id: xxxxxxxxxxxxxxxx          # the productId from the Frida dump (optional, see below)
    manufacturer: Example
    model: Generic AC
entities:
  - entity: climate
    dps:
      - id: 1                     # learn_dps said: power on/off
        type: boolean
        name: hvac_mode
        mapping:
          - dps_val: false
            value: "off"
          - dps_val: true
            constraint: mode       # pair on/off with dps 4 to pick heat vs cool…
            conditions:
              - dps_val: cold
                value: cool
              - dps_val: hot
                value: heat
      - id: 2                     # learn_dps said: temp +1 moved this 24 -> 25
        type: integer
        name: temperature
        range:
          min: 16
          max: 30
      - id: 3                     # learn_dps said: reads room temp, moves on its own
        type: integer
        name: current_temperature
        mapping:
          - scale: 10             # device sends 235 -> means 23.5 °C
      - id: 4                     # learn_dps said: mode button cycled cold/hot/wind
        type: string
        name: mode
        hidden: true              # drives the mapping above; no entity of its own
```

The three dps types you'll use most: **boolean** (on/off, a switch), **integer** (a
temperature, a timer, a percentage — often with a `range:` and a `scale:` when the device
multiplies by 10 or 100), and **string** (a named mode like `cold`/`hot`/`auto`, which you
remap to the words the integration wants). A `mapping:` is just a lookup table from the
raw dps value to a friendly one; `constraint:` links two dps together when the real
setting needs both (on/off *and* mode = "cool" vs "heat").

Drop the file in `custom_components/tuya_local/devices/` and restart Home Assistant, then
add the integration (configure it manually by IP, since you're not using the cloud). You
won't type the product id anywhere: the integration **matches the file by its dps
signature** — it offers you a device-type list, and your config appears because the dps
ids and *types* you declared are the ones the device actually reports. The `products:`
block is just a bonus hint. So the catch is there: get a `type:` wrong and your file
silently drops off the list. If it's missing, or a control does nothing once added, that
dps is mislabeled — go back to `learn_dps.py`, move that one setting, and fix the number
or the type.

> That same table works for **LocalTuya** too (it asks you, per dps, "is this a switch, a
> number, a select?" in its config flow) and for a plain `tinytuya` script
> (`d.set_value(2, 25)` to set dps 2 to 25). The device config is the portable part.
>
> ⚠️ A file under `custom_components/` is **overwritten when the integration updates**.
> Keep a copy somewhere safe and drop it back after an update — or, better, open a PR to
> [make-all/tuya-local](https://github.com/make-all/tuya-local) so your device ships with
> the integration and everyone with that model gets it for free.

### 7. Use it locally, then clean up

You're off the cloud now. Last thing — don't leave the key lying around:

- **Delete any file that held the key in cleartext** (dump output, scratch JSON).
- Store the key in a password/secret manager, not in a dotfile next to your configs.
- **Shut the emulator down** and stop frida-server when you're done.

---

## Files in this repo

| File | What it is |
| --- | --- |
| [`dump_localkey.py`](dump_localkey.py) | The Frida script: hooks `*DeviceBean`, prints id / name / `local_key` / productId / ip. |
| [`verify_lan.py`](verify_lan.py) | Confirms the key by reading device state over the LAN with `tinytuya`. |
| [`learn_dps.py`](learn_dps.py) | Listens for dps changes while you operate the device from its remote, to learn what each DPS means. |

## A note on stability

The `local_key` **rotates** if you re-pair the device or reset it. If local control
suddenly stops, the key changed — dump it again. And a Tuya device accepts only **one
local connection at a time**: the vendor app and your local integration will fight over
it if both poll at once.

## Credits

Built on the shoulders of [Frida](https://frida.re/) and
[`tinytuya`](https://github.com/jasonacox/tinytuya).

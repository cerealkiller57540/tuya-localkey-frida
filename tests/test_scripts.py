"""Tests for the helper logic. No device, no emulator, no tinytuya install needed.

    python -m unittest discover -s tests -v

The dedup test runs the real Frida JS from dump_localkey.py under Node with a fake
`Java` object; it is skipped when `node` is not on PATH.
"""
import os
import re
import sys
import json
import shutil
import argparse
import subprocess
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Stand-in for tinytuya so the scripts import anywhere; tests patch Device as needed.
sys.modules.setdefault("tinytuya", types.SimpleNamespace(Device=None))

import verify_lan  # noqa: E402
import learn_dps   # noqa: E402


class FakeDevice:
    """Replays a scripted list of replies for status() and receive()."""

    def __init__(self, status=(), receive=()):
        self._status = list(status)
        self._receive = list(receive)

    def status(self):
        return self._status.pop(0) if self._status else {"dps": {}}

    def receive(self):
        return self._receive.pop(0) if self._receive else None


class TestNeed(unittest.TestCase):
    def test_explicit_value_wins(self):
        with mock.patch.dict(os.environ, {"DEV_IP": "10.0.0.9"}):
            self.assertEqual(verify_lan.need("192.168.1.5", "DEV_IP", "?"), "192.168.1.5")

    def test_placeholder_falls_back_to_env(self):
        with mock.patch.dict(os.environ, {"DEV_IP": "10.0.0.9"}):
            self.assertEqual(verify_lan.need("<DEVICE_LAN_IP>", "DEV_IP", "?"), "10.0.0.9")

    def test_empty_env_falls_back_to_prompt(self):
        with mock.patch.dict(os.environ, {"TUYA_KEY": ""}), \
             mock.patch("builtins.input", return_value="  abc  ") as ask:
            self.assertEqual(verify_lan.need(None, "TUYA_KEY", "key: "), "abc")
            ask.assert_called_once_with("key: ")


class TestVersion(unittest.TestCase):
    def test_default_and_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(verify_lan.parse_args([]).version, 3.3)
        with mock.patch.dict(os.environ, {"TUYA_VERSION": "3.5"}):
            self.assertEqual(verify_lan.parse_args([]).version, 3.5)

    def test_flag_beats_env(self):
        with mock.patch.dict(os.environ, {"TUYA_VERSION": "3.5"}):
            self.assertEqual(learn_dps.parse_args(["--version", "3.4"]).version, 3.4)

    def test_rejects_unknown(self):
        self.assertRaises(argparse.ArgumentTypeError, verify_lan.version_arg, "3.9")
        self.assertRaises(argparse.ArgumentTypeError, verify_lan.version_arg, "abc")
        with mock.patch.dict(os.environ, {"TUYA_VERSION": "abc"}), \
             mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            verify_lan.parse_args([])

    def test_poll_must_be_positive(self):
        self.assertEqual(learn_dps.parse_args(["--poll"]).poll, 1.0)
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            learn_dps.parse_args(["--poll", "0"])


class TestExplain(unittest.TestCase):
    def test_success(self):
        ok, msg = verify_lan.explain({"dps": {"1": True}})
        self.assertTrue(ok)
        self.assertIn("'1': True", msg)

    def test_known_codes_get_a_hint(self):
        for code, word in [("901", "6668"), ("904", "--version"), ("905", "IP"),
                           ("914", "local key")]:
            ok, msg = verify_lan.explain({"Error": "x", "Err": code, "Payload": None})
            self.assertFalse(ok)
            self.assertIn(f"Err {code}", msg)
            self.assertIn(word, msg)

    def test_incomplete_replies(self):
        for reply in (None, "", {}, {"dps": None}, {"dps": "garbage"}, {"t": 123}):
            ok, _ = verify_lan.explain(reply)
            self.assertFalse(ok, reply)

    def test_unknown_code(self):
        ok, msg = verify_lan.explain({"Error": "Something", "Err": "999"})
        self.assertFalse(ok)
        self.assertIn("Err 999", msg)


class TestDiff(unittest.TestCase):
    def test_changed_and_new_keys(self):
        self.assertEqual(learn_dps.diff({"1": True, "2": 24}, {"2": 25, "4": "hot"}),
                         {"2": (24, 25), "4": (None, "hot")})

    def test_partial_push_is_not_a_change(self):
        # A push carrying only dps 2 must not report the absent dps 1 as changed.
        self.assertEqual(learn_dps.diff({"1": True, "2": 24}, {"2": 24}), {})


class TestDrain(unittest.TestCase):
    def test_push_mode_skips_junk(self):
        d = FakeDevice(receive=[None, {"Err": "904", "Error": "x"}, {"dps": "bad"},
                                {"dps": {"2": 25}}, {"t": 1}])
        state = {"1": True, "2": 24}
        with mock.patch("builtins.print"):
            moved = learn_dps.drain(d, state, timeout=0.2)
        self.assertEqual(moved, {"2": (24, 25)})
        self.assertEqual(state, {"1": True, "2": 25})

    def test_poll_mode_collects_across_reads(self):
        d = FakeDevice(status=[{"dps": {"1": True, "2": 24}}, {"Err": "902", "Error": "x"},
                               {"dps": {"1": False, "2": 24}}])
        state = {"1": True, "2": 24}
        with mock.patch("builtins.print"), mock.patch("time.sleep"):
            moved = learn_dps.drain(d, state, timeout=0.05, every=0.01)
        self.assertEqual(moved, {"1": (True, False)})

    def test_main_stops_on_failed_first_read(self):
        d = FakeDevice(status=[{"Err": "914", "Error": "Check device key or version"}])
        with mock.patch.object(learn_dps, "connect", return_value=d), \
             mock.patch("builtins.print") as out:
            self.assertEqual(learn_dps.main([]), 1)
        self.assertIn("914", " ".join(str(a) for c in out.call_args_list for a in c.args))


JAVA_STUB = r"""
var sent = [];
function send(o) { sent.push(o); }
function bean(f) {
  var b = {};
  ['getDevId','getName','getLocalKey','getProductId','getUuid','getMac','getIp']
    .forEach(function (m) {
      b[m] = function () { if (f[m] === 'THROW') throw new Error('x'); return f[m]; };
    });
  return b;
}
var HEAP = %s;
var Java = {
  perform: function (fn) { fn(); },
  enumerateLoadedClasses: function (cb) { Object.keys(HEAP).concat(['x.Other'])
    .forEach(cb.onMatch); cb.onComplete(); },
  choose: function (cls, cb) { (HEAP[cls] || []).map(bean).forEach(cb.onMatch);
    cb.onComplete(); }
};
"""


@unittest.skipUnless(shutil.which("node"), "node not on PATH")
class TestDumpDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "dump_localkey.py"), encoding="utf-8") as f:
            src = f.read()
        cls.js = re.search(r'JS = r"""(.*?)"""', src, re.S).group(1)

    def run_js(self, heap):
        code = JAVA_STUB % json.dumps(heap) + self.js + \
            "\nconsole.log(JSON.stringify(sent));"
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                             check=True)
        sent = json.loads(out.stdout)
        return sent[0]["classes"], sent[1]["devices"]

    def test_merges_copies_by_devid(self):
        heap = {"a.DeviceBean": [
            {"getDevId": "d1", "getLocalKey": "K1", "getName": "Clim", "getIp": ""},
            {"getDevId": "d1", "getLocalKey": "K1", "getName": None, "getIp": "1.2.3.4"},
            {"getDevId": "d2", "getLocalKey": "K2", "getMac": "THROW"},
        ]}
        classes, devices = self.run_js(heap)
        self.assertEqual(classes, ["a.DeviceBean"])
        self.assertEqual([d["getDevId"] for d in devices], ["d1", "d2"])
        d1 = devices[0]
        self.assertEqual(d1["instances"], 2)
        self.assertEqual(d1["getName"], "Clim")       # first non-empty kept
        self.assertEqual(d1["getIp"], "1.2.3.4")      # gap filled from a later copy
        self.assertNotIn("otherLocalKeys", d1)
        self.assertNotIn("getMac", devices[1])        # a throwing getter is skipped

    def test_flags_a_disagreeing_key(self):
        heap = {"a.DeviceBean": [{"getDevId": "d1", "getLocalKey": "K1"},
                                 {"getDevId": "d1", "getLocalKey": "K9"},
                                 {"getDevId": "d1", "getLocalKey": "K9"}]}
        _, devices = self.run_js(heap)
        self.assertEqual(devices[0]["getLocalKey"], "K1")
        self.assertEqual(devices[0]["otherLocalKeys"], ["K9"])
        self.assertEqual(devices[0]["instances"], 3)

    def test_rows_without_devid_are_kept_apart(self):
        heap = {"a.DeviceBean": [{"getLocalKey": "K1"}, {"getLocalKey": "K2"}],
                "b.GroupDeviceBean": [{"getDevId": "g1"}]}
        _, devices = self.run_js(heap)
        self.assertEqual(len(devices), 3)


if __name__ == "__main__":
    unittest.main()

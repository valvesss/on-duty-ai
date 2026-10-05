"""HTTP API tests: the real request handler on an ephemeral port, with a temporary home and database.
No camera or microphone is touched; the engine loop isn't started."""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import calibration  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import on_duty  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        config.HOME, config.CONFIG_PATH, config.CUSTOM_PHRASES = cls.tmp, cls.tmp / "config.json", cls.tmp / "phrases.json"
        db.DB_PATH, db._con = cls.tmp / "t.db", None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), on_duty.Dashboard)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        if db._con:
            db._con.close()
        db._con = None

    def setUp(self):
        on_duty.CFG.clear()
        on_duty.CFG.update(config.merge({"onboarded": True, "port": self.port}))
        on_duty.STATE["cmds"].clear()
        on_duty.STATE["pause_until"] = 0.0
        on_duty.STATE["status"] = {}

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Type", ""), data, r

    def json(self, method, path, body=None):
        code, _, data, _ = self.call(method, path, body)
        return code, json.loads(data)

    def test_pages_are_served(self):
        for p in ("/", "/setup", "/settings", "/summary"):
            code, ctype, data, _ = self.call("GET", p)
            self.assertEqual(code, 200, p)
            self.assertIn("text/html", ctype)
            self.assertIn(b"<title>on-duty", data)

    def test_dashboard_redirects_to_setup_until_onboarded(self):
        on_duty.CFG["onboarded"] = False
        code, _, _, r = self.call("GET", "/")
        self.assertEqual((code, r.getheader("Location")), (302, "/setup"))

    def test_assets(self):
        for p, t in (("/logo.svg", "svg"), ("/favicon.ico", "icon"), ("/radar.js", "javascript"), ("/apple-touch-icon.png", "png")):
            code, ctype, data, _ = self.call("GET", p)
            self.assertEqual(code, 200, p)
            self.assertIn(t, ctype)
            self.assertGreater(len(data), 100)

    def test_status_is_json_and_skips_series_by_default(self):
        on_duty.STATE["series"].append([1, 0, 0, False, False, False])
        _, s = self.json("GET", "/status")
        self.assertNotIn("series", s)
        _, s = self.json("GET", "/status?series=1")
        self.assertIn("series", s)

    def test_config_roundtrip_and_validation(self):
        code, j = self.json("POST", "/api/config", {"name": "  Sam  ", "tone": "ruthless", "mirror": False, "rotate": 99, "retention_days": -5})
        self.assertEqual(code, 200)
        cfg = j["config"]
        self.assertEqual((cfg["name"], cfg["tone"], cfg["mirror"], cfg["rotate"], cfg["retention_days"]), ("Sam", "ruthless", False, 25.0, 0))
        self.assertTrue(json.loads(config.CONFIG_PATH.read_text())["name"] == "Sam")  # persisted

    def test_bad_times_are_rejected(self):
        code, j = self.json("POST", "/api/config", {"schedule": {"start": "25:99"}})
        self.assertEqual(code, 400)
        self.assertIn("HH:MM", j["error"])

    def test_unknown_tone_falls_back(self):
        _, j = self.json("POST", "/api/config", {"tone": "nope"})
        self.assertEqual(j["config"]["tone"], "balanced")

    def test_port_cannot_be_changed_from_the_page(self):
        _, j = self.json("POST", "/api/config", {"port": 1})
        self.assertEqual(j["config"]["port"], self.port)

    def test_pause_and_resume(self):
        self.json("POST", "/api/pause", {"minutes": 30})
        self.assertGreater(on_duty.STATE["pause_until"], 0)
        self.json("POST", "/api/pause", {"minutes": 0})
        self.assertEqual(on_duty.STATE["pause_until"], 0)

    def test_engine_commands_are_queued(self):
        self.json("POST", "/api/calibrate", {"action": "start", "kind": "zone"})
        self.json("POST", "/api/feedback", {"kind": "missed"})
        self.json("POST", "/api/focus", {"action": "start", "minutes": 25})
        self.json("POST", "/api/level")
        acts = [c["action"] for c in on_duty.STATE["cmds"]]
        self.assertEqual(acts, ["start", "feedback", "focus_start", "level"])

    def test_setups_list_and_phrases(self):
        db.put("setup:cam0-1d-1920x1080", {"label": "1 display", "zones": [{"name": "main", "pitch": 1, "yaw": 0, "gaze": 0.3}], "created": 5})
        _, setups = self.json("GET", "/api/setups")
        self.assertEqual([s["label"] for s in setups], ["1 display"])
        self.assertEqual(self.json("GET", "/api/phrases")[1]["custom"], False)
        config.CUSTOM_PHRASES.write_text(json.dumps({"levels": [["a", "b"]] * 5, "back": {}}))
        self.assertEqual(self.json("GET", "/api/phrases")[1], {"custom": True, "lines": 10, "path": str(config.CUSTOM_PHRASES)})
        self.json("POST", "/api/phrases", {"action": "remove"})
        self.assertFalse(config.CUSTOM_PHRASES.exists())

    def test_export_and_clear_history(self):
        db.record("alert", n=1, cause="face", level=1, said="hi")
        code, ctype, data, r = self.call("GET", "/api/export")
        self.assertEqual(code, 200)
        self.assertIn("attachment", r.getheader("Content-Disposition"))
        self.assertIn(b'"said": "hi"', data)
        _, j = self.json("POST", "/api/data", {"action": "clear_history"})
        self.assertGreaterEqual(j["removed"], 1)
        self.assertEqual(db.count_events(), 0)

    def test_summary_and_about(self):
        _, s = self.json("GET", "/api/summary?days=7")
        self.assertEqual(len(s["days"]), 7)
        _, a = self.json("GET", "/api/about")
        self.assertRegex(a["version"], r"^\d+\.\d+\.\d+")

    def test_sample_line(self):
        _, j = self.json("GET", "/api/sample?lang=en_US&tone=balanced&name=Sam")
        self.assertTrue(j["text"])

    def test_calibration_helpers_exist_for_setup_signature(self):
        self.assertTrue(calibration.setup_signature(0, 1, 1920, 1080).startswith("cam0"))


if __name__ == "__main__":
    unittest.main()

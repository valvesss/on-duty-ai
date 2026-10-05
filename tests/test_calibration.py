import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import calibration as c  # noqa: E402


class Summarize(unittest.TestCase):
    def test_needs_enough_samples(self):
        self.assertIsNone(c.summarize([(5, 0, 0.3)] * 3))

    def test_drops_outliers(self):
        s = c.summarize([(5.0 + i * 0.1, 2, 0.3) for i in range(10)] + [(40, 30, 0.9)])
        self.assertLess(abs(s["pitch"] - 5.4), 0.5)
        self.assertEqual(s["n"], 10)

    def test_all_outliers_is_none(self):
        self.assertIsNone(c.summarize([(i * 20, 0, 0) for i in range(8)]))


class Zones(unittest.TestCase):
    zones = [{"name": "main", "yaw": 0, "pitch": 4, "gaze": 0.3}, {"name": "side", "yaw": 30, "pitch": 9, "gaze": 0.3}]

    def test_nearest_by_yaw(self):
        self.assertEqual(c.nearest_zone(self.zones, 27)["name"], "side")
        self.assertEqual(c.nearest_zone(self.zones, -5)["name"], "main")

    def test_none_without_zones(self):
        self.assertIsNone(c.nearest_zone([], 0))


class Thresholds(unittest.TestCase):
    zones = [{"pitch": 3, "gaze": 0.25}]

    def test_half_way_to_the_phone(self):
        t = c.derive_thresholds(self.zones, {"pitch": 23, "gaze": 0.55})
        self.assertEqual(t["pitch_delta"], 10.0)
        self.assertEqual(t["gaze_delta"], c.GAZE_FLOOR)  # 0.15 measured, lifted to the jitter floor

    def test_sensitivity_scales(self):
        phone = {"pitch": 23, "gaze": 0.55}
        self.assertGreater(c.derive_thresholds(self.zones, phone, "relaxed")["pitch_delta"],
                           c.derive_thresholds(self.zones, phone, "strict")["pitch_delta"])

    def test_clamped(self):
        self.assertEqual(c.derive_thresholds(self.zones, {"pitch": 80, "gaze": 0.3})["pitch_delta"], 20.0)
        self.assertEqual(c.derive_thresholds(self.zones, {"pitch": 8, "gaze": 0.3})["pitch_delta"], c.PITCH_FLOOR)
        self.assertEqual(c.derive_thresholds(self.zones, {"pitch": 20, "gaze": 0.31})["gaze_delta"], c.GAZE_FLOOR)

    def test_no_clear_signal_keeps_defaults(self):
        self.assertEqual(c.derive_thresholds(self.zones, {"pitch": 4, "gaze": 0.26}), {})

    def test_needs_both(self):
        self.assertEqual(c.derive_thresholds([], {"pitch": 20, "gaze": 0.5}), {})
        self.assertEqual(c.derive_thresholds(self.zones, None), {})


class Quality(unittest.TestCase):
    def test_good(self):
        self.assertTrue(c.quality(0.95, 120, 0.3, 0.5, 1.0)["ok"])

    def test_each_issue(self):
        q = lambda **k: c.quality(**{"face_ratio": .95, "brightness": 120, "face_h": .3, "cx": .5, "pitch_mad": 1, **k})["issues"]  # noqa: E731
        self.assertEqual(q(face_ratio=.3), ["no_face"])
        self.assertEqual(q(brightness=30), ["dark"])
        self.assertEqual(q(brightness=240), ["bright"])
        self.assertEqual(q(face_h=.1), ["far"])
        self.assertEqual(q(face_h=.8), ["close"])
        self.assertEqual(q(cx=.05), ["off_center"])
        self.assertEqual(q(pitch_mad=6), ["moving"])


class Drift(unittest.TestCase):
    def test_hysteresis(self):
        self.assertFalse(c.drift_state(False, 7))
        self.assertTrue(c.drift_state(False, 10))
        self.assertTrue(c.drift_state(True, 7))   # stays on until it falls below DRIFT_OFF
        self.assertFalse(c.drift_state(True, 5))

    def test_clamp(self):
        self.assertEqual(c.clamp_drift(30), 8.0)
        self.assertEqual(c.clamp_drift(-30), -8.0)
        self.assertEqual(c.clamp_drift(3), 3)


class Signature(unittest.TestCase):
    def test_changes_with_displays_and_camera(self):
        a = c.setup_signature(0, 1, 1280, 720)
        self.assertNotEqual(a, c.setup_signature(0, 2, 1280, 720))
        self.assertNotEqual(a, c.setup_signature(1, 1, 1280, 720))
        self.assertEqual(a, c.setup_signature(0, 1, 1280, 720))


class Capture(unittest.TestCase):
    def feed(self, session, n, pitch=5.0, yaw=1.0, gaze=0.3, jitter=0.4, bright=120.0, face=True):
        for i in range(n):
            wobble = ((i % 5) - 2) * jitter
            session.add((pitch + wobble, yaw, gaze) if face else None, bright, 0.3, 0.5)

    def test_good_zone_capture(self):
        s = c.CaptureSession("zone", "Main screen", 8, 100.0)
        self.feed(s, 40)
        self.assertTrue(s.done(108.1))
        r = s.result()
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["summary"]["pitch"], 5.0, delta=0.5)
        self.assertTrue(r["quality"]["ok"])

    def test_no_face(self):
        s = c.CaptureSession("zone", "x", 8, 0.0)
        self.feed(s, 30, face=False)
        r = s.result()
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "no_face")
        self.assertIn("no_face", r["quality"]["issues"])

    def test_moving_too_much(self):
        s = c.CaptureSession("zone", "x", 8, 0.0)
        for i in range(30):
            s.add((i * 3.0, 0.0, 0.3), 120.0, 0.3, 0.5)
        r = s.result()
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "moving")

    def test_live_progress_and_quality(self):
        s = c.CaptureSession("phone", "phone", 10, 0.0)
        self.feed(s, 10, bright=30.0)
        live = s.live(5.0)
        self.assertEqual(live["progress"], 0.5)
        self.assertIn("dark", live["quality"]["issues"])

    def test_full_flow_to_thresholds(self):
        z = c.CaptureSession("zone", "main", 8, 0.0)
        self.feed(z, 40, pitch=4.0)
        p = c.CaptureSession("phone", "phone", 8, 0.0)
        self.feed(p, 40, pitch=24.0, gaze=0.6)
        zr, pr = z.result(), p.result()
        t = c.derive_thresholds([{**zr["summary"], "name": "main"}], pr["summary"], "normal")
        self.assertAlmostEqual(t["pitch_delta"], 10.0, delta=0.6)
        self.assertGreater(t["gaze_delta"], 0.1)


class Detection(unittest.TestCase):
    def test_head_drop_triggers(self):
        self.assertTrue(c.is_face_down(14, 0.0, 12, 0.25, False))
        self.assertFalse(c.is_face_down(5, 0.0, 12, 0.25, False))

    def test_gaze_alone_needs_to_be_strong(self):
        self.assertFalse(c.is_face_down(0, 0.3, 12, 0.25, False))   # noisy eyes alone: no
        self.assertTrue(c.is_face_down(0, 0.5, 12, 0.25, False))    # very strongly down: yes
        self.assertTrue(c.is_face_down(7, 0.3, 12, 0.25, False))    # eyes down + head part-way: yes

    def test_turned_head_never_counts(self):
        self.assertFalse(c.is_face_down(30, 0.9, 12, 0.25, True))
        self.assertTrue(c.turned_away(40, 5))
        self.assertFalse(c.turned_away(10, 5))

    def test_noise_floor_lifts_the_threshold(self):
        noisy = [((i * 7) % 25) - 12.0 for i in range(100)]
        self.assertGreater(c.noise_floor(noisy), 10)
        self.assertEqual(c.noise_floor([0.0] * 10), 0.0)  # not enough data yet
        th = c.effective_thresholds({"pitch_delta": 5, "gaze_delta": 0.14}, {}, {}, c.noise_floor(noisy), True)
        self.assertGreaterEqual(th["pitch_delta"], c.noise_floor(noisy))

    def test_uncalibrated_is_calmer(self):
        a = c.effective_thresholds({"pitch_delta": 12, "gaze_delta": 0.25}, {}, {}, 0, True)
        b = c.effective_thresholds({"pitch_delta": 12, "gaze_delta": 0.25}, {}, {}, 0, False)
        self.assertGreater(b["pitch_delta"], a["pitch_delta"])

    def test_feedback_nudges_and_clamps(self):
        t = {}
        for _ in range(20):
            t = c.adjust_tuning(t, "false_positive")
        self.assertEqual(t["pitch"], 12.0)
        for _ in range(20):
            t = c.adjust_tuning(t, "missed")
        self.assertEqual(t["pitch"], -4.0)

    def test_separation_verdict(self):
        z = [{"pitch": -10, "gaze": 0.4}]
        self.assertEqual(c.separation(z, {"pitch": 8})["verdict"], "good")
        self.assertEqual(c.separation(z, {"pitch": -2})["verdict"], "weak")
        self.assertEqual(c.separation(z, {"pitch": -9})["verdict"], "none")

    def test_smoother_kills_single_flips(self):
        s = c.Smoother(3)
        s.push((0.0, 0.0, 0.3))
        s.push((1.0, 0.0, 0.3))
        out = s.push((40.0, 0.0, 0.3))  # one-frame flip
        self.assertEqual(out[0], 1.0)
        self.assertIsNone(s.push(None))


class PhoneRatio(unittest.TestCase):
    def test_phone_ratio_reported(self):
        s = c.CaptureSession("phone", "phone", 8, 0.0)
        for i in range(20):
            s.add((20.0, 0.0, 0.6), 120.0, 0.3, 0.5, phone=(i % 2 == 0))
        self.assertEqual(s.result()["phone_ratio"], 0.5)
        self.assertTrue(s.live(1.0)["phone_seen"])


class SetupSwitching(unittest.TestCase):
    """The desk/monitor story: home (1 display), office (2 displays), back again."""

    def profile(self, pitch, phone_pitch):
        return {"label": "x", "zones": [{"name": "main", "pitch": pitch, "yaw": 0, "gaze": 0.3}], "created": 1,
                "phone": {"pitch": phone_pitch, "gaze": 0.6}, "sensitivity": "normal"}

    def test_never_then_new_setup(self):
        self.assertEqual(c.load_setup(None, False)["state"], "never")
        self.assertEqual(c.load_setup(None, True)["state"], "new_setup")

    def test_plug_calibrate_unplug_replug(self):
        saved = {}
        home, office = c.setup_signature(0, 1, 1920, 1080), c.setup_signature(0, 2, 1920, 1080)
        self.assertNotEqual(home, office)
        # first run at home: nothing known
        self.assertEqual(c.load_setup(saved.get(home), bool(saved))["state"], "never")
        saved[home] = self.profile(-10, 6)                       # calibrate at home
        # plug the external monitor: a different setup, but the user has calibrated before
        s = c.load_setup(saved.get(office), bool(saved))
        self.assertEqual((s["state"], s["zones"]), ("new_setup", []))
        saved[office] = self.profile(2, 24)                      # calibrate the office
        # unplug: home comes back with ITS zones and ITS thresholds
        h = c.load_setup(saved.get(home), bool(saved))
        self.assertEqual((h["state"], h["zones"][0]["pitch"]), ("ok", -10))
        # replug: office again, different thresholds
        o = c.load_setup(saved.get(office), bool(saved))
        self.assertEqual((o["state"], o["zones"][0]["pitch"]), ("ok", 2))
        self.assertNotEqual(h["overrides"], o["overrides"])

    def test_old_profiles_get_current_floors(self):
        p = self.profile(0, 8)  # an old build would have saved a 4-5° trigger for this
        self.assertGreaterEqual(c.load_setup(p, True)["overrides"]["pitch_delta"], c.PITCH_FLOOR)


if __name__ == "__main__":
    unittest.main()

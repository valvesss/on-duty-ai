import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logic import Debounce, FocusSession, TabPresence  # noqa: E402


class DebounceTests(unittest.TestCase):
    def test_needs_consecutive_samples_to_turn_on(self):
        d = Debounce(on=3, off=3)
        self.assertEqual([d.update(x) for x in (True, True, False, True, True, True)], [False, False, False, False, False, True])

    def test_needs_consecutive_samples_to_turn_off(self):
        d = Debounce(on=1, off=3)
        d.update(True)
        self.assertEqual([d.update(x) for x in (False, False, True, False, False, False)], [True, True, True, True, True, False])

    def test_flicker_never_flips(self):
        d = Debounce(on=3, off=3)
        self.assertFalse(any(d.update(i % 2 == 0) for i in range(20)))


class FocusTests(unittest.TestCase):
    def test_runs_and_completes(self):
        f = FocusSession(25, 1000.0)
        self.assertEqual(f.remaining(1000.0), 1500.0)
        self.assertFalse(f.done(2499.0))
        self.assertTrue(f.done(2500.0))
        f.slip()
        f.slip()
        f.add_phone(1.5)
        r = f.finish(2500.0)
        self.assertEqual((r["completed"], r["slips"], r["phone_min"], r["actual"]), (True, 2, 1.5, 25.0))

    def test_stopped_early_is_not_completed(self):
        f = FocusSession(50, 0.0)
        r = f.finish(600.0)
        self.assertFalse(r["completed"])
        self.assertEqual(r["actual"], 10.0)

    def test_actual_never_exceeds_planned(self):
        r = FocusSession(10, 0.0).finish(99999.0)
        self.assertEqual(r["actual"], 10.0)


if __name__ == "__main__":
    unittest.main()


class TabPresenceTests(unittest.TestCase):
    def test_waits_for_the_first_tab_then_quits(self):
        p = TabPresence(0.0, boot_grace=90, grace=20)
        self.assertFalse(p.should_quit(89.0))
        self.assertTrue(p.should_quit(90.0))

    def test_stays_while_a_tab_pings(self):
        p = TabPresence(0.0)
        for t in range(0, 600, 10):
            p.ping("a", float(t))
            self.assertFalse(p.should_quit(float(t)))

    def test_quits_after_the_last_tab_says_bye(self):
        p = TabPresence(0.0)
        p.ping("a", 10.0), p.ping("b", 10.0)
        p.bye("a", 20.0)
        self.assertFalse(p.should_quit(100.0))  # b is still open
        p.bye("b", 100.0)
        self.assertFalse(p.should_quit(119.0))  # reload grace
        self.assertTrue(p.should_quit(120.0))

    def test_reload_survives(self):
        p = TabPresence(0.0)
        p.ping("a", 10.0)
        p.bye("a", 50.0)
        p.ping("a2", 52.0)
        self.assertFalse(p.should_quit(100.0))

    def test_silent_tabs_expire(self):
        p = TabPresence(0.0, stale=150, grace=20)
        p.ping("a", 10.0)
        self.assertFalse(p.should_quit(159.0))
        self.assertFalse(p.should_quit(160.0))  # expired here, grace starts
        self.assertTrue(p.should_quit(180.0))

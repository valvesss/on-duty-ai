import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logic import Debounce, FocusSession  # noqa: E402


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

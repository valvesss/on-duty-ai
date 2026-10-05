import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stats  # noqa: E402

NOW = dt.datetime(2026, 10, 7, 15, 0).timestamp()  # a Wednesday


def at(day_offset: int, hour: int) -> float:
    return (dt.datetime(2026, 10, 7, hour, 0) + dt.timedelta(days=day_offset)).timestamp()


def back(day, hour, minutes):
    s = at(day, hour)
    return {"kind": "back", "t": s + minutes * 60, "start": s, "minutes": minutes}


class WeeklySummary(unittest.TestCase):
    def test_empty_week(self):
        r = stats.summarize([], [], NOW)
        self.assertEqual(len(r["days"]), 7)
        self.assertEqual((r["total_min"], r["sessions"], r["best_day"], r["worst_day"], r["trend_pct"]), (0.0, 0, None, None, None))
        self.assertEqual(r["worst_hours"], [])

    def test_totals_days_and_hours(self):
        ev = [back(0, 10, 5), back(0, 10, 3), back(-1, 15, 12), {"kind": "alert", "t": at(0, 10), "n": 1, "level": 1}]
        r = stats.summarize(ev, [], NOW)
        self.assertEqual(r["total_min"], 20.0)
        self.assertEqual(r["days"][-1]["minutes"], 8.0)
        self.assertEqual(r["days"][-1]["scoldings"], 1)
        self.assertEqual(r["worst_day"], r["days"][-2]["date"])
        self.assertEqual(r["best_day"], r["days"][-1]["date"])
        self.assertEqual(r["worst_hours"][0], {"hour": 15, "minutes": 12.0})
        self.assertEqual(r["longest_session_min"], 12.0)
        self.assertEqual(r["heat"][-1][10], 8.0)

    def test_trend_against_previous_week(self):
        ev = [back(0, 10, 10), back(-8, 10, 20)]  # this week 10 min, the week before 20
        r = stats.summarize(ev, [], NOW)
        self.assertEqual((r["total_min"], r["prev_total_min"], r["trend_pct"]), (10.0, 20.0, -50))

    def test_old_events_ignored(self):
        self.assertEqual(stats.summarize([back(-30, 10, 99)], [], NOW)["total_min"], 0.0)

    def test_focus_blocks(self):
        f = [{"start": at(0, 9), "actual": 25.0, "completed": True, "slips": 1}, {"start": at(-1, 9), "actual": 10.0, "completed": False, "slips": 3}]
        r = stats.summarize([], f, NOW)["focus"]
        self.assertEqual(r, {"blocks": 2, "completed": 1, "minutes": 35.0, "slips": 4})


if __name__ == "__main__":
    unittest.main()

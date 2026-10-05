"""Weekly summary from the event log. Pure functions over plain dicts, so they're unit-tested without a database.

A phone session is attributed, in full, to the day and hour it *started*."""

import datetime as dt


def _day(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(ts).date()


def summarize(events: list[dict], focus: list[dict], now: float, days: int = 7) -> dict:
    today = _day(now)
    span = [today - dt.timedelta(days=days - 1 - i) for i in range(days)]
    prev = {today - dt.timedelta(days=days + i) for i in range(days)}
    idx = {d: i for i, d in enumerate(span)}
    out_days = [{"date": d.isoformat(), "dow": d.weekday(), "minutes": 0.0, "sessions": 0, "scoldings": 0} for d in span]
    heat = [[0.0] * 24 for _ in span]
    prev_total, longest = 0.0, 0.0
    for e in events:
        if e.get("kind") == "back":
            d = _day(e["start"] or e["t"])
            m = float(e.get("minutes") or 0)
            if d in idx:
                row = out_days[idx[d]]
                row["minutes"] += m
                row["sessions"] += 1
                heat[idx[d]][dt.datetime.fromtimestamp(e["start"] or e["t"]).hour] += m
                longest = max(longest, m)
            elif d in prev:
                prev_total += m
        elif e.get("kind") == "alert" and _day(e["t"]) in idx:
            out_days[idx[_day(e["t"])]]["scoldings"] += 1
    for r in out_days:
        r["minutes"] = round(r["minutes"], 1)
    total = round(sum(r["minutes"] for r in out_days), 1)
    by_hour = [sum(row[h] for row in heat) for h in range(24)]
    active = [r for r in out_days if r["sessions"]]
    tracked = [r for r in out_days if r["sessions"] or r["scoldings"]]  # days with any recorded activity
    f = [x for x in focus if _day(x["start"]) in idx]
    return {
        "days": out_days, "total_min": total, "prev_total_min": round(prev_total, 1),
        "trend_pct": round((total - prev_total) / prev_total * 100) if prev_total else None,
        "sessions": sum(r["sessions"] for r in out_days), "scoldings": sum(r["scoldings"] for r in out_days),
        "best_day": min(tracked, key=lambda r: r["minutes"])["date"] if len(tracked) >= 2 else None,
        "worst_day": max(active, key=lambda r: r["minutes"])["date"] if active else None,
        "heat": [[round(v, 1) for v in row] for row in heat],
        "worst_hours": [{"hour": h, "minutes": round(by_hour[h], 1)} for h in sorted(range(24), key=lambda h: -by_hour[h])[:3] if by_hour[h] > 0],
        "longest_session_min": round(longest, 1),
        "focus": {"blocks": len(f), "completed": sum(1 for x in f if x["completed"]), "minutes": round(sum(x["actual"] for x in f), 1),
                  "slips": sum(x["slips"] for x in f)},
    }

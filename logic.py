"""Small pure rules the engine uses: debouncing, focus sessions and open-tab presence. No OS, no camera, so they're unit-tested."""


class Debounce:
    """Turns a flickery boolean into a stable one: on after `on` consecutive truthy samples, off after `off` falsy ones."""

    def __init__(self, on: int = 3, off: int = 3):
        self.on, self.off, self.state, self._run = on, off, False, 0

    def update(self, value: bool) -> bool:
        if bool(value) == self.state:
            self._run = 0
        else:
            self._run += 1
            if self._run >= (self.off if self.state else self.on):
                self.state, self._run = bool(value), 0
        return self.state


class FocusSession:
    """A timed block of work. The engine calls slip() whenever you drift to the phone and add_phone() with the minutes."""

    def __init__(self, minutes: float, t0: float):
        self.minutes, self.t0, self.end = float(minutes), t0, t0 + float(minutes) * 60
        self.slips, self.phone_min = 0, 0.0

    def remaining(self, now: float) -> float:
        return max(0.0, self.end - now)

    def done(self, now: float) -> bool:
        return now >= self.end

    def slip(self) -> None:
        self.slips += 1

    def add_phone(self, minutes: float) -> None:
        self.phone_min += minutes

    def finish(self, now: float) -> dict:
        """The record to store/show. `completed` is true only if the full time ran."""
        return {"start": int(self.t0), "planned": self.minutes, "ended": int(min(now, self.end)),
                "actual": round(max(0.0, min(now, self.end) - self.t0) / 60, 1), "completed": now >= self.end,
                "slips": self.slips, "phone_min": round(self.phone_min, 1)}


class TabPresence:
    """The engine only runs while a dashboard tab is open. Tabs ping with an id every few seconds and say goodbye when they
    close; should_quit() is true once no tab is left (after `grace` s, so a reload survives) or when every tab has gone
    silent for `stale` s (crashed browser; backgrounded tabs are throttled to ~1 ping/min, so keep it above that).
    The first tab has `boot_grace` s to show up."""

    def __init__(self, t0: float, boot_grace: float = 90.0, grace: float = 20.0, stale: float = 150.0):
        self.tabs: dict[str, float] = {}
        self.grace, self.stale = grace, stale
        self.empty_since = t0 + boot_grace - grace

    def ping(self, tab: str, now: float) -> None:
        self.tabs[tab] = now

    def bye(self, tab: str, now: float) -> None:
        self.tabs.pop(tab, None)
        if not self.tabs:
            self.empty_since = now

    def should_quit(self, now: float) -> bool:
        self.tabs = {k: t for k, t in self.tabs.items() if now - t < self.stale}
        if self.tabs:
            self.empty_since = now
            return False
        return now - self.empty_since >= self.grace

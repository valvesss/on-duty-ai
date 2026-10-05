"""Small pure rules the engine uses: debouncing and focus sessions. No OS, no camera, so they're unit-tested."""


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

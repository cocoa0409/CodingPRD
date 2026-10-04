"""In-memory data store for the IRP benchmark implementation.

The store starts empty on every boot -- no seeding of any kind. All entities
are constructed through the declared API surface. Module-level dicts are
plain data containers keyed by entity id; a global sequence counter backs
ResourceCandidate.global_sequence_index.
"""

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock: fixed default 2026-09-01T00:00:00Z, never wall-clock.
# ---------------------------------------------------------------------------
class LogicalClock:
    """Server-controlled logical clock; settable via POST /_clock/set_current_utc."""

    _DEFAULT_ISO = "2026-09-01T00:00:00+00:00"

    def __init__(self):
        self._now = datetime.fromisoformat(self._DEFAULT_ISO)

    def set(self, iso_string: str):
        s = iso_string.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        return self._now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def date_iso(self) -> str:
        return self._now.strftime("%Y-%m-%d")

    def year(self) -> int:
        return self._now.year


clock = LogicalClock()


def _fresh_store():
    return {
        "plans": {},
        "forecasts": {},
        "resources": {},
        "portfolios": {},
        "candidates": {},
        "positions": {},
        "snapshots": {},
        "retirement_analyses": {},
        "comments": {},
        "intervenors": {},
        "testimonies": {},
        "sensitivities": {},
        "commitments": {},
        "conditions": {},
        "deviation_reports": {},
    }


class Store:
    """Mutable in-memory store. Instantiated once per process (fresh boot)."""

    def __init__(self):
        self._data = _fresh_store()
        self.candidate_seq = 0  # global_sequence_index counter, starts at 1 on first create
        self.clock = clock

    # -- typed accessors ---------------------------------------------------
    @property
    def plans(self):
        return self._data["plans"]

    @property
    def forecasts(self):
        return self._data["forecasts"]

    @property
    def resources(self):
        return self._data["resources"]

    @property
    def portfolios(self):
        return self._data["portfolios"]

    @property
    def candidates(self):
        return self._data["candidates"]

    @property
    def positions(self):
        return self._data["positions"]

    @property
    def snapshots(self):
        return self._data["snapshots"]

    @property
    def retirement_analyses(self):
        return self._data["retirement_analyses"]

    @property
    def comments(self):
        return self._data["comments"]

    @property
    def intervenors(self):
        return self._data["intervenors"]

    @property
    def testimonies(self):
        return self._data["testimonies"]

    @property
    def sensitivities(self):
        return self._data["sensitivities"]

    @property
    def commitments(self):
        return self._data["commitments"]

    @property
    def conditions(self):
        return self._data["conditions"]

    @property
    def deviation_reports(self):
        return self._data["deviation_reports"]


store = Store()

"""In-memory store and the logical clock.

Storage is deliberately process-local: one dictionary per collection, keyed
by the server-minted UUID.  Nothing is seeded, preloaded or persisted — a
fresh process starts with every collection empty (PRD section 2.4, and the
harness contract that every test rebuilds its world through the API).
"""

import datetime as _dt
import uuid

# ─── the logical clock (PRD 2.11 / endpoint table) ────────────────────────
# At server startup, before any call to /_clock/set_current_utc, the clock
# reads exactly 2026-09-01T00:00:00Z.  It never falls back to wall-clock time.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"


def _parse_utc(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if isinstance(value, _dt.datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def format_utc(dt):
    """Render an instant as ISO 8601 UTC.

    The fractional part is emitted at millisecond precision when the instant
    carries sub-second precision, and omitted when it does not, so a logical
    clock at a whole second renders exactly `...T00:00:00Z`.
    """
    dt = _parse_utc(dt)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def format_utc_millis(dt):
    """Always render three fractional digits (the envelope's request stamp)."""
    dt = _parse_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Clock:
    """The single logical clock that governs every time comparison."""

    def __init__(self):
        self.value = _parse_utc(DEFAULT_CLOCK_UTC)

    def now(self):
        return self.value

    def set(self, value):
        self.value = _parse_utc(value)
        return self.value


class Store:
    """All collections of the interface.  Created empty; never seeded."""

    def __init__(self):
        self.clock = Clock()
        self.reset()

    def reset(self):
        # Every persisted resource type from the entity relationship table.
        self.territories = {}
        self.depots = {}
        self.vehicles = {}
        self.bay_slots = {}
        self.cycles = {}
        self.waves = {}
        self.demand_signals = {}
        self.area_rules = {}
        self.exclusion_zones = {}
        self.expansion_requests = {}
        self.rides = {}
        self.pickup_locations = {}
        self.curb_rules = {}
        self.assistance_sessions = {}
        self.incident_reports = {}
        self.roadside_cases = {}
        self.roadside_teams = {}
        # Forecast weather tiers, recorded per (territory, service window).
        self.weather_tiers = {}

    # ─── identity and mutation helpers (PRD 2.4) ──────────────────────────

    def new_id(self):
        """A plain UUID with no type prefix or resource-name prefix."""
        return str(uuid.uuid4())

    def now(self):
        return self.clock.now()

    def stamp_create(self, row):
        """Mint id/created_at/updated_at/version for a brand new row."""
        now = self.now()
        row.setdefault("version", 1)
        row["created_at"] = format_utc(now)
        row["updated_at"] = format_utc(now)
        return row

    def touch(self, row):
        """A mutation by the server's own recomputation logic.

        Refreshes updated_at and advances version by exactly 1.  created_at is
        never part of a recomputation: it stays pinned to the row's creation
        instant so a derived-field write cannot reorder the battery/creation
        tie-break the selector and the wave allocator both rely on.
        """
        now = self.now()
        row["updated_at"] = format_utc(now)
        row["version"] = int(row.get("version", 1)) + 1
        return row


store = Store()
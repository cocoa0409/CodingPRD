"""In-memory data store and the logical ranch clock.

Everything lives in plain dicts keyed by id.  Nothing is persisted and nothing
is seeded: a fresh process starts with an entirely empty ranch.
"""

import datetime
import threading
import uuid

UTC = datetime.timezone.utc

# PRD 2.5: mandated startup default for the logical clock.
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def fmt_instant(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


class Store(object):
    COLLECTIONS = (
        "seasons",
        "cabins",
        "guests",
        "rider_assessments",
        "bookings",
        "horses",
        "horse_health_events",
        "activity_slots",
        "guide_assignments",
        "activity_reservations",
        "staff_members",
        "incident_reports",
    )

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self._last_ts = None

    # -- identity / timestamps -------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def wall_now(self):
        """Strictly increasing real-time instant, used for created_at/updated_at."""
        now = datetime.datetime.now(UTC)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + datetime.timedelta(milliseconds=1)
        self._last_ts = now
        return now

    def stamp(self):
        return fmt_instant(self.wall_now())

    # -- logical clock ---------------------------------------------------
    def clock_instant(self):
        return self.clock

    def clock_iso(self):
        return fmt_instant(self.clock)

    def clock_date(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt.astimezone(UTC)

    # -- generic row helpers ---------------------------------------------
    def insert(self, collection, row, versioned=True):
        row["id"] = row.get("id") or self.new_id()
        row["created_at"] = self.stamp()
        row["_seq"] = self.next_seq()
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        getattr(self, collection)[row["id"]] = row
        return row

    def touch(self, row):
        """Record a mutation: refresh updated_at and advance version by one."""
        if row is None:
            return row
        if "version" in row:
            row["version"] = int(row["version"]) + 1
            row["updated_at"] = self.stamp()
        return row

    def rows(self, collection):
        return sorted(
            getattr(self, collection).values(), key=lambda r: (r["created_at"], r["_seq"])
        )


db = Store()

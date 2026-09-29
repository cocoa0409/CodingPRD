"""In-memory data store, logical clock and request-scoped mutation bookkeeping.

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
Every row in here is created by an API call.
"""
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.5: the logical clock starts at this instant on every boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "seasons",
    "lifts",
    "staff",
    "areas",
    "readings",
    "pumps",
    "sessions",
    "tasks",
    "patrollers",
    "missions",
    "incidents",
    "day_plans",
    "reservations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    return store.clock


def set_clock(value):
    store.clock = value


def new_id():
    return str(uuid.uuid4())


def hours(n):
    return timedelta(hours=n)


def minutes(n):
    return timedelta(minutes=n)


def new_row(extra=None, versioned=True):
    """Build a row with the system-managed common fields (PRD 2.4)."""
    row = {"id": new_id(), "created_at": now(), "_seq": store.next_seq()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    if extra:
        row.update(extra)
    return row


# ---------------------------------------------------------------- mutations

def _touched():
    bucket = getattr(g, "touched", None)
    if bucket is None:
        bucket = {}
        g.touched = bucket
    return bucket


def mark(row):
    """Record that this request mutated `row` and advance its version once.

    PRD 2.4: version increments by exactly 1 per mutation the server applies to
    the row, so a row touched several times inside one request advances once.
    The bump is applied eagerly so that anything serialised later in the same
    request already observes the new version.
    """
    if row is None:
        return
    bucket = _touched()
    key = id(row)
    if key in bucket:
        return
    bucket[key] = row
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = now()


def commit():
    g.touched = {}


# ---------------------------------------------------------------- ordering

def by_seq(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def ordered(collection):
    """Every list endpoint defaults to created_at ascending (PRD 2.3)."""
    return by_seq(list(collection.values()))


def season_areas(season_id):
    return [a for a in store.areas.values() if a["season_id"] == season_id]


def season_lifts(season_id):
    return [l for l in store.lifts.values() if l["season_id"] == season_id]


def season_pumps(season_id):
    return [p for p in store.pumps.values() if p["season_id"] == season_id]


def season_day_plans(season_id):
    return [d for d in store.day_plans.values() if d["season_id"] == season_id]


def season_patrollers(season_id):
    return [p for p in store.patrollers.values() if p["season_id"] == season_id]


def area_of_session(session):
    return store.areas.get(session["terrain_area_id"])


def season_of_area(area):
    return store.seasons.get(area["season_id"])


def season_of_session(session):
    return season_of_area(area_of_session(session))


def area_sessions(area_id):
    return by_seq([s for s in store.sessions.values() if s["terrain_area_id"] == area_id])


def pump_sessions(pump_id):
    return by_seq([s for s in store.sessions.values() if s["pump_house_id"] == pump_id])


def season_sessions(season_id):
    out = []
    for s in store.sessions.values():
        area = store.areas.get(s["terrain_area_id"])
        if area is not None and area["season_id"] == season_id:
            out.append(s)
    return by_seq(out)


def area_tasks(area_id):
    """Grooming tasks of an area, in sequence_index ascending cascade order."""
    rows = [t for t in store.tasks.values() if t["terrain_area_id"] == area_id]
    return sorted(rows, key=lambda t: (t["sequence_index"], t["created_at"], t["_seq"]))


def season_tasks(season_id):
    out = []
    for t in store.tasks.values():
        area = store.areas.get(t["terrain_area_id"])
        if area is not None and area["season_id"] == season_id:
            out.append(t)
    return sorted(out, key=lambda t: (t["sequence_index"], t["created_at"], t["_seq"]))


def season_missions(season_id):
    out = []
    for m in store.missions.values():
        area = store.areas.get(m["terrain_area_id"])
        if area is not None and area["season_id"] == season_id:
            out.append(m)
    return by_seq(out)


def area_readings(area_id):
    return by_seq([r for r in store.readings.values() if r["terrain_area_id"] == area_id])


def area_patrollers(area_id):
    return by_seq([p for p in store.patrollers.values()
                   if p.get("assigned_terrain_area_id") == area_id])


def lift_assignments(lift_id):
    return by_seq([a for a in store.staff.values() if a["lift_id"] == lift_id])


def plan_reservations(plan_id):
    return by_seq([r for r in store.reservations.values() if r["day_plan_id"] == plan_id])


def lifts_by_code(season_id):
    """PRD 2.9: lift cascades run in lift_code ascending order."""
    return sorted(season_lifts(season_id), key=lambda l: l["lift_code"])


def areas_by_code(season_id):
    """PRD 2.9: terrain cascades run in trail_code ascending order."""
    return sorted(season_areas(season_id), key=lambda a: a["trail_code"])

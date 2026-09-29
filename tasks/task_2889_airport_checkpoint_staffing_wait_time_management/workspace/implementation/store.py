"""In-memory storage and the server logical clock.

Every collection is a plain dict keyed by entity id.  Nothing is ever seeded:
the store starts completely empty on every process boot.
"""

from datetime import date, datetime
from decimal import Decimal

from util import DEFAULT_CLOCK, iso, new_id

COLLECTIONS = (
    "checkpoints",
    "lanes",
    "equipment_units",
    "officers",
    "show_up_curves",
    "flight_schedule_entries",
    "time_bands",
    "staffing_plans",
    "lane_assignments",
    "wait_time_observations",
    "escalation_tickets",
    "screening_referrals",
    "surge_details",
)

_DB = {}
_CLOCK = {}
_SEQ = {"n": 0}


def reset():
    for name in COLLECTIONS:
        _DB[name] = {}
    _CLOCK["now"] = DEFAULT_CLOCK
    _SEQ["n"] = 0


reset()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    return _CLOCK["now"]


def set_now(value):
    _CLOCK["now"] = value


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------
def table(name):
    return _DB[name]


def rows(name):
    return sorted(_DB[name].values(), key=lambda r: r["_seq"])


def get(name, ident):
    if not isinstance(ident, str):
        return None
    return _DB[name].get(ident)


def add(name, row):
    _SEQ["n"] += 1
    row["_seq"] = _SEQ["n"]
    _DB[name][row["id"]] = row
    return row


def base(versioned=True):
    stamp = now()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = now()
    if "version" in row:
        row["version"] += 1


def stamp(row):
    """Update updated_at without advancing version."""
    if "updated_at" in row:
        row["updated_at"] = now()


# --------------------------------------------------------------------------
# JSON projection
# --------------------------------------------------------------------------
def render(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: render(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [render(v) for v in value]
    return value


def project(row, extra=None):
    out = {k: render(v) for k, v in row.items() if not k.startswith("_")}
    if extra:
        for k, v in extra.items():
            out[k] = render(v)
    return out

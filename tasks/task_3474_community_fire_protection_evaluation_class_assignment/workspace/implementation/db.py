"""In-memory data store and the logical clock (PRD §2.4, §2.5).

The store starts empty on every boot; nothing is seeded. All temporal
reasoning uses the logical clock, which defaults to 2026-09-01T00:00:00Z
and is advanced only via POST /_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

STORE = {
    "communities": {},
    "cycles": {},
    "departments": {},
    "apparatus": {},
    "systems": {},
    "hydrants": {},
    "flow_tests": {},
    "credits": {},
    "sheets": {},
    "classifications": {},
    "properties": {},
    "quotes": {},
    "requests": {},
    "appeals": {},
}

_SEQ = {"n": 0}

CLOCK = {
    "dt": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": "2026-09-01T00:00:00Z",
}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.5)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_dt():
    return CLOCK["dt"]


def clock_date():
    return CLOCK["dt"].date()


def clock_iso():
    return fmt_ts(CLOCK["dt"])


def set_clock(dt, raw):
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw


def new_entity(store, fields):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    ts = clock_iso()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    STORE[store][e["id"]] = e
    return e


def touch(e):
    """PRD §2.5: every mutation refreshes updated_at and increments version."""
    e["updated_at"] = clock_iso()
    e["version"] += 1


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def find(store, entity_id):
    return STORE[store].get(entity_id)


def all_of(store):
    """Creation order (ascending created_at / insertion sequence)."""
    return sorted(STORE[store].values(), key=lambda e: e["_seq"])


# --- domain lookups -------------------------------------------------------

def dept_of_community(community_id):
    for d in all_of("departments"):
        if d["community_id"] == community_id:
            return d
    return None


def system_of_community(community_id):
    for s in all_of("systems"):
        if s["community_id"] == community_id:
            return s
    return None


def active_cycle_of_community(community_id):
    """The community's non-terminal cycle (not EFFECTIVE, not WITHDRAWN)."""
    for c in all_of("cycles"):
        if c["community_id"] == community_id and c["status"] not in ("EFFECTIVE", "WITHDRAWN"):
            return c
    return None


def effective_classification_of_community(community_id):
    for cl in all_of("classifications"):
        if cl["community_id"] == community_id and cl["status"] == "EFFECTIVE":
            return cl
    return None


def next_cycle_number(community_id):
    n = 0
    for c in all_of("cycles"):
        if c["community_id"] == community_id:
            n += 1
    return n + 1

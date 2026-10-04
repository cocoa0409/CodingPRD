"""In-memory data store and the server-side logical clock.

Storage is plain dicts keyed by id; the store starts empty on every boot and
nothing is seeded. The logical clock defaults to 2026-09-01T00:00:00Z and is
only moved by POST /_clock/set_current_utc (PRD 2.4). All entity timestamps
(created_at/updated_at) and every date/datetime comparison read this clock,
never the wall clock.
"""

import itertools
import uuid

import constants
import util

STORE = {
    "museums": {},
    "timed_entry_passes": {},
    "members": {},
    "exhibitions": {},
    "tickets": {},
    "education_programs": {},
    "docents": {},
    "docent_assignments": {},
    "school_reservations": {},
    "collection_objects": {},
    "loan_agreements": {},
    "condition_reports": {},
    "collection_reviews": {},
    "funds": {},
    "expenditures": {},
    "research_requests": {},
}

# Monotonic insertion counter: used only to break created_at ties (the logical
# clock can be frozen, giving several entities identical created_at values).
# PRD forbids id-based tie-breaks for the waitlist; insertion order is not the
# resource id and keeps ordering deterministic under a frozen clock.
_seq_counter = itertools.count(1)

_clock_raw = constants.CLOCK_DEFAULT_RAW
_clock_dt = util.parse_datetime(constants.CLOCK_DEFAULT_RAW)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def set_clock(raw, parsed):
    global _clock_raw, _clock_dt
    _clock_raw = raw
    _clock_dt = parsed


def clock_raw():
    return _clock_raw


def now_dt():
    return _clock_dt


def now_iso():
    return util.format_dt(_clock_dt)


def today():
    return _clock_dt.date()


def today_str():
    return _clock_dt.date().isoformat()


def current_slot_index():
    """Whole number of complete 15-minute intervals elapsed since 10:00 UTC."""
    minutes = _clock_dt.hour * 60 + _clock_dt.minute
    return (minutes - constants.ENTRY_DAY_START_MINUTE) // constants.SLOT_MINUTES


def new_entity(fields):
    """Build an entity dict with the four common fields plus an internal seq."""
    e = dict(fields)
    e["id"] = new_id()
    ts = now_iso()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def touch(entity):
    """Record a mutation: bump updated_at and version (PRD 2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def all_sorted(collection):
    """All rows of a collection in list order: created_at ASC (PRD 2.3),
    with the insertion sequence as tie-break under a frozen clock."""
    return sorted(
        STORE[collection].values(), key=lambda e: (e["created_at"], e["_seq"])
    )

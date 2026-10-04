"""In-memory data store, logical clock, identity, and timestamp rendering.

Storage is Python dicts keyed by id only. No SQLite, no disk, no seeding:
every entity is created through the API. The logical clock starts at exactly
2026-09-01T00:00:00Z and moves only via POST /_clock/set_current_utc; the
wall clock is never consulted.
"""
import uuid
from datetime import datetime, timedelta, timezone

# --- entity tables (all flat, keyed by server-minted dashed UUID) -----------
DB = {
    "band_plans": {},
    "areas": {},
    "blocks": {},
    "auctions": {},
    "applicants": {},
    "rounds": {},
    "bids": {},
    "assignment_bids": {},
    "licenses": {},
    "milestones": {},
    "transfers": {},
    "incumbents": {},
    "renewals": {},
}

# --- logical clock -----------------------------------------------------------
CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}

# --- monotonic creation sequence (tie-breaks equal created_at instants) ------
SEQ = {"n": 0}


def now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def new_id():
    # Standard dashed UUID string; never uuid4().hex (undashed hex fails
    # downstream is_valid_uuid checks).
    return str(uuid.uuid4())


def stamp_new(entity):
    """Populate the four system-managed common fields on a new entity."""
    ts = now()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Record a mutation: version +1 and updated_at re-stamped. Caller
    dedupes per request via helpers.touch() wrapper."""
    entity["version"] += 1
    entity["updated_at"] = now()


# --- ISO 8601 helpers --------------------------------------------------------

def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_house(dt):
    """Housekeeping family: created_at / updated_at / api_request_timestamp.
    Always exactly three fractional digits (millisecond precision)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def render_domain(dt):
    """Domain family: application_deadline, grant_date, term_end,
    payment_deadline, due_date, lease windows, transition windows.
    Renders exactly as the logical clock reads — no added fractional-digit
    normalization (whole seconds when the instant has no fraction)."""
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        frac = "%06d" % dt.microsecond
        frac = frac.rstrip("0")
        return base + "." + frac + "Z"
    return base + "Z"


def add_days(dt, days):
    """Calendar-naive day arithmetic: a day is a 24-hour multiple."""
    return dt + timedelta(days=days)


def created_key(entity):
    """List ordering: created_at ASC, ties broken by creation sequence
    (never by id)."""
    return (entity["created_at"], entity["_seq"])

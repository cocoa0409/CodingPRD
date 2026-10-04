"""In-memory data store.

Nothing is persisted, nothing is seeded. Every collection starts empty on boot
(the per-test-server isolation re-launches start.sh before each test) and every
entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_LOGICAL_CLOCK

# ---------------------------------------------------------------------------
# Collections (all keyed by id)
# ---------------------------------------------------------------------------
programs = {}
carry_quota_ledgers = {}
patients = {}
dose_orders = {}
dose_dispenses = {}
take_home_privileges = {}
take_home_exceptions = {}
take_home_carry_ledgers = {}
inventory_lots = {}
inventory_transactions = {}
counseling_sessions = {}
treatment_plan_reviews = {}
guest_dosing_arrangements = {}
compliance_inspections = {}
compliance_findings = {}
corrective_actions = {}
diversion_cases = {}
users = {}
time_in_treatment_trackers = {}

# ---------------------------------------------------------------------------
# Logical clock. Startup default is exactly 2026-09-01T00:00:00Z and never the
# host wall clock; POST /otp/_clock/set_current_utc is the only way to move it.
# ---------------------------------------------------------------------------
_SEQ = itertools.count(1)


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (YYYY-MM-DD). Returns an aware UTC datetime of midnight."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


_clock = parse_iso(DEFAULT_LOGICAL_CLOCK)


def clock_dt():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        dt.astimezone(timezone.utc).microsecond // 1000
    )


def now_iso():
    """A strictly increasing timestamp derived from the logical clock."""
    return fmt_dt(_clock + timedelta(microseconds=next(_SEQ)))


def stamp(obj):
    """Refresh updated_at and bump version — any mutation is a real mutation."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def touch_no_version(obj):
    obj["updated_at"] = now_iso()
    return obj


def new_id():
    """A server-minted identifier formatted as a UUID (no type prefix)."""
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def new_token():
    return "gtk_" + uuid.uuid4().hex


def clear_all():
    for collection in (
        programs,
        carry_quota_ledgers,
        patients,
        dose_orders,
        dose_dispenses,
        take_home_privileges,
        take_home_exceptions,
        take_home_carry_ledgers,
        inventory_lots,
        inventory_transactions,
        counseling_sessions,
        treatment_plan_reviews,
        guest_dosing_arrangements,
        compliance_inspections,
        compliance_findings,
        corrective_actions,
        diversion_cases,
        users,
        time_in_treatment_trackers,
    ):
        collection.clear()
    set_clock(parse_iso(DEFAULT_LOGICAL_CLOCK))
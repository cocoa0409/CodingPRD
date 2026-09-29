"""In-memory store, the logical clock, and temporal helpers (PRD 2.4, 2.5).

Storage is process-memory only: plain dicts keyed by id. A restart wipes every
byte of state. Nothing is seeded, preloaded or hardcoded at import time.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone, date

UTC = timezone.utc

# --- the logical clock (PRD 2.5) ---------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_clock = {"now": DEFAULT_CLOCK}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def today():
    return now().date()


# --- collections -------------------------------------------------------------
COLLECTIONS = (
    "payer_policies",
    "patients",
    "allergy_test_orders",
    "reaction_events",
    "immunotherapy_vials",
    "immunotherapy_doses",
    "sinuplasty_cases",
    "diagnostic_studies",
    "device_dispenses",
    "endoscope_assets",
    "supply_lots",
    "surgery_center_blocks",
    "procedure_bookings",
)

NOT_FOUND = {
    "payer_policies": "ERR_PAYER_POLICY_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "allergy_test_orders": "ERR_ALLERGY_TEST_ORDER_NOT_FOUND",
    "reaction_events": "ERR_REACTION_EVENT_NOT_FOUND",
    "immunotherapy_vials": "ERR_IMMUNOTHERAPY_VIAL_NOT_FOUND",
    "immunotherapy_doses": "ERR_IMMUNOTHERAPY_DOSE_NOT_FOUND",
    "sinuplasty_cases": "ERR_SINUPLASTY_CASE_NOT_FOUND",
    "diagnostic_studies": "ERR_DIAGNOSTIC_STUDY_NOT_FOUND",
    "device_dispenses": "ERR_DEVICE_DISPENSE_NOT_FOUND",
    "endoscope_assets": "ERR_ENDOSCOPE_ASSET_NOT_FOUND",
    "supply_lots": "ERR_SUPPLY_LOT_NOT_FOUND",
    "surgery_center_blocks": "ERR_SURGERY_CENTER_BLOCK_NOT_FOUND",
    "procedure_bookings": "ERR_PROCEDURE_BOOKING_NOT_FOUND",
}

db = {name: {} for name in COLLECTIONS}
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def rows(name):
    return list(db[name].values())


# --- instant / date formatting and parsing -----------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(?:[Zz]|\+00:?00|-00:?00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or "0"
    micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None


def parse_date(value):
    """Parse a bare calendar date. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# --- temporal arithmetic conventions (PRD 2.5) -------------------------------
def whole_days_between(earlier, later):
    """Whole days elapsed, partial days discarded."""
    return int((later - earlier).total_seconds() // 86400)


def whole_minutes_between(earlier, later):
    """Whole minutes elapsed, remainder discarded."""
    return int((later - earlier).total_seconds() // 60)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)

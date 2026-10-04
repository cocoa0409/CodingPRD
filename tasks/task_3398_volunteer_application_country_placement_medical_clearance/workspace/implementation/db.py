"""In-memory data store, logical clock, pinned constants, and record helpers.

Storage is plain dicts keyed by id. The store starts empty on every boot and
nothing is seeded. The system never consults the wall clock for domain
timestamps: created_at/updated_at/issued_at/service dates all read the logical
clock, whose startup default is exactly 2026-09-01T00:00:00Z.
"""
import threading
import uuid
from datetime import datetime, timezone

# --- Pinned constants (SCAFFOLD.yaml calculations / PRD.md) ---
DEFAULT_CLOCK_START = "2026-09-01T00:00:00Z"
INVITATION_ACCEPTANCE_WINDOW_DAYS = 10
SERVICE_TERM_DAYS = 810
READJUSTMENT_MONTHLY_RATE_CENTS = 47500
DAYS_PER_MONTH = 30
HALF_MONTH_DAYS = 15
ET_SHORT_SERVICE_THRESHOLD_MONTHS = 18
NCE_MIN_MONTHS_SERVED = 12
NCE_DURATION_MONTHS = 12
MAX_MEDICAL_DEFERRALS = 2
MIN_DIMENSION_FLOOR = 2.0
STRONGLY_RECOMMEND_MIN = 4.0
RECOMMEND_MIN = 3.0
NEUTRAL_MIN = 2.5
TECHNICAL_MIN_SCORE = 2.5
CULTURAL_MIN_SCORE = 2.5

SKILL_CATALOG = [
    "TEACHING_ENGLISH", "MATH_SCIENCE", "PRIMARY_HEALTH", "NURSING", "AGRONOMY",
    "FORESTRY", "SMALL_BUSINESS", "IT", "WATER_SANITATION", "YOUTH_DEVELOPMENT",
]
SECTORS = [
    "EDUCATION", "HEALTH", "AGRICULTURE", "ENVIRONMENT", "YOUTH",
    "COMMUNITY_DEVELOPMENT",
]
ROLES = [
    "SystemAdmin", "Applicant", "PlacementOfficer", "MedicalOfficer",
    "LegalReviewer", "TrainingDirector", "CountryDirector",
]

STORE = {
    "applicants": {},
    "country_programs": {},
    "assignment_openings": {},
    "applications": {},
    "interviews": {},
    "invitations": {},
    "medical_clearances": {},
    "legal_clearances": {},
    "training_cohorts": {},
    "training_enrollments": {},
    "volunteer_services": {},
    "site_placements": {},
    "service_events": {},
    "completion_records": {},
}

# Single global lock: every request mutates/reads under it (app.py hooks).
LOCK = threading.RLock()


def parse_dt(value):
    """Parse an ISO8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO8601 UTC with exactly 3 fractional digits."""
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (u.microsecond // 1000)


def ts_sec(dt):
    """Truncate to whole seconds: timestamps compare at second precision."""
    return dt.replace(microsecond=0)


_clock = {"current": parse_dt(DEFAULT_CLOCK_START)}


def logical_now():
    return _clock["current"]


def set_logical_clock(to):
    _clock["current"] = to


def now_iso():
    return fmt_ts(logical_now())


def new_id():
    return str(uuid.uuid4())


def new_record():
    """Common fields for every persisted resource except ServiceEvent."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(record):
    """Refresh updated_at and bump version (every mutation, incl. cascades)."""
    record["updated_at"] = now_iso()
    record["version"] += 1

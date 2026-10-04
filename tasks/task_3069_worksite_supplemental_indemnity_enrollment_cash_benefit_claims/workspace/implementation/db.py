"""In-memory data store. Empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

# entity name -> {id: record dict}
STORES = {
    "employer_groups": {},
    "benefit_counselors": {},
    "enrollment_campaigns": {},
    "policy_series": {},
    "benefit_schedules": {},
    "employees": {},
    "policies": {},
    "claims": {},
    "claim_documents": {},
    "wellness_benefits": {},
    "payroll_cycles": {},
    "deduction_lines": {},
}

# deterministic certificate sequence counters per series id
CERT_SEQ = {}


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Logical-clock-driven creation timestamp, formatted with ms precision."""
    from clock import now as clock_now
    return format_ts(clock_now())


def format_ts(dt):
    """Format a datetime as ISO8601 UTC with 3 fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def stamp_created(rec):
    now = iso_now()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = iso_now()
    rec["version"] = rec.get("version", 1) + 1
    return rec

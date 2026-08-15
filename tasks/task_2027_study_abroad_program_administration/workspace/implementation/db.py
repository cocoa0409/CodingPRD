"""In-memory data store. Store starts empty on every boot -- no seeding."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --- logical clock (never wall-clock for temporal rules) ---
_logical_clock = "2026-08-01T00:00:00Z"


def get_clock():
    return _logical_clock


def set_clock(iso_str):
    global _logical_clock
    _logical_clock = iso_str
    return _logical_clock


# --- entity stores ---
partner_agreements = {}
programs = {}
students = {}
applications = {}
course_preapprovals = {}
travel_advisories = {}
insurance_enrollments = {}
billing_statements = {}
incidents = {}
credit_postings = {}

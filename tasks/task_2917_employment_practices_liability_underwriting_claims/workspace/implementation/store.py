"""In-memory storage, identity, the logical clock and small lookup helpers.

Storage is process-local and starts completely empty: no seeding, no
persistence, no files. Every fresh boot is a blank system.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# --- tables ---------------------------------------------------------------
JURISDICTIONS = {}
RATE_PLANS = {}
APPLICANTS = {}
SERVICES = {}
ASSESSMENTS = {}
POLICIES = {}
CLAIMS = {}
GROUPS = {}
FIRMS = {}
ASSIGNMENTS = {}
INVOICES = {}
PAYMENTS = {}
RESOLUTIONS = {}

# --- logical clock --------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(value):
    _clock["now"] = value


# --- identity / timestamps ------------------------------------------------
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def fmt_instant(dt):
    """Canonical ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    micro = dt.microsecond
    millis = micro // 1000
    if micro % 1000 >= 500:
        millis += 1
        if millis > 999:
            dt = dt + timedelta(seconds=1)
            millis = 0
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis)


def wall_now():
    return datetime.now(timezone.utc)


def new_row(extra=None):
    stamp = fmt_instant(wall_now())
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = fmt_instant(wall_now())
    row["version"] = row["version"] + 1
    return row


# --- lookups --------------------------------------------------------------
def find(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def jurisdiction_by_code(code):
    for row in JURISDICTIONS.values():
        if row["code"] == code:
            return row
    return None


def rows(table):
    return list(table.values())


def claims_of_policy(policy_id):
    return [c for c in CLAIMS.values() if c["policy_id"] == policy_id]


def services_of_applicant(applicant_id):
    return [s for s in SERVICES.values() if s["applicant_id"] == applicant_id]


def assessments_of_applicant(applicant_id):
    return [a for a in ASSESSMENTS.values() if a["applicant_id"] == applicant_id]


def assignments_of_claim(claim_id):
    return [a for a in ASSIGNMENTS.values() if a["claim_id"] == claim_id]


def invoices_of_assignment(assignment_id):
    return [i for i in INVOICES.values()
            if i["defense_assignment_id"] == assignment_id]


def payments_of_claim(claim_id):
    return [p for p in PAYMENTS.values() if p["claim_id"] == claim_id]


def resolutions_of_claim(claim_id):
    return [r for r in RESOLUTIONS.values() if r["claim_id"] == claim_id]


def members_of_group(group_id):
    return [c for c in CLAIMS.values()
            if c.get("related_claim_group_id") == group_id]


def policy_of_claim(claim):
    return POLICIES.get(claim["policy_id"])


def applicant_of_policy(policy):
    return APPLICANTS.get(policy["applicant_id"])


def sort_key_created(row):
    return (row["created_at"], row["_seq"])

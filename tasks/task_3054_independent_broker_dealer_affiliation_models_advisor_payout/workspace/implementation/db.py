"""In-memory store, identifier minting and the logical clock.

Storage is process-local and in-memory only: plain dicts keyed by id.  Nothing
is written to disk, nothing is seeded at import time, and every dict below is
empty on a fresh boot, so re-running start.sh wipes every byte of state.

Table names mirror the scaffold entity names:

    branches, advisors, branch_supervisor_enrollments, advisor_branch_links,
    accounts, revenue_entries, payout_periods, advisor_payout_lines,
    payout_loans, loan_amortization_entries, expense_pass_throughs,
    advisory_revenue_splits, transition_records, account_retentions
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Tables.  All empty at boot; tests build every entity through the API.
# ---------------------------------------------------------------------------

branches = {}
advisors = {}
branch_supervisor_enrollments = {}
advisor_branch_links = {}
accounts = {}
revenue_entries = {}
payout_periods = {}
advisor_payout_lines = {}
payout_loans = {}
loan_amortization_entries = {}
expense_pass_throughs = {}
advisory_revenue_splits = {}
transition_records = {}
account_retentions = {}

TABLES = (branches, advisors, branch_supervisor_enrollments, advisor_branch_links,
          accounts, revenue_entries, payout_periods, advisor_payout_lines,
          payout_loans, loan_amortization_entries, expense_pass_throughs,
          advisory_revenue_splits, transition_records, account_retentions)


# ---------------------------------------------------------------------------
# Identifier minting and timestamps.
# ---------------------------------------------------------------------------

_seq = [0]
_created_seq = 0


def new_id():
    """A UUID with no type prefix or kind marker embedded in it (PRD 2.6)."""
    return str(uuid.uuid4())


def next_created_seq():
    """Monotonic creation ordinal used only for the created_at tie-break."""
    global _created_seq
    _created_seq += 1
    return _created_seq


def iso_now():
    """ISO 8601 UTC with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# The logical clock (PRD 2.11).  Until it is set it reads the fixed startup
# default 2026-09-01T00:00:00Z and never falls back to host wall-clock time.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
_clock = {"value": DEFAULT_CLOCK, "set": False}


def set_clock(value):
    _clock["value"] = value
    _clock["set"] = True


def clock_value():
    return _clock["value"]


def clock_is_set():
    return _clock["set"]


def clock_dt():
    """The logical clock as an aware datetime.  Tolerates the Z suffix."""
    raw = _clock["value"]
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(DEFAULT_CLOCK.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_date(value):
    """Parse an ISO date (optionally with a time component) into a datetime."""
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(text + "T00:00:00")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def clear_all():
    """Drop every row.  Only used by tests through no endpoint; kept harmless."""
    for table in TABLES:
        table.clear()
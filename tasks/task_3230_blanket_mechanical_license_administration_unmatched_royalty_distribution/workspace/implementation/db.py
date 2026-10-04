"""In-memory data store. Empty on every boot — no seeding."""

# Resource dicts keyed by id
service_providers = {}
members = {}
payees = {}
works = {}
work_shares = {}
rate_schedules = {}
usage_reports = {}
usage_lines = {}
accruals = {}
match_runs = {}
claims = {}
disputes = {}
statements = {}
statement_lines = {}
audits = {}
cycle_runs = {}
distribution_lines = {}

# Queued postings: list of dicts
# { "member_id", "period_month" (statement period key), "usage_line_id",
#   "allocated_cents", "line_type" }
postings = []

# Clock: logical time, default 2026-09-01T00:00:00Z
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
logical_now = DEFAULT_CLOCK


def now():
    return logical_now


def set_now(dt):
    global logical_now
    logical_now = dt


def reset_all():
    """Not used at startup; defensive only."""
    for d in (service_providers, members, payees, works, work_shares,
              rate_schedules, usage_reports, usage_lines, accruals,
              match_runs, claims, disputes, statements, statement_lines,
              audits, cycle_runs, distribution_lines):
        d.clear()
    postings.clear()
    set_now(DEFAULT_CLOCK)

"""In-memory store and the logical clock.

No persistence of any kind: every process starts with empty collections and the
logical clock pinned at 2026-09-01T00:00:00Z.  Nothing here is ever seeded.
"""

import copy
from datetime import datetime, timedelta, timezone

CLOCK_START = "2026-09-01T00:00:00Z"
DAY_SECONDS = 86400


def parse_iso(value):
    """Parse an ISO-8601 instant (with or without fractional seconds) to UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an instant as an ISO 8601 UTC timestamp.

    Whole-second instants (the logical clock and the day-boundary markers
    derived from it) are rendered without a fractional part; sub-second
    instants keep exactly three fractional digits.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def logical_day(clock):
    """00:00:00Z of the clock's calendar date."""
    return clock.replace(hour=0, minute=0, second=0, microsecond=0)


class Store:
    def __init__(self):
        self.clock = parse_iso(CLOCK_START)
        self.seq = 0
        self.employers = {}
        self.job_seekers = {}
        self.campaigns = {}
        self.sponsored_jobs = {}
        self.job_postings = {}
        self.job_posting_versions = {}
        self.assessments = {}
        self.applications = {}
        self.apply_events = {}
        self.job_alert_subscriptions = {}
        self.sponsor_events = {}
        self.budget_ledger = {}
        self.pacing_holds = {}
        self.ledger_seq = {"CMT": 0, "RFD": 0, "REV": 0, "HLD": 0}


store = Store()


def snapshot():
    """Deep copy of the mutable collections + clock, for request-level rollback."""
    return {
        "clock": store.clock,
        "employers": copy.deepcopy(store.employers),
        "job_seekers": copy.deepcopy(store.job_seekers),
        "campaigns": copy.deepcopy(store.campaigns),
        "sponsored_jobs": copy.deepcopy(store.sponsored_jobs),
        "job_postings": copy.deepcopy(store.job_postings),
        "job_posting_versions": copy.deepcopy(store.job_posting_versions),
        "assessments": copy.deepcopy(store.assessments),
        "applications": copy.deepcopy(store.applications),
        "apply_events": copy.deepcopy(store.apply_events),
        "job_alert_subscriptions": copy.deepcopy(store.job_alert_subscriptions),
        "sponsor_events": copy.deepcopy(store.sponsor_events),
        "budget_ledger": copy.deepcopy(store.budget_ledger),
        "pacing_holds": copy.deepcopy(store.pacing_holds),
        "ledger_seq": copy.deepcopy(store.ledger_seq),
    }


def restore(state):
    for key, value in state.items():
        setattr(store, key, value)


def reset():
    """Drop every row and rewind the clock — used only by the per-boot self check."""
    store.__init__()
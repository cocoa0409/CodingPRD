"""In-memory data store and logical clock.

The store starts EMPTY on every boot — no seeding, preloading, or hardcoded
entities. Every entity is constructed through the declared API surface.
The logical clock starts pinned at 2026-09-01T00:00:00Z and is monotonic.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_START_ISO = "2026-09-01T00:00:00Z"

organizations = {}
rule_proposals = {}
comment_letters = {}
disclosure_submissions = {}
professionals = {}
exam_attempts = {}
trade_reports = {}
data_subscriptions = {}
enforcement_referrals = {}
solicitation_records = {}

_clock = {
    "now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
}


def now():
    """Current logical time (never the wall clock)."""
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())

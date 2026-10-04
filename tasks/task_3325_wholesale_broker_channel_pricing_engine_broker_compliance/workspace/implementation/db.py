"""In-memory data store, logical clock and id/timestamp minting.

The store is created empty on every process boot. Nothing here seeds,
preloads or hardcodes an entity: every row is produced by a client call
against a declared endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT_ISO

# ---------------------------------------------------------------------------
# Collections - module level, instantiated empty.
# ---------------------------------------------------------------------------
brokers = {}
licenses = {}
financial_reviews = {}
product_eligibilities = {}
exclusivity_policies = {}
rate_sheets = {}
pricing_quotes = {}
loan_submissions = {}
underwriting_decisions = {}
turn_time_escalations = {}
compensation_plans = {}
quality_control_reviews = {}


# ---------------------------------------------------------------------------
# Instant helpers - ISO 8601 UTC, three fractional digits, trailing Z.
# ---------------------------------------------------------------------------
def parse_instant(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_instant(moment):
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    millis = moment.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second, millis,
    )


def now_iso():
    return format_instant(clock.now)


class Clock(object):
    def __init__(self):
        self.now = parse_instant(CLOCK_DEFAULT_ISO)

    def set(self, instant):
        self.now = instant

    def advance_days(self, days):
        return self.now + timedelta(days=days)

    def iso(self):
        return format_instant(self.now)


clock = Clock()


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------
def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24].upper()


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def base_row():
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def touch(row):
    """Standard mutation bookkeeping: refresh updated_at, bump version."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def touch_broker(broker):
    return touch(broker)


def reset_all():
    """Wipe every byte of state. Called only by explicit administrative use."""
    for collection in (
        brokers, licenses, financial_reviews, product_eligibilities,
        exclusivity_policies, rate_sheets, pricing_quotes, loan_submissions,
        underwriting_decisions, turn_time_escalations, compensation_plans,
        quality_control_reviews,
    ):
        collection.clear()
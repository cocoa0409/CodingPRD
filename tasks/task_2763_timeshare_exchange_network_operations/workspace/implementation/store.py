"""In-memory data store, logical clock and row bookkeeping.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Every row the API reports is created by a caller
through a declared endpoint.
"""

import uuid
from datetime import datetime, date, timedelta

DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# operational constants
# ---------------------------------------------------------------------------
STAY_NIGHTS = 7
TURNOVER_BUFFER_NIGHTS = 1
OCCUPANCY_NIGHTS_PER_DEPOSIT = 8
DEPOSIT_LIFETIME_DAYS = 730
EXTENSION_DAYS_PER_MONTH = 30
MAX_EXTENSION_MONTHS = 12
DEPOSIT_LEAD_MIN_DAYS = 60
REQUEST_WINDOW_MAX_SPAN_DAYS = 60
MATCH_HOLD_HOURS = 48
REINSTATEMENT_WINDOW_DAYS = 14
GETAWAY_SWEEP_WITHIN_DAYS = 45
MAX_DISPUTE_ROUNDS = 2
AFFILIATION_YEAR_DAYS = 365
COMPLAINT_STRIKE_THRESHOLD = 2
LATE_CANCEL_SURCHARGE_CENTS = 7500

COUNTED_DEPOSIT_STATUSES = ("BANKED", "RESERVED", "USED")
ACTIVE_REQUEST_STATUSES = ("SUBMITTED", "WAITLISTED", "MATCHED")

# ---------------------------------------------------------------------------
# enum vocabularies
# ---------------------------------------------------------------------------
TIER_CODES = ["BASIC", "PLUS", "ELITE"]
QUALITY_RATINGS = ["GOLD_CROWN", "SILVER_CROWN", "STANDARD", "HOSPITALITY"]
BAND_CODES = ["PLATINUM", "GOLD", "SILVER", "BRONZE"]
UNIT_SIZES = ["STUDIO", "ONE_BR", "TWO_BR", "THREE_BR"]
AFFILIATION_STATUSES = ["PENDING_AFFILIATION", "ACTIVE", "PROBATION", "SUSPENDED", "TERMINATED"]
ENROLLMENT_STATUSES = ["PENDING_PAYMENT", "ACTIVE", "LAPSED", "SUSPENDED", "CANCELLED"]
DEPOSIT_STATUSES = ["BANKED", "RESERVED", "USED", "EXPIRED", "WITHDRAWN"]
RENTAL_STATUSES = ["NOT_LISTED", "LISTED_GETAWAY", "RENTED"]
REQUEST_STATUSES = ["SUBMITTED", "WAITLISTED", "MATCHED", "CONFIRMED", "CANCELLED", "EXPIRED", "DENIED"]
FUNDING_MODES = ["DEPOSIT_FIRST", "REQUEST_FIRST"]
CONFIRMATION_STATUSES = ["CONFIRMED", "COMPLETED", "CANCELLED", "REINSTATED"]
RUN_STATUSES = ["PENDING", "COMPLETED"]
OFFER_STATUSES = ["LISTED", "BOOKED", "WITHDRAWN", "EXPIRED"]
DISPUTE_STATUSES = ["OPEN", "UNDER_REVIEW", "INFO_REQUESTED", "RESOLVED_UPHELD", "RESOLVED_DENIED", "WITHDRAWN"]
SUBJECT_TYPES = ["TRADING_POWER", "RESORT_QUALITY"]
ENTRY_TYPES = [
    "DEPOSIT_CREDIT", "DEPOSIT_WITHDRAWAL_REVERSAL", "DEPOSIT_EXPIRY_FORFEIT",
    "SETTLEMENT_ADJUSTMENT", "EXCHANGE_DEBIT", "EXCHANGE_RESTORATION",
    "RESTORATION_HAIRCUT", "GETAWAY_LISTING_FORFEIT", "DISPUTE_POWER_GRANT",
    "DUES_PAYMENT", "EXCHANGE_CHARGE", "EXCHANGE_CHARGE_REFUND",
    "CANCELLATION_FEE", "REINSTATEMENT_FEE", "EXTENSION_FEE",
    "GETAWAY_BOOKING_PAYMENT",
]
RELATED_ENTITY_TYPES = ["DEPOSIT", "EXCHANGE_REQUEST", "CONFIRMATION", "GETAWAY_OFFER", "DISPUTE", "MEMBER"]
ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO-8601 UTC instant.  Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    if parsed.utcoffset().total_seconds() != 0:
        return None
    return parsed.replace(tzinfo=None)


def format_instant(moment):
    if moment is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def parse_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    if value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def format_date(day):
    if day is None:
        return None
    return "%04d-%02d-%02d" % (day.year, day.month, day.day)


# ---------------------------------------------------------------------------
# the store itself
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.membership_tiers = {}
        self.resorts = {}
        self.season_bands = {}
        self.members = {}
        self.deposits = {}
        self.exchange_requests = {}
        self.confirmations = {}
        self.matching_runs = {}
        self.getaway_offers = {}
        self.disputes = {}
        self.resort_quality_reviews = {}
        self.ledger_entries = {}
        self.clock = parse_instant(DEFAULT_LOGICAL_CLOCK)
        self._seq = 0

    # -- clock --------------------------------------------------------------
    def now(self):
        return self.clock

    def today(self):
        return self.clock.date()

    def now_iso(self):
        return format_instant(self.clock)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, extra=None):
        moment = self.now_iso()
        row = {
            "id": str(uuid.uuid4()),
            "created_at": moment,
            "updated_at": moment,
            "version": 1,
            "_seq": self.next_seq(),
        }
        if extra:
            row.update(extra)
        return row

    # -- ordered access ----------------------------------------------------
    def ordered(self, table):
        return sorted(table.values(), key=lambda row: (row["created_at"], row["_seq"]))


db = Store()


def serialize(row, drop=()):
    out = {}
    for key, value in row.items():
        if key.startswith("_") or key in drop:
            continue
        out[key] = value
    return out


def touch(row):
    """Mark a row mutated: refresh updated_at and advance version once per request."""
    try:
        from flask import g, has_request_context
        if has_request_context():
            touched = getattr(g, "_touched", None)
            if touched is None:
                touched = set()
                g._touched = touched
            if row["id"] in touched:
                row["updated_at"] = db.now_iso()
                return row
            touched.add(row["id"])
    except Exception:
        pass
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now_iso()
    return row


def add_days(day, count):
    return day + timedelta(days=count)


def whole_days(later, earlier):
    return (later - earlier).days

"""Calculation constants and the pure pricing / grading calculations."""
from decimal import Decimal, ROUND_HALF_UP

UNIT_SECONDS = 30

DAYPART_MULTIPLIER = {
    "MORNING": Decimal("0.60"),
    "DAYTIME": Decimal("0.45"),
    "EARLY_NEWS": Decimal("1.00"),
    "PRIME": Decimal("2.25"),
    "LATE_NIGHT": Decimal("0.35"),
}

DAYPARTS = ["MORNING", "DAYTIME", "EARLY_NEWS", "PRIME", "LATE_NIGHT"]

VOLUME_DISCOUNT_TIERS = [
    (1, 4, Decimal("0.00")),
    (5, 9, Decimal("0.05")),
    (10, 19, Decimal("0.125")),
    (20, None, Decimal("0.20")),
]

AGENCY_COMMISSION_TIERS = [
    (0, 49999, Decimal("0.00")),
    (50000, 249999, Decimal("0.02")),
    (250000, None, Decimal("0.035")),
]

LUC_WINDOW_DAYS = {"PRIMARY": 45, "GENERAL": 60, "RUNOFF": 45, "SPECIAL": 45}
ELECTION_TYPES = ["PRIMARY", "GENERAL", "RUNOFF", "SPECIAL"]

INCLUDED_SPOT_STATUSES = {
    "PROVISIONAL": ["SCHEDULED", "AIRED"],
    "FINAL": ["AIRED"],
}
INCLUDED_ORDER_STATUSES = {
    "PROVISIONAL": ["ACCEPTED", "SUSPENDED", "RUNNING", "COMPLETED"],
    "FINAL": ["RUNNING", "COMPLETED"],
}

POSTURE_RESTRICTED_THRESHOLD = 1
POSTURE_FROZEN_THRESHOLD = 2

DISCLOSURE_MIN_SECONDS = 4
DISCLOSURE_PREFIX = "PAID FOR BY "
AUTHORIZED_BY = "AUTHORIZED BY"

CANDIDATE_SEPARATION_BUFFER_SECONDS = 900
EO_REQUEST_WINDOW_DAYS = 7
EO_RESPONSE_DEADLINE_HOURS = 24
COMPLAINT_RESPONSE_DEADLINE_HOURS = 240
CURE_PERIOD_HOURS = 720
NET_TERM_DAYS = 30
MAX_REVIEW_ROUNDS = 3

PAYMENT_TERMS = ["PREPAY", "NET_30"]
EO_PARITY_BASES = ["SPOT_COUNT", "DOLLAR_VALUE"]
REQUESTED_CLASSES = ["CANDIDATE", "ISSUE"]
DURATIONS = [30, 60]


def round_half_up(value):
    """Round a Decimal (or int) half up to a whole integer of cents/units."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def volume_discount_pct(spot_count):
    for lo, hi, pct in VOLUME_DISCOUNT_TIERS:
        if spot_count >= lo and (hi is None or spot_count <= hi):
            return pct
    return Decimal("0.00")


def agency_commission_pct(gross_cents):
    for lo, hi, pct in AGENCY_COMMISSION_TIERS:
        if gross_cents >= lo and (hi is None or gross_cents <= hi):
            return pct
    return Decimal("0.00")


def card_unit_rate_cents(rate_class):
    """The undiscounted 30-second card rate for a rate class."""
    return round_half_up(
        Decimal(rate_class["posted_rate_cents"]) * DAYPART_MULTIPLIER[rate_class["daypart"]]
    )


def scaled_cap_cents(luc_cents, duration_seconds):
    return round_half_up(Decimal(luc_cents) * Decimal(duration_seconds) / Decimal(UNIT_SECONDS))


def unit_equivalent(charged_rate_cents, duration_seconds):
    return round_half_up(
        Decimal(charged_rate_cents) * Decimal(UNIT_SECONDS) / Decimal(duration_seconds)
    )


def raw_spot_charge(rate_class, duration_seconds, discount_pct):
    return (
        Decimal(rate_class["posted_rate_cents"])
        * DAYPART_MULTIPLIER[rate_class["daypart"]]
        * (Decimal(duration_seconds) / Decimal(UNIT_SECONDS))
        * (Decimal(1) - discount_pct)
    )


def compliance_posture(overdue_count, open_complaint_count):
    breach = max(overdue_count, open_complaint_count)
    if breach >= POSTURE_FROZEN_THRESHOLD:
        return "FROZEN"
    if breach >= POSTURE_RESTRICTED_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


def disclosure_conformance(text, duration_seconds, legal_name):
    """Four branches, top to bottom, first match wins."""
    if text is None or not text.strip():
        return "MISSING"
    if not text.startswith(DISCLOSURE_PREFIX):
        return "NONCONFORMING"
    if legal_name is None or legal_name not in text:
        return "NONCONFORMING"
    if duration_seconds is None or duration_seconds < DISCLOSURE_MIN_SECONDS:
        return "NONCONFORMING"
    return "CONFORMING"

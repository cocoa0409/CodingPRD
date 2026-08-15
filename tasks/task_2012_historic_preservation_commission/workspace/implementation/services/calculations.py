"""Calculation rules (scaffold §1.3), implemented with pinned constants,
pinned rounding order, and the logical clock as the only time source."""
from decimal import Decimal

from db import db
from errors import raise_error
from util import (
    CLOCK, parse_dt, fmt_dt, add_days, whole_days_between, round_half_up_cents,
    rate_times_cents,
)

# --- application_fee constants ---
BASE_FEE_CENTS = {
    "EXTERIOR_ALTERATION": 15000,
    "ADDITION": 30000,
    "NEW_CONSTRUCTION": 50000,
    "DEMOLITION": 25000,
    "RELOCATION": 40000,
    "SITE_WORK": 10000,
}
RATE = {
    "EXTERIOR_ALTERATION": "0.004",
    "ADDITION": "0.005",
    "NEW_CONSTRUCTION": "0.006",
    "DEMOLITION": "0.003",
    "RELOCATION": "0.005",
    "SITE_WORK": "0.002",
}
HEARING_SURCHARGE_CENTS = 20000

# --- review_track_determination constants ---
COMMISSION_REVIEW_THRESHOLD_CENTS = 1000000
COMMISSION_TYPES = {"DEMOLITION", "NEW_CONSTRUCTION", "RELOCATION"}
HIGH_TIERS = {"LANDMARK", "ICONIC"}

# --- civil_penalty constants ---
TIER1_DAILY_CENTS = 10000
TIER2_DAILY_CENTS = 20000
TIER3_DAILY_CENTS = 50000
TIER1_DAYS = 30
TIER2_DAYS = 30
CAP_PCT = Decimal("0.10")
CURE_WINDOW_DAYS = 30

# --- demolition_delay_schedule constants ---
BASE_DELAY_DAYS = {"LOCAL": 90, "LANDMARK": 180, "ICONIC": 365}
DEFAULT_BASE_DELAY_DAYS = BASE_DELAY_DAYS["LOCAL"]  # property outside any district
POSTPONEMENT_EXTENSION_DAYS = 30
MAX_POSTPONEMENTS = 2
HARDSHIP_FILING_CUTOFF_DAYS = 30
HARDSHIP_LIFT_DAYS = 10

# --- notice_window_check constant ---
NOTICE_PERIOD_DAYS = 15


# ---------------------------------------------------------------------------
# application_fee (provisional + final variants)
# ---------------------------------------------------------------------------

def fee_per_item(category: str, cost_cents: int) -> int:
    """base + round_half_up(rate * cost); the variable component is rounded to
    integer cents PER ITEM before any summation (pinned rounding order)."""
    return BASE_FEE_CENTS[category] + rate_times_cents(RATE[category], cost_cents)


def application_fee_declared(work_items) -> int:
    """Provisional variant: declared items, never a hearing surcharge."""
    return sum(fee_per_item(i["category"], i["estimated_cost_cents"]) for i in work_items)


def application_fee_final(verified_work_items, review_track: str) -> int:
    """Final variant: staff-verified items, plus the hearing surcharge AFTER the
    per-item sum when the computed track is COMMISSION."""
    total = sum(fee_per_item(i["category"], i["verified_cost_cents"]) for i in verified_work_items)
    if review_track == "COMMISSION":
        total += HEARING_SURCHARGE_CENTS
    return total


# ---------------------------------------------------------------------------
# review_track_determination (threshold; boundary is >=)
# ---------------------------------------------------------------------------

def determine_review_track(application, prop, district, verified_cost_cents: int) -> str:
    if application["application_type"] in COMMISSION_TYPES:
        return "COMMISSION"
    if verified_cost_cents >= COMMISSION_REVIEW_THRESHOLD_CENTS:
        return "COMMISSION"
    if (
        prop is not None
        and prop.get("contributing_status") == "CONTRIBUTING"
        and application.get("is_visible_from_public_way") is True
        and district is not None
        and district.get("significance_tier") in HIGH_TIERS
    ):
        return "COMMISSION"
    return "STAFF"


# ---------------------------------------------------------------------------
# civil_penalty (demand + final variants); marginal tiers like tax brackets
# ---------------------------------------------------------------------------

def civil_penalty(assessed_value_cents: int, notice_dt, stop_dt):
    """Returns (penalty_cents, penalty_capped). Accrual window
    [notice_issued_at, stop_date) measured in whole days; cap is
    round_half_up(10% of assessed value); capped iff raw strictly exceeds cap."""
    elapsed_days = whole_days_between(notice_dt, stop_dt)
    if elapsed_days < 0:
        elapsed_days = 0
    raw = (
        TIER1_DAILY_CENTS * min(elapsed_days, TIER1_DAYS)
        + TIER2_DAILY_CENTS * min(max(elapsed_days - TIER1_DAYS, 0), TIER2_DAYS)
        + TIER3_DAILY_CENTS * max(elapsed_days - TIER1_DAYS - TIER2_DAYS, 0)
    )
    cap = round_half_up_cents(CAP_PCT * Decimal(int(assessed_value_cents)))
    penalty = min(raw, cap)
    return penalty, (raw > cap)


def demand_letter_penalty(violation, prop) -> int:
    """Demand variant: stop = notice_issued_at + 30 days (cure-window projection)."""
    notice_dt = parse_dt(violation["notice_issued_at"])
    stop_dt = add_days(notice_dt, CURE_WINDOW_DAYS)
    amount, _capped = civil_penalty(prop["assessed_value_cents"], notice_dt, stop_dt)
    return amount


def final_penalty(violation, prop, stop_dt):
    """Final variant: stop = compliance_verified_at (or referred_at when closed
    from COURT_REFERRAL)."""
    notice_dt = parse_dt(violation["notice_issued_at"])
    return civil_penalty(prop["assessed_value_cents"], notice_dt, stop_dt)


# ---------------------------------------------------------------------------
# demolition_delay_schedule (pinned evaluation order) + lazy expiry
# ---------------------------------------------------------------------------

def provisional_delay_end(delay):
    start = parse_dt(delay["delay_start_at"])
    days = delay["base_delay_days"] + delay["postponement_count"] * POSTPONEMENT_EXTENSION_DAYS
    return add_days(start, days)


def provisional_delay_end_iso(delay) -> str:
    return fmt_dt(provisional_delay_end(delay))


def effective_delay_end(delay):
    """final_delay_end when set, otherwise provisional_delay_end."""
    if delay.get("final_delay_end"):
        return parse_dt(delay["final_delay_end"])
    return provisional_delay_end(delay)


def lazy_expire_delay(delay):
    """ACTIVE -> EXPIRED whenever the logical clock has reached or passed the
    effective end. Evaluated on every read of or action on the delay."""
    if delay is None or delay.get("status") != "ACTIVE":
        return delay
    if CLOCK.now() >= effective_delay_end(delay):
        delay["status"] = "EXPIRED"
        from services.core import touch
        touch(delay)
    return delay


def lazy_expire_all_delays():
    for d in db["demolition_delays"].values():
        lazy_expire_delay(d)


def delay_windows_overlap(start_a, end_a, start_b, end_b) -> bool:
    """Half-open interval overlap: adjacency (end == start) is permitted."""
    return start_a < end_b and start_b < end_a


# ---------------------------------------------------------------------------
# fee_refund_schedule (stage-based, round_half_up)
# ---------------------------------------------------------------------------

REFUND_PCT_BY_STAGE = {
    "SUBMITTED": Decimal("1.00"),
    "UNDER_STAFF_REVIEW": Decimal("1.00"),
    "INCOMPLETE": Decimal("1.00"),
    "ACCEPTED": Decimal("0.50"),
    "HEARING_SCHEDULED": Decimal("0.50"),
    "HEARING_DEFERRED": Decimal("0.50"),
    "HEARING_OPEN": Decimal("0.00"),
}


def withdrawal_refund(status: str, paid_fee_cents: int) -> int:
    pct = REFUND_PCT_BY_STAGE.get(status, Decimal("0.00"))
    return round_half_up_cents(Decimal(int(paid_fee_cents)) * pct)


# ---------------------------------------------------------------------------
# notice_window_check (inclusive 15-day boundary)
# ---------------------------------------------------------------------------

def notice_window_ok(notice_posted_at, meeting_date) -> bool:
    """notice_posted_at <= meeting_date - 15 days; the boundary is inclusive."""
    return notice_posted_at <= add_days(meeting_date, -NOTICE_PERIOD_DAYS)

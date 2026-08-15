"""Calculation rules (scaffold 1.3): coverage, accrual schedule, chargeback
formula, SLA constants, trend alert, auto-approval gate constants.

Money is integer cents; rates are Decimal fractions; rounding is round-half-up
to whole cents applied at the pinned points (PRD 2.6).
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from util import add_months

# --- coverage_determination -------------------------------------------------
TERM_MONTHS = {"WORKMANSHIP": 12, "SYSTEMS": 24, "STRUCTURAL": 120}
CATEGORY_TIER_MAP = {
    "DRYWALL_PAINT": "WORKMANSHIP",
    "FLOORING": "WORKMANSHIP",
    "PLUMBING": "SYSTEMS",
    "ELECTRICAL": "SYSTEMS",
    "HVAC": "SYSTEMS",
    "FOUNDATION": "STRUCTURAL",
    "FRAMING": "STRUCTURAL",
}
EXCLUDED_CATEGORIES = {"LANDSCAPING", "APPLIANCE", "ROUTINE_MAINTENANCE"}

# --- sla_deadline_tracking --------------------------------------------------
RESPONSE_SLA_HOURS = {"EMERGENCY": 4, "URGENT": 24, "STANDARD": 72}
COMPLETION_SLA_DAYS = {"EMERGENCY": 3, "URGENT": 7, "STANDARD": 30}

# --- reserve_accrual_schedule ----------------------------------------------
ACCRUAL_RATE = Decimal("0.005")
ACCRUAL_TERM_MONTHS = 120

# --- chargeback_amount ------------------------------------------------------
CHARGEBACK_DEDUCTIBLE_CENTS = 25000
CHARGEBACK_CAP_CENTS = 500000
ADMIN_FEE_RATE = Decimal("0.10")
ADMIN_FEE_MAX_CENTS = 15000

# --- reserve_trend_alert ----------------------------------------------------
ALERT_FRACTION = Decimal("0.20")

# --- chargeback_auto_approval_gate ------------------------------------------
AUTO_APPROVE_CAP_CENTS = 100000
CONTEST_WINDOW_DAYS = 10

# --- dispute / follow-up windows --------------------------------------------
DISPUTE_WINDOW_DAYS = 30
FOLLOWUP_AUTOCLOSE_DAYS = 14


def round_half_up(dec: Decimal) -> int:
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def coverage_check(reported_at, closing_date, tier) -> bool:
    """Half-open coverage window: closing instant <= reported_at < tier end instant."""
    start = datetime(closing_date.year, closing_date.month, closing_date.day, tzinfo=timezone.utc)
    end_d = add_months(closing_date, TERM_MONTHS[tier])
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc)
    return start <= reported_at < end


def expected_accrual_cents(sale_price_cents: int, rate: Decimal = ACCRUAL_RATE) -> int:
    """round_half_up(sale_price_cents * rate), rounded once when computed."""
    return round_half_up(Decimal(sale_price_cents) * rate)


def monthly_accrual_cents(expected_cents: int) -> int:
    """round_half_up(expected / 120) — each month rounded individually."""
    return round_half_up(Decimal(expected_cents) / ACCRUAL_TERM_MONTHS)


def accrual_for_month(expected_cents: int, month_index: int) -> int:
    """Months 1..119 take the rounded monthly value; month 120 takes the remainder."""
    monthly = monthly_accrual_cents(expected_cents)
    if month_index < ACCRUAL_TERM_MONTHS:
        return monthly
    return expected_cents - (ACCRUAL_TERM_MONTHS - 1) * monthly


def chargeback_amount(cost_cents: int) -> int:
    """recoverable = max(0, cost - deductible); capped = min(recoverable, cap);
    fee = min(round_half_up(capped * 10%), fee_max); total = capped + fee."""
    recoverable = max(0, cost_cents - CHARGEBACK_DEDUCTIBLE_CENTS)
    capped = min(recoverable, CHARGEBACK_CAP_CENTS)
    admin_fee = min(round_half_up(Decimal(capped) * ADMIN_FEE_RATE), ADMIN_FEE_MAX_CENTS)
    return capped + admin_fee


def alert_status_for(balance_cents: int, expected_cents: int) -> str:
    """Strictly-below triggers: balance < 0 DEPLETED; balance < threshold ELEVATED;
    otherwise NORMAL (balance exactly == threshold is NORMAL)."""
    if balance_cents < 0:
        return "DEPLETED"
    threshold = round_half_up(Decimal(expected_cents) * ALERT_FRACTION)
    if balance_cents < threshold:
        return "ELEVATED"
    return "NORMAL"

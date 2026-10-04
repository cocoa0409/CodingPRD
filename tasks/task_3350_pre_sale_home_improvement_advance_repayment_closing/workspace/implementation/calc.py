"""Pinned program constants and money math (PRD 2.5, scaffold calculations).

All money is integer cents. Fee lines: rate * principal rounded HALF_UP per
line, then summed. Caps: floored. Decimal only — never float for money.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

ADVANCE_LIMIT_RATE = Decimal("0.15")
MIN_EQUITY_RATIO = Decimal("1.10")
LATE_GRACE_DAYS = 7
PROGRAM_FEE_RATE_A = Decimal("0.03")
PROGRAM_FEE_RATE_B = Decimal("0.01")
LATE_ACCRUAL_RATE = Decimal("0.005")
LATE_FEE_RATE = Decimal("0.002")
VENDOR_FAULT_PENALTY_BP = 500
LATE_PENALTY_BP = 200
QUALITY_RECOVERY_BP = 50
QUALITY_SCORE_CAP_BP = 10000
DEFAULT_LISTING_WINDOW_DAYS = 180

SECONDS_PER_DAY = Decimal(86400)

VARIANT_A_BASES = ("LISTED_WITHIN_WINDOW", "SOLD_WITHIN_WINDOW")
VARIANT_B_BASES = ("NOT_LISTED_WITHIN_WINDOW", "SOLD_AFTER_WINDOW")


def floor_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_advance_limit(proceeds_cents, estimated_value_cents, contribution_cents):
    cap = floor_cents(Decimal(proceeds_cents) * ADVANCE_LIMIT_RATE)
    if contribution_cents > 0:
        cap = min(cap, proceeds_cents - estimated_value_cents)
    return cap


def days_between(start, end):
    """Exact (fractional) days between two datetimes, as Decimal."""
    return Decimal((end - start).total_seconds()) / SECONDS_PER_DAY


def months_late(days, window_days):
    """ceil((days_between - listing_window_days) / 30), floored at 0."""
    late_days = days - Decimal(window_days)
    if late_days <= 0:
        return 0
    return int((late_days / Decimal(30)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def compute_fees(payoff_basis, advance_repayment_cents, days, window_days):
    """Dual-variant program fee plus late fee (scaffold calculation rules)."""
    principal = Decimal(advance_repayment_cents)
    if payoff_basis in VARIANT_A_BASES:
        program_fee = round_half_up_cents(principal * PROGRAM_FEE_RATE_A)
        late_fee = 0
    else:
        months = months_late(days, window_days)
        program_fee = (
            round_half_up_cents(principal * PROGRAM_FEE_RATE_B)
            + round_half_up_cents(principal * LATE_ACCRUAL_RATE * months)
        )
        late_fee = round_half_up_cents(principal * LATE_FEE_RATE * months)
    return program_fee, late_fee

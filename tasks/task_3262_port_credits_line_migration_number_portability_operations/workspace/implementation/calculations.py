"""Calculation rules (scaffold `calculations`, PRD 3).

All monetary arithmetic uses Decimal and rounds half-up to whole cents. Every
constant is copied verbatim from the scaffold.
"""

from decimal import Decimal, ROUND_HALF_UP

import clock

# --- port_in_promo_credit_projection ---------------------------------------
BASE_CREDIT_CENTS = 20000
MONTHLY_BASE_CENTS = 1000

# --- trade_in_credit_assessment --------------------------------------------
GRADE_VALUE_CENTS = {
    "FLAWLESS": 60000,
    "GOOD": 42000,
    "FAIR": 24000,
    "POOR": 8000,
    "BROKEN": 0,
}

# --- credit_class_determination --------------------------------------------
DEPOSIT_CLASS_A = 0
DEPOSIT_CLASS_B = 10000
DEPOSIT_CLASS_C = 25000
DEPOSIT_CLASS_D = 50000
CLASS_DEPOSIT_CENTS = {
    "CLASS_A": DEPOSIT_CLASS_A,
    "CLASS_B": DEPOSIT_CLASS_B,
    "CLASS_C": DEPOSIT_CLASS_C,
    "CLASS_D": DEPOSIT_CLASS_D,
    "BLOCKED": 0,
}
FAMILY_TIER_LINE_THRESHOLD = 5

# --- device_installment_balance --------------------------------------------
DAYS_PER_BILLING_CYCLE = 30

# --- migration_proration_credit --------------------------------------------
TIER_RATE_CENTS = {1: 5000, 2: 4000, 3: 3000, 4: 2500}
DAYS_IN_CYCLE = 30
CARRY_WEIGHT = Decimal("0.50")


def round_half_up(value):
    """Round a Decimal (or numeric) to a whole number of cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
def promo_billable_months(installment_months, retention_requirement_cycles):
    return min(installment_months, retention_requirement_cycles)


def promo_provisional_total(installment_months, retention_requirement_cycles):
    """Forward-looking projection: base credit plus every billable month."""
    months = promo_billable_months(installment_months, retention_requirement_cycles)
    return BASE_CREDIT_CENTS + MONTHLY_BASE_CENTS * months


def promo_vested_total(cycles_elapsed):
    """Chronological accumulation: only cycles actually completed in the window."""
    return MONTHLY_BASE_CENTS * cycles_elapsed


def promo_window_end(window_start, installment_months):
    return clock.add_days(window_start, installment_months * DAYS_PER_BILLING_CYCLE)


def promo_cycles_elapsed(window_start, instant=None):
    """Completed billing cycles inside the window as of the logical clock."""
    if instant is None:
        instant = clock.now()
    if window_start is None or instant < window_start:
        return 0
    return clock.completed_cycles(window_start, instant)


def trade_in_value(condition):
    return GRADE_VALUE_CENTS.get(condition, 0)


def trade_in_estimated(declared_condition):
    return trade_in_value(declared_condition)


def trade_in_final(graded_condition):
    return trade_in_value(graded_condition)


def trade_in_grade_delta(estimated_credit_cents, final_credit_cents):
    return final_credit_cents - estimated_credit_cents


# ---------------------------------------------------------------------------
def credit_class_from_score(payment_history_score):
    if payment_history_score < 300:
        return "BLOCKED"
    if payment_history_score < 500:
        return "CLASS_D"
    if payment_history_score < 650:
        return "CLASS_C"
    if payment_history_score < 800:
        return "CLASS_B"
    return "CLASS_A"


def credit_class_determination(payment_history_score, active_line_count, line_count):
    """Return (determined_credit_class, required_deposit_cents).

    Evaluated against the account's active_line_count as observed at evaluation
    time plus the request's line_count.
    """
    lines_after = active_line_count + line_count
    raw_class = credit_class_from_score(payment_history_score)
    if lines_after >= FAMILY_TIER_LINE_THRESHOLD and raw_class in ("CLASS_A", "CLASS_B"):
        determined = "CLASS_C"
    else:
        determined = raw_class
    return determined, CLASS_DEPOSIT_CENTS[determined]


def deposit_for_class(credit_class):
    return CLASS_DEPOSIT_CENTS.get(credit_class, 0)


# ---------------------------------------------------------------------------
def financed_balance_cents(device_price_cents, down_payment_cents):
    return max(device_price_cents - down_payment_cents, 0)


def level_installment_cents(balance_cents, installment_months):
    """Floor the per-installment amount; the remainder goes to the first one."""
    if installment_months <= 0:
        return 0, balance_cents
    monthly = balance_cents // installment_months
    first = balance_cents - monthly * (installment_months - 1)
    return monthly, first


def remaining_balance_cents(financed_balance, trade_in_credit_cents):
    return max(financed_balance - trade_in_credit_cents, 0)


def upgrade_eligible_at(financed_at, installment_months):
    """financed_at plus half the term in billing cycles (halving floors)."""
    if financed_at is None:
        return None
    half_cycles = installment_months // 2
    return clock.add_days(financed_at, half_cycles * DAYS_PER_BILLING_CYCLE)


# ---------------------------------------------------------------------------
def migration_proration_credit(active_line_count, prepaid_balance_cents,
                               device_balance_cents, instant=None):
    """Pinned evaluation order (scaffold `migration_proration_credit`)."""
    if instant is None:
        instant = clock.now()
    # 1. the migration itself contributes the line
    lines_after = active_line_count + 1
    # 2. tier capped at four
    tier = min(lines_after, 4)
    # 3. plan rate for the tier
    plan_rate_cents = TIER_RATE_CENTS[tier]
    # 4. remaining days in the cycle, floored at zero
    remaining_days = DAYS_IN_CYCLE - clock.day_of_month(instant)
    if remaining_days < 0:
        remaining_days = 0
    # 5. proration component
    proration_component = round_half_up(
        Decimal(plan_rate_cents) * Decimal(remaining_days) / Decimal(DAYS_IN_CYCLE)
    )
    # 6. carry component
    carry_component = round_half_up(
        CARRY_WEIGHT * Decimal(prepaid_balance_cents + device_balance_cents)
    )
    # 7. total
    return proration_component + carry_component


# ---------------------------------------------------------------------------
def promo_clawback_reversal(schedule):
    """The reversal is exactly the schedule's own provisional total."""
    return schedule["provisional_total_cents"]
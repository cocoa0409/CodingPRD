"""Concession settlement: percentage rent, guarantees, net rent (PRD section 3.10)."""
import clock
import db
from services.money import apply_bps, round_half_up

SECONDS_PER_DAY = 86400
MARKETING_TIERS = ((5000000, 400), (2000000, 250))
BASE_TIER_BPS = 100


def percentage_rent(agreement):
    return apply_bps(agreement["gross_sales_cents"], agreement["rent_pct_bps"])


def derive_basis(percentage, floor_cents):
    return "PERCENTAGE" if percentage >= floor_cents else "MINIMUM_GUARANTEE"


def recompute_accrual(agreement):
    """Cascade levels 3 and 4 of the pickup / void compensation."""
    agreement["percentage_rent_cents"] = percentage_rent(agreement)
    agreement["rent_basis"] = derive_basis(
        agreement["percentage_rent_cents"], agreement["minimum_guarantee_cents"]
    )


def period_days(agreement):
    start = clock.parse(agreement["period_start_utc"])
    end = clock.parse(agreement["period_end_utc"])
    return int((end - start).total_seconds()) // SECONDS_PER_DAY


def elapsed_days(agreement, days_in_period):
    start = clock.parse(agreement["period_start_utc"])
    raw = int((clock.now() - start).total_seconds()) // SECONDS_PER_DAY + 1
    raw = max(1, raw)
    if days_in_period is not None:
        raw = min(days_in_period, raw)
    return raw


def projection(agreement):
    days_in_period = period_days(agreement)
    elapsed = elapsed_days(agreement, days_in_period)
    percentage = agreement["percentage_rent_cents"]
    if days_in_period > 0:
        prorated = round_half_up(
            agreement["minimum_guarantee_cents"] * elapsed, days_in_period
        )
    else:
        prorated = agreement["minimum_guarantee_cents"]
    return {
        "gross_sales_cents": agreement["gross_sales_cents"],
        "percentage_rent_cents": percentage,
        "period_days": days_in_period,
        "elapsed_days": elapsed,
        "prorated_minimum_guarantee_cents": prorated,
        "provisional_rent_cents": max(percentage, prorated),
        "rent_basis": derive_basis(percentage, prorated),
    }


def marketing_tier_bps(final_rent_cents):
    for floor_cents, tier_bps in MARKETING_TIERS:
        if final_rent_cents >= floor_cents:
            return tier_bps
    return BASE_TIER_BPS


def settle(agreement):
    """FINAL_PERIOD_CLOSE followed by the tiered marketing credit."""
    percentage = percentage_rent(agreement)
    agreement["percentage_rent_cents"] = percentage
    guarantee = agreement["minimum_guarantee_cents"]
    final_rent = max(percentage, guarantee)
    agreement["final_rent_cents"] = final_rent
    agreement["rent_basis"] = derive_basis(percentage, guarantee)
    credit = apply_bps(final_rent, marketing_tier_bps(final_rent))
    agreement["marketing_credit_cents"] = credit
    agreement["net_rent_cents"] = final_rent - credit
    agreement["status"] = "CLOSED"
    agreement["closed_at"] = clock.now_iso()


def agreement_for_period(terminal_id, period_code):
    for agreement in db.ordered(db.agreements,
                               lambda a: a["terminal_id"] == terminal_id
                               and a["period_code"] == period_code):
        return agreement
    return None

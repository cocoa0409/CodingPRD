"""Calculation rules (SCAFFOLD §1.3 / PRD §3), integer-cents throughout."""

from constants import (
    CAPITALIZATION_BPS,
    CONDITION_FACTOR_BPS,
    PROVISIONAL_PROJECTION_MONTHS,
    ISR_PROJECTION_MONTHS,
    MONTHLY_CARRYING_COST_CENTS,
    INTERLOCUTORY_RATIO_THRESHOLD_PCT,
    TIER1_CAP_CENTS,
    TIER1_BPS,
    TIER2_CAP_CENTS,
    TIER2_BPS,
    TIER3_BPS,
    DEPRECIATION_PER_GRADE_STEP_BPS,
    DEPRECIATION_PER_MONTH_BPS,
    DEPRECIATION_CAP_BPS,
    GRADE_RANK,
)
from util import rhu


# ---------------------------------------------------------------------------
# condition_adjusted_valuation — Valuation creation
# ---------------------------------------------------------------------------
def adjusted_value(method, raw_value_cents, assessed_condition_grade, annual_net_revenues):
    """Compute adjusted_value_cents at Valuation creation.

    INCOME_APPROACH: each of the 3 annual net revenues is capitalized at
    3300 bps and rounded half-up PER YEAR, then the three rounded products
    are summed (pinned rounding order).
    Other methods: raw x condition factor, rounded half-up once.
    """
    if method == "INCOME_APPROACH":
        return sum(rhu(rev * CAPITALIZATION_BPS, 10000) for rev in annual_net_revenues)
    factor = CONDITION_FACTOR_BPS[assessed_condition_grade]
    return rhu(raw_value_cents * factor, 10000)


# ---------------------------------------------------------------------------
# retention_value_estimate — dual variant, derived from current store state
# ---------------------------------------------------------------------------
def _latest(valuations):
    """'latest' = greatest created_at; insertion sequence breaks any tie."""
    if not valuations:
        return None
    return max(valuations, key=lambda v: (v["created_at"], v["_seq"]))


def retention_values(asset, valuations):
    """Return (provisional_net_retention_value_cents, final_net_retention_value_cents).

    FINAL: latest ACCEPTED adjusted value minus actual accumulated net cost;
           null until the first ACCEPTED valuation.
    PROVISIONAL: latest SUBMITTED (preferred) else latest ACCEPTED adjusted
           value, minus (accumulated cost + 6-month projected carrying cost);
           null until at least one valuation exists in any status.
    """
    accepted = [v for v in valuations if v["status"] == "ACCEPTED"]
    submitted = [v for v in valuations if v["status"] == "SUBMITTED"]
    rejected = [v for v in valuations if v["status"] == "REJECTED"]

    latest_accepted = _latest(accepted)
    if latest_accepted is None:
        final = None
    else:
        final = (
            latest_accepted["adjusted_value_cents"]
            - asset["accumulated_net_holding_cost_cents"]
        )

    base = _latest(submitted) or latest_accepted or _latest(rejected)
    if base is None:
        provisional = None
    else:
        burden = asset["accumulated_net_holding_cost_cents"] + (
            PROVISIONAL_PROJECTION_MONTHS
            * MONTHLY_CARRYING_COST_CENTS[asset["asset_type"]]
        )
        provisional = base["adjusted_value_cents"] - burden

    return provisional, final


# ---------------------------------------------------------------------------
# interlocutory_eligibility — pinned integer comparison, boundary inclusive
# ---------------------------------------------------------------------------
def projected_burden_cents(asset):
    """accumulated net holding cost + ISR_PROJECTION_MONTHS x monthly rate."""
    return asset["accumulated_net_holding_cost_cents"] + (
        ISR_PROJECTION_MONTHS * MONTHLY_CARRYING_COST_CENTS[asset["asset_type"]]
    )


def interlocutory_eligible(asset):
    """True iff projected_burden * 100 >= 30 * appraised_value_cents.

    Callers guarantee appraised_value_cents is non-null (legal-state gates
    run first, so a null value is unreachable here).
    """
    appraised = asset["appraised_value_cents"]
    if appraised is None:
        return False
    return (
        projected_burden_cents(asset) * 100
        >= INTERLOCUTORY_RATIO_THRESHOLD_PCT * appraised
    )


# ---------------------------------------------------------------------------
# auction_fee_schedule — tiered MARGINAL fee; per-bracket RHU then summed
# ---------------------------------------------------------------------------
def auction_fee_cents(gross_proceeds_cents):
    b1 = min(gross_proceeds_cents, TIER1_CAP_CENTS)
    f1 = rhu(b1 * TIER1_BPS, 10000)
    rem1 = gross_proceeds_cents - b1
    b2 = min(rem1, TIER2_CAP_CENTS)
    f2 = rhu(b2 * TIER2_BPS, 10000)
    b3 = rem1 - b2
    f3 = rhu(b3 * TIER3_BPS, 10000)
    return f1 + f2 + f3


# ---------------------------------------------------------------------------
# depreciation_on_return
# ---------------------------------------------------------------------------
def full_months_held(seized_on, now):
    """Whole calendar months from seized_on to now.

    (now.year - seized.year) * 12 + (now.month - seized.month), minus one
    when now's day-of-month is earlier than the seizure day-of-month.
    """
    months = (now.year - seized_on.year) * 12 + (now.month - seized_on.month)
    if now.day < seized_on.day:
        months -= 1
    return months


def depreciation_cents(asset, return_condition_grade, now):
    """Computed depreciation recorded at complete-return (0 when unappraised)."""
    appraised = asset["appraised_value_cents"]
    if appraised is None:
        return 0
    grade_steps_down = max(
        0,
        GRADE_RANK[asset["seizure_condition_grade"]]
        - GRADE_RANK[return_condition_grade],
    )
    months = full_months_held(asset["seized_on"], now)
    fraction_bps = min(
        DEPRECIATION_CAP_BPS,
        DEPRECIATION_PER_GRADE_STEP_BPS * grade_steps_down
        + DEPRECIATION_PER_MONTH_BPS * months,
    )
    return rhu(appraised * fraction_bps, 10000)

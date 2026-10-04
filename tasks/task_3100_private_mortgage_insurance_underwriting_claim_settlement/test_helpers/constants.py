"""Domain thresholds — the numeric constants the pricing and claim rules use.

These are the pinned reference figures the PRD states explicitly, kept in one
place so tests assert against named constants rather than magic numbers.
"""

# The canonical master policy terms.
MASTER_POLICY = {
    "delegated_curtailment_rate": 0.12,
    "nondelagated_curtailment_rate": 0.08,
    "ltv_variance_tolerance": 0.05,
    "rescission_relief_cycles": 2,
    "min_third_party_net_bps": 1500,
    "exposure_contribution_rate": 0.35,
}

# The canonical rate card.
RATE_CARD = {
    "credit_grade": "B",
    "ltv_band": "831_TO_85",
    "coverage_percent": 25,
    "premium_plan": "BPM",
    "rate_bps": 62,
}

# The canonical delegated loan.
LOAN = {
    "loan_amount_cents": 34_000_000,
    "property_value_cents": 40_000_000,
    "coverage_percent": 25,
    "coverage_base_upb_cents": 8_500_000,
    "rate_bps_applied": 62,
    "annual_premium_cents": 52_700,
    "monthly_period_cents": 4_392,
    "final_period_cents": 4_388,
}

# The canonical claim items and the arithmetic they produce.
CLAIM = {
    "unpaid_principal_cents": 8_000_000,
    "accrued_interest_cents": 1_500_000,
    "allowable_advances_cents": 5_000_000,
    "gross_proceeds_cents": 7_000_000,
    "expenses_of_sale_cents": 500_000,
    "permitted_interest_cents": 1_200_000,
    "permitted_advances_cents": 5_000_000,
    "net_unpaid_balance_cents": 14_200_000,
    "recoverable_amount_cents": 7_700_000,
    "coverage_ceiling_cents": 8_500_000,
    "covered_claim_amount_cents": 7_700_000,
    "curtailment_rate_applied": 0.12,
    "post_curtailment_cents": 6_776_000,
    "claim_deductible_cents": 677_600,
    "net_claim_amount_cents": 6_098_400,
}

# Credit-grade deductible rates.
DEDUCTIBLE_RATE = {"A": 0.05, "B": 0.10, "C": 0.15, "D": 0.20}

# Percentage caps used by the claim computation.
INTEREST_CAP_RATE = 0.15
ADVANCES_CAP_RATE = 1.10
THIRD_PARTY_MIN_PROCEEDS_RATIO = 0.85

# Milestone thresholds against the origination property value.
MILESTONE_80_RATIO = 0.80
MILESTONE_78_RATIO = 0.78

# Cancellation deferrals and the milestone deferral.
MIN_NOTICE_DAYS = 30
DEFICIENCY_MIN_DAYS = 60

# Logical clock default.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
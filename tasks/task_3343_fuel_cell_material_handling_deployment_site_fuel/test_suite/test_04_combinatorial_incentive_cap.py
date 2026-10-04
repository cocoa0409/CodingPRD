"""FEDERAL_ITC evaluation order and the claimed-amount cap (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success, setup_site_with_completed_conversion,
    create_submitted_claim, COMPLIANCE,
)

# Gate: 50 x 1.20 = 60.0; recorded 61.0 via TELEMATICS passes.
PLAN_KW = {"baseline_productivity_units_per_hour": 50.0,
           "expected_productivity_gain_pct": 20}


def _setup_two_submitted_claims():
    site, plan, _events, _tech = setup_site_with_completed_conversion(
        "S-ITC", "Tech ITC", num_events=2, plan_overrides=PLAN_KW,
        record_productivity=("TELEMATICS", 61.0))
    claim_low = create_submitted_claim(site["id"], claimed_amount_cents=900000)
    claim_high = create_submitted_claim(site["id"], claimed_amount_cents=2000000)
    return site, claim_low, claim_high


def test_itc_approval_capped_by_claimed_amount(api):
    """PRD §3.7: "apply the 30 percent investment tax credit rate, again
    rounding half-up to integer cents; and finally cap the result at the
    claim's `claimed_amount_cents`."

    Design: Difficulty/combinatorial_formula/incentive_evaluation_order_with_cap
    """
    site, claim_low, _claim_high = _setup_two_submitted_claims()
    approved = validate_success(api.approve_claim(site["id"], claim_low["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED"
    # Computed ITC (2 x 1,500,000 x 1.20 x 0.30 = 1,080,000) exceeds the
    # 900,000-cent claim, so the cap binds.
    assert approved["approved_amount_cents"] == 900000


def test_itc_approval_uncapped_full_computation(api):
    """PRD §3.7: "take the governing plan; count its conversion events in
    `COMPLETED` status as the converted units; multiply by a qualified capital
    expenditure of 1,500,000 cents per converted unit; uplift that capex by the
    plan's gain fraction (its `expected_productivity_gain_pct` divided by one
    hundred), rounding half-up to integer cents; apply the 30 percent
    investment tax credit rate, again rounding half-up to integer cents; and
    finally cap the result at the claim's `claimed_amount_cents`."

    Design: Difficulty/combinatorial_formula/incentive_evaluation_order_with_cap
    """
    site, _claim_low, claim_high = _setup_two_submitted_claims()
    approved = validate_success(api.approve_claim(site["id"], claim_high["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED"
    # 2 converted units x 1,500,000 = 3,000,000; uplifted x1.20 = 3,600,000;
    # ITC x0.30 = 1,080,000; below the 2,000,000-cent claim so uncapped.
    assert approved["approved_amount_cents"] == 1080000

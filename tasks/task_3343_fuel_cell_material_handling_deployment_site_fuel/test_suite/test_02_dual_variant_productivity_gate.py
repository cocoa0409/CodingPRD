"""Productivity measurement variants: TELEMATICS verbatim vs SELF_REPORTED
haircut, and how the recorded figure decides the FEDERAL_ITC gate (PRD §3.7).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_site_with_completed_conversion, create_submitted_claim,
    COMPLIANCE, api_client,
)

PLAN_KW = {"baseline_productivity_units_per_hour": 60.0,
           "expected_productivity_gain_pct": 10}


def test_telematics_recorded_verbatim_and_gate_passes(api):
    """PRD §3.7: "When `measurement_mode` is `TELEMATICS`, the metered figure is
    trusted verbatim: the site's `actual_productivity_units_per_hour` becomes
    exactly the reported figure."
    PRD §3.7: "multiply by a qualified capital expenditure of 1,500,000 cents
    per converted unit; uplift that capex by the plan's gain fraction (its
    `expected_productivity_gain_pct` divided by one hundred), rounding half-up
    to integer cents; apply the 30 percent investment tax credit rate, again
    rounding half-up to integer cents; and finally cap the result at the
    claim's `claimed_amount_cents`."

    Design: Difficulty/dual_variant_calc/productivity_telematics_vs_self_reported_gate
    """
    site, plan, _events, _tech = setup_site_with_completed_conversion(
        "S-TEL", "Tech One", num_events=1, plan_overrides=PLAN_KW,
        record_productivity=("TELEMATICS", 66.0))
    site_after = validate_success(api.get_site(site["id"], COMPLIANCE))
    assert site_after["actual_productivity_units_per_hour"] == pytest.approx(66.0), (
        "TELEMATICS records the reported figure verbatim")
    claim = create_submitted_claim(site["id"], claimed_amount_cents=99999999)
    approved = validate_success(api.approve_claim(site["id"], claim["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED"
    # 1 unit x 1,500,000 x 1.10 x 0.30 = 495,000, below the claimed cap.
    assert approved["approved_amount_cents"] == 495000


def test_self_reported_haircut_fails_productivity_gate(api):
    """PRD §3.7: "When it is `SELF_REPORTED`, a confidence haircut applies
    because customer-reported throughput historically overstates gains: the
    recorded figure is 90 percent of the reported figure, rounded half-up to 2
    decimal places."
    PRD §3.7: "A missing plan, missing measurement, or shortfall rejects
    approval with `ERR_PRODUCTIVITY_GATE_NOT_MET` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/productivity_telematics_vs_self_reported_gate
    """
    site, plan, _events, _tech = setup_site_with_completed_conversion(
        "S-SELF", "Tech Two", num_events=1, plan_overrides=PLAN_KW,
        record_productivity=("SELF_REPORTED", 66.0))
    site_after = validate_success(api.get_site(site["id"], COMPLIANCE))
    # 66.0 x 0.90 = 59.40, below the gate at 60 x 1.10 = 66.00.
    assert site_after["actual_productivity_units_per_hour"] == pytest.approx(59.4)
    claim = create_submitted_claim(site["id"], claimed_amount_cents=99999999)
    resp = api.approve_claim(site["id"], claim["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PRODUCTIVITY_GATE_NOT_MET)
    after = get_success_data(api.get_incentive_claim(claim["id"], COMPLIANCE))
    assert after["status"] == "SUBMITTED", "rejected approval leaves the claim SUBMITTED"
    assert after["approved_amount_cents"] is None

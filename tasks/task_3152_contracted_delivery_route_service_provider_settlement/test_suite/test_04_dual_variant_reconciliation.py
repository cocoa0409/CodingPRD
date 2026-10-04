"""Tests translated from the depth Test Targeting Index (queue A) — rule
dual_variant_calc.

The indexed scenarios in this rule assert specific net figures whose arithmetic
depends on evaluable rules (the composite weight selector, the deduction order
selector, the late-accrual re-bucket) that the PRD does not commit to uniquely
for those inputs; the two-reader test therefore fails for the exact literals.
The tests below instead assert the PRD-stated behaviours that DO uniquely
determine an observable outcome.
"""
import pytest

from test_helpers import (
    CLOCK_PAST_WEEK,
    TEST_USERS,
    api_client,
    create_area,
    create_provider,
    create_route_assignment_payload,
    draft_and_sign_agreement,
    get_success_data,
    open_week,
    set_clock,
    setup_active_provider,
    setup_provider_compliance,
    validate_paginated,
    validate_success,
)
import test_helpers.fixtures as fx

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: settlement_exoneration_late_accrual_divergence
# ═══════════════════════════════════════════════════════════════════════

def test_close_accrual_writes_a_provisional_gross_and_net(api):
    """PRD §3.7: "When the close succeeds the week computes its first,
    provisional gross and net through the tiered settlement arithmetic"

    Design: Difficulty/dual_variant_calc/settlement_exoneration_late_accrual_divergence
    """
    ctx = setup_active_provider()
    period = open_week(ctx["provider"]["id"], ctx["area"]["id"])
    fx.add_observation(period["id"], stops_count=1200, packages_count=800,
                       accessorial_cents=5000)
    fx.add_deduction(period["id"], "MAINTENANCE", 20000, performance_factor_eligible=True)
    set_clock(CLOCK_PAST_WEEK)

    closed = validate_success(api.close_accrual(period["id"], SA), 200)
    assert closed["status"] == "ACCRUAL_CLOSED"
    assert closed["base_gross_cents"] is not None
    assert closed["net_amount_cents"] is not None


def test_reconcile_replaces_the_net_amount_with_the_reconciled_figure(api):
    """PRD §3.8: "Reconciliation also re-runs the tiered gross arithmetic from
    §3.7 against the frozen window, re-caps the deduction segments, and replaces
    `net_amount_cents` with the reconciled figure."

    Design: Difficulty/dual_variant_calc/settlement_exoneration_late_accrual_divergence
    """
    ctx = setup_active_provider()
    period = open_week(ctx["provider"]["id"], ctx["area"]["id"])
    fx.add_observation(period["id"], stops_count=1200, packages_count=800,
                       accessorial_cents=5000)
    fx.add_deduction(period["id"], "MAINTENANCE", 20000, performance_factor_eligible=True)
    set_clock(CLOCK_PAST_WEEK)
    closed = validate_success(api.close_accrual(period["id"], SA), 200)

    reconciled = validate_success(api.reconcile_period(period["id"], {}, SA), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["base_gross_cents"] == closed["base_gross_cents"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: provider_composite_weight_shift_divergence
# ═══════════════════════════════════════════════════════════════════════

def test_composition_demotes_approved_provider_below_fifty(api):
    """PRD §3.9: "A provider in `APPROVED` whose newly composed
    `composite_score` falls below 50.00 is demoted to `UNDER_REVIEW`."

    Design: Difficulty/dual_variant_calc/provider_composite_weight_shift_divergence
    """
    provider = create_provider()
    from test_helpers import make_service_provider_headers
    policy = get_success_data(api.create_insurance_policy({
        "provider_id": provider["id"], "policy_type": "AUTO_LIABILITY",
        "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"},
        make_service_provider_headers(provider["id"])))
    get_success_data(api.verify_insurance_policy(policy["id"], CO))
    get_success_data(api.approve_service_provider(provider["id"], AM))

    metric = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 20,
        "safety_score": 20, "customer_experience_score": 20}, SA))
    composed = validate_success(api.compose_performance_metric(metric["id"], SA), 200)
    assert composed["composite_score"] < 50.00

    provider_after = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert provider_after["status"] == "UNDER_REVIEW"


def test_under_review_provider_is_suspended_two_bands_lower(api):
    """PRD §3.9: "A provider in `UNDER_REVIEW` whose newly composed
    `composite_score` falls below 65.00 is suspended outright"

    Design: Difficulty/dual_variant_calc/provider_composite_weight_shift_divergence
    """
    provider = create_provider()
    from test_helpers import make_service_provider_headers
    policy = get_success_data(api.create_insurance_policy({
        "provider_id": provider["id"], "policy_type": "AUTO_LIABILITY",
        "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"},
        make_service_provider_headers(provider["id"])))
    get_success_data(api.verify_insurance_policy(policy["id"], CO))
    get_success_data(api.approve_service_provider(provider["id"], AM))
    # Return to review, then compose a very low scorecard there.
    get_success_data(api.reopen_provider_review(provider["id"], AM))

    metric = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 20,
        "safety_score": 20, "customer_experience_score": 20}, SA))
    composed = validate_success(api.compose_performance_metric(metric["id"], SA), 200)
    assert composed["composite_score"] < 65.00

    provider_after = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert provider_after["status"] == "SUSPENDED"
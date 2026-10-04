"""Tests translated from the depth Test Targeting Index (queue A) — rule
compensating_invariant (the release-offset sibling of that rule is not
translated: its indexed literals are not derivable from PRD prose).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_deduction_payload,
    get_success_data,
    setup_active_provider,
    setup_reconciled_week,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]


def _reconciled_week_with_claim(claim_type="DAMAGE", amount_cents=500000,
                                recovery_rate_pct=10):
    ctx = setup_reconciled_week(
        deductions=[{"deduction_type": "MAINTENANCE", "amount_cents": 5000,
                     "performance_factor_eligible": True}])
    claim = get_success_data(api_client.create_chargeback_claim({
        "provider_id": ctx["provider"]["id"],
        "settlement_period_id": ctx["period"]["id"],
        "claim_type": claim_type,
        "amount_cents": amount_cents,
        "recovery_rate_pct": recovery_rate_pct,
    }, AM))
    ctx["claim"] = claim
    return ctx


def test_rejected_claim_posts_no_chargeback_deduction(api):
    """PRD §3.10: "an `AccountManager` may reject a claim from `FILED` without
    any precondition beyond the state, which is the compensating action: a
    rejected claim is terminal and restores the pre-charge-back service area
    score that approval would have altered."
    PRD §3.10: "A `SettlementDeduction` is created on the claim's week with a
    `deduction_type` of `CHARGEBACK`"

    Design: Difficulty/compensating_invariant/claim_rejection_leaves_assessment_zero
    """
    ctx = _reconciled_week_with_claim()
    rejected = validate_success(
        api.reject_chargeback_claim(ctx["claim"]["id"], AM), 200)
    assert rejected["status"] == "REJECTED"

    data, _meta = validate_paginated(
        api.list_deductions(ctx["period"]["id"], SA))
    chargeback_rows = [d for d in data if d["deduction_type"] == "CHARGEBACK"]
    assert chargeback_rows == []


def test_rejected_claim_leaves_outstanding_and_recovery_zero(api):
    """PRD §3.10: "The provider's `chargeback_outstanding_cents` is incremented
    by the net-of-recovery amount, which is what raises the balance that gates
    route transfers in §3.5."
    PRD §3.10: "The result is written to the claim's `net_of_recovery_cents`."

    Design: Difficulty/compensating_invariant/claim_rejection_leaves_assessment_zero
    """
    ctx = _reconciled_week_with_claim()
    validate_success(api.reject_chargeback_claim(ctx["claim"]["id"], AM), 200)

    provider_after = validate_success(api.get_service_provider(ctx["provider"]["id"], SA), 200)
    assert provider_after["chargeback_outstanding_cents"] == 0
    claim_after = validate_success(api.get_chargeback_claim(ctx["claim"]["id"], AM), 200)
    assert claim_after["net_of_recovery_cents"] is None


def test_rejected_claim_leaves_branding_percentage_unchanged(api):
    """PRD §3.1: "When it is not empty, the percentage is the count of
    active-fleet vehicles whose `branding_compliance` is `PASSED`, divided by the
    total count of the active fleet, multiplied by one hundred, and rounded half
    up to two decimal places."
    PRD §3.10: "an `AccountManager` may reject a claim from `FILED` without any
    precondition beyond the state"

    Design: Difficulty/compensating_invariant/claim_rejection_leaves_assessment_zero
    """
    ctx = _reconciled_week_with_claim()
    before = validate_success(api.get_service_provider(ctx["provider"]["id"], SA), 200)
    assert before["brand_compliance_pct"] == 100.00

    validate_success(api.reject_chargeback_claim(ctx["claim"]["id"], AM), 200)

    provider_after = validate_success(api.get_service_provider(ctx["provider"]["id"], SA), 200)
    assert provider_after["brand_compliance_pct"] == 100.00


# ═══════════════════════════════════════════════════════════════════════
# Instance: empty_roster_and_branding_denominator_boundaries
# ═══════════════════════════════════════════════════════════════════════

def _empty_roster_provider():
    """Provider A APPROVED holding an ACTIVE title over A1 with no non-temporary
    drivers or vehicles; one temporary CLASS_C UNQUALIFIED driver is rostered."""
    from test_helpers import (
        create_area, create_peak_declaration_payload, create_provider,
        create_route_assignment_payload, draft_and_sign_agreement,
        file_and_verify_policy, approve_provider, get_success_data,
    )

    provider = create_provider()
    area = create_area()
    file_and_verify_policy(provider["id"])
    approve_provider(provider["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api_client.get_service_area(area["id"], AM))
    assignment = get_success_data(api_client.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    assignment = get_success_data(api_client.activate_route_assignment(assignment["id"], AM))
    # A temporary asset requires a covering ACTIVE declaration (PRD §2.7/§3.6).
    decl = get_success_data(api_client.create_peak_declaration(
        create_peak_declaration_payload(area["id"]), AM))
    get_success_data(api_client.activate_peak_declaration(decl["id"], AM))
    temp_driver = get_success_data(api_client.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "full_name": "Temp Only", "license_class": "CLASS_C",
        "qualification_status": "UNQUALIFIED", "is_temporary": True}, AM))
    return provider, area, assignment, temp_driver


def test_temporary_driver_excluded_from_reaffirm_failure_count(api):
    """PRD §3.4: "a driver who is unqualified blocks the signature path with
    `ERR_DRIVER_NOT_QUALIFIED` (HTTP 422), and temporary drivers are excluded
    from the roster entirely."
    PRD §3.4: "a reaffirmation that finds failures does *not* block — it proceeds
    and records the failures by writing the count to the title's
    `compliance_failures_count`."

    Design: Difficulty/boundary_precision_check/empty_roster_and_branding_denominator_boundaries
    """
    provider, area, assignment, _temp = _empty_roster_provider()
    reaffirmed = validate_success(api.reaffirm_route_assignment(assignment["id"], AM), 200)
    assert reaffirmed["status"] == "ACTIVE"
    assert reaffirmed["compliance_failures_count"] == 0


def test_empty_active_fleet_reports_zero_branding_percentage(api):
    """PRD §3.1: "when that active fleet is empty, records `brand_compliance_pct`
    as exactly 0.00."
    PRD §3.6: "temporary assets are excluded from every one of the fleet, roster
    and capacity denominators described in §2.6"

    Design: Difficulty/boundary_precision_check/empty_roster_and_branding_denominator_boundaries
    """
    provider, area, assignment, _temp = _empty_roster_provider()
    provider_now = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert provider_now["brand_compliance_pct"] == 0.00
    assert provider_now["brand_compliance_pct"] is not None

# ═══════════════════════════════════════════════════════════════════════
# Instance: release_chargeback_offset_conservation
# ═══════════════════════════════════════════════════════════════════════

def _reconciled_week_with_two_claims():
    """A RECONCILED week W1 carrying two approved CHARGEBACK segments whose
    recovery rates are zero, so each net amount equals its asserted amount."""
    ctx = setup_reconciled_week(
        deductions=[{"deduction_type": "MAINTENANCE", "amount_cents": 15000,
                     "performance_factor_eligible": True},
                    {"deduction_type": "FUEL", "amount_cents": 3000,
                     "performance_factor_eligible": False}])
    for amount in (50000, 25000):
        claim = get_success_data(api_client.create_chargeback_claim({
            "provider_id": ctx["provider"]["id"],
            "settlement_period_id": ctx["period"]["id"],
            "claim_type": "DAMAGE", "amount_cents": amount,
            "recovery_rate_pct": 0}, AM))
        validate_success(api_client.approve_chargeback_claim(claim["id"], AM), 200)
    return ctx


def test_chargeback_outstanding_equals_the_unoffset_deductions(api):
    """PRD §2.4: "the provider's `chargeback_outstanding_cents` must equal the
    sum of the `amount_cents` of every `CHARGEBACK` deduction on that provider's
    `RECONCILED` and `RELEASED` weeks that has not yet been offset."
    PRD §3.10: "its `amount_cents` set to the claim's `net_of_recovery_cents`"

    Design: Difficulty/compensating_invariant/release_chargeback_offset_conservation
    """
    ctx = _reconciled_week_with_two_claims()
    provider_after = validate_success(api.get_service_provider(ctx["provider"]["id"], SA), 200)
    assert provider_after["chargeback_outstanding_cents"] == 75000


def test_release_offsets_outstanding_and_adds_only_the_net_amount(api):
    """PRD §3.11: "Every `CHARGEBACK` deduction on the week reduces the
    provider's `chargeback_outstanding_cents` by its `amount_cents`, retiring the
    balance that was raised at claim approval in §3.10"
    PRD §3.11: "The week's `net_amount_cents` is added to the provider's
    `lifetime_paid_cents`"

    Design: Difficulty/compensating_invariant/release_chargeback_offset_conservation
    """
    ctx = _reconciled_week_with_two_claims()
    provider, period = ctx["provider"], ctx["period"]
    before = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert before["chargeback_outstanding_cents"] == 75000

    released = validate_success(api.release_period(period["id"], AM), 200)

    after = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert after["chargeback_outstanding_cents"] == 0
    assert after["lifetime_paid_cents"] == before["lifetime_paid_cents"] + released["net_amount_cents"]

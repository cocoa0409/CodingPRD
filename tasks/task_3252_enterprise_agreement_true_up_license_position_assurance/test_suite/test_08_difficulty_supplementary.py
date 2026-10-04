"""Supplementary coverage for difficulty-design instances (second test each)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_true_up_line,
    create_entitlement,
    create_product,
    create_true_up_report,
    create_user_deployment,
    get_success_data,
    make_customer_admin_headers,
    set_clock,
    setup_active_agreement_with_anniversary,
    setup_report_in_state,
    setup_settled_report_with_ratified_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]


def test_settle_benefit_accrual_tier_boundaries(api):
    """PRD §3.7: "Below five hundred thousand dollars of settled total, no training vouchers and no support incidents accrue. At five hundred thousand dollars or more but below two million dollars, the agreement accrues 5 training-voucher units and 1 support incident."
    PRD §3.7: "Tier boundaries are inclusive on the lower side — exactly five hundred thousand dollars enters the first tier."

    Design: Difficulty/transitive_cascade/settle_cascade_entitlement_baseline_anniversary_closure_benefit_accrual
    """
    # growth 1 at 100000 cents full-year => 100000 cents, below the 50000000-cent tier.
    ctx = setup_report_in_state("SETTLED", deployment_users=6, entitlement_qty=5,
                                months_growth=1, pricing_variant="FULL_YEAR_RETROACTIVE")
    grants, _ = validate_paginated(
        api.list_benefit_grants_of_agreement(ctx["agreement"]["id"], LS))
    assert grants == [], "a settled total below five hundred thousand dollars accrues nothing"


def test_submit_blocked_when_agreement_in_renewal_pending(api):
    """PRD §3.5: "Submitting the report moves it `DRAFT → SUBMITTED` and is performed by the `CustomerAdmin`; a report with zero lines is rejected with `ERR_REPORT_EMPTY` (HTTP 422), and the owning agreement must be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_agreement_active
    """
    # DRAFT report built under an ACTIVE agreement, then the agreement leaves ACTIVE.
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="XR2")
    create_entitlement(agr["id"], prod["id"], 1)
    create_user_deployment(agr["id"], org["id"], prod["id"], 2)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=1)
    set_clock("2029-07-01T00:00:00Z")
    resp = api.open_renewal_review(agr["id"], LS)
    assert resp.status_code == 200, get_success_data(resp)
    resp = api.submit_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)


def test_step_up_rejected_path_moves_no_quantity(api):
    """PRD §3.9: "A conversion may instead be declined, moving it `REQUESTED → REJECTED` with no quantity movement; `COMPLETED` and `REJECTED` are terminal."

    Design: Difficulty/compensating_invariant/step_up_conserves_total_license_quantity
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    p_std = create_product(sku="SUR1", edition="STANDARD", family="OFFICE",
                           annual_unit_price_cents=100000)
    p_ent = create_product(sku="SUR2", edition="ENTERPRISE", family="OFFICE",
                           annual_unit_price_cents=200000)
    ent = create_entitlement(agr["id"], p_std["id"], 10)
    resp = api.create_step_up(ent["id"], {"target_product_id": p_ent["id"], "quantity": 4}, LS)
    conv = validate_success(resp, 201)
    resp = api.reject_step_up(conv["id"], LS)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    src_after = get_success_data(api.get_entitlement(ent["id"], LS))
    assert src_after["quantity"] == 10, "declined conversion moves no licenses"
    ents, _ = validate_paginated(api.list_entitlements_of_agreement(agr["id"], LS))
    assert all(e["product_id"] != p_ent["id"] for e in ents), "no target entitlement created"


def test_per_line_rounding_order_sum_never_reverse(api):
    """PRD §2.6: "in retroactive true-up pricing, each line is rounded half-up to whole cents individually and only then summed into the report's `total_amount_cents`; the report total is never computed by summing unrounded line amounts and rounding once."

    Design: Difficulty/combinatorial_formula/true_up_per_line_rounding_order
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    p1 = create_product(sku="R3", name="Round Three", annual_unit_price_cents=100001)
    p2 = create_product(sku="R4", name="Round Four", annual_unit_price_cents=100001)
    create_user_deployment(agr["id"], org["id"], p1["id"], 1)
    create_user_deployment(agr["id"], org["id"], p2["id"], 1)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    add_true_up_line(rep["id"], org["id"], p1["id"], months_growth=7,
                     pricing_variant="ANNIVERSARY_PRORATION")
    add_true_up_line(rep["id"], org["id"], p2["id"], months_growth=7,
                     pricing_variant="ANNIVERSARY_PRORATION")
    rep_after = get_success_data(api.get_true_up_report(rep["id"], LS))
    # per-line rounding: 50001 + 50001 = 100002; sum-then-round would give 100001.
    assert rep_after["total_amount_cents"] == 100002
    assert rep_after["total_amount_cents"] != 100001


def test_benefit_depletion_partial_then_exact_zero(api):
    """PRD §2.10: "a benefit grant moves itself from `ACTIVE` to `DEPLETED` the moment a redemption takes its `quantity_remaining` to exactly zero".

    Design: Difficulty/boundary_precision_check/benefit_depletion_zero_remaining_boundary
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    from test_helpers import create_benefit_grant
    grant = create_benefit_grant(agr["id"], benefit_type="TRAINING_VOUCHER",
                                 quantity_granted=3, expires_on="2028-01-01")
    for q, expected_status, expected_remaining in ((1, "ACTIVE", 2), (2, "DEPLETED", 0)):
        resp = api.redeem_benefit(grant["id"], {"quantity": q},
                                  make_customer_admin_headers(org["id"]))
        assert resp.status_code == 201, get_success_data(resp)
        g = get_success_data(api.get_benefit_grant(grant["id"], LS))
        assert g["status"] == expected_status
        assert g["quantity_remaining"] == expected_remaining


def test_state_temporal_conflict_on_forfeited_grant(api):
    """PRD §2.9: "Requests are validated in a fixed priority order so that the error a caller receives is deterministic when several rules are violated at once."
    PRD §3.7: "A grant's terminal states are `DEPLETED`, `EXPIRED`, and `FORFEITED`; a grant in any terminal state rejects further redemptions with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_temporal_benefit_redemption
    """
    # FORFEITED via agreement expiry, grant also past expiry afterwards: state error wins.
    ctx = setup_active_agreement_with_anniversary(
        with_anniversary=False,
        agreement_overrides={"end_date": "2026-09-30"})
    org, agr = ctx["org"], ctx["agreement"]
    from test_helpers import create_benefit_grant
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=2, expires_on="2027-01-01")
    set_clock("2026-10-01T00:00:00Z")
    resp = api.expire_agreement(agr["id"], PA)
    assert resp.status_code == 200, get_success_data(resp)
    assert get_success_data(api.get_benefit_grant(grant["id"], LS))["status"] == "FORFEITED"
    set_clock("2027-06-01T00:00:00Z")
    resp = api.redeem_benefit(grant["id"], {"quantity": 1},
                              make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

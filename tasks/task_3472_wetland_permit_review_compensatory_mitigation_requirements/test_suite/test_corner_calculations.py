"""Corner queue — calculation results (PRD §3.6, §3.7, §3.9).

Ratio-table extremes, the ATF multiplier inside the provisional variant,
exact in-lieu fee payment, the penalty cap, ATF closure without the
good-faith offset, the left-closed pricing tier boundary, and the generated
monitoring schedule shape.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CaseStatus,
    PlanStatus,
    ReportStatus,
    assert_credit_requirement,
    assert_iso_instants_equal,
    assert_monitoring_schedule_shape,
    create_plan,
    impact_line,
    iso_add_days,
    make_applicant_headers,
    pay_ilf_fee,
    pay_in_lieu_fee_payload,
    purchase_credits,
    reserve_and_purchase,
    reserve_credits,
    review_plan,
    set_clock,
    setup_aa_accepted,
    setup_atf_application_linked,
    setup_case_confirmed,
    setup_issued_atf_permit,
    setup_issued_permit,
    setup_operational_bank,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    walk_application_to_alternatives_review,
)


def test_corner_ratio_flat_stream_credits(api):
    """PRD §3.6: "For each impact line of the application, keyed by resource
    type, the base ratio is 2.0 credits per acre for `EMERGENT_MARSH`, 3.0
    for `FORESTED_WETLAND`, 1.5 for `OPEN_WATER`, and 1.0 for `STREAM`."

    4.0 STREAM acres at the flat 1.0 ratio yields exactly {STREAM: 4.00}
    provisional credits.

    Design: Corner/calculations/corner_ratio_flat_stream_credits
    """
    ctx = setup_aa_accepted(
        site_overrides={"resource_types_present": ["STREAM"]},
        app_overrides={
            "impacts": [impact_line("STREAM", 4.0)],
            "project_purpose": "Culvert replacement",
            "estimated_cost_dollars": 300000.0,
        },
    )
    plan = create_plan(ctx["app"], ctx["applicant"])
    assert_credit_requirement(plan, {"STREAM": 4.00})


def test_corner_atf_multiplier_in_plan_credits(api):
    """PRD §3.6: "The provisional requirement multiplies the line's
    `impact_acres` by its base ratio, then by a location multiplier and a lag
    multiplier both fixed at 1.0 at creation — no bank has been chosen and no
    lag has elapsed — and finally by the after-the-fact multiplier, 1.5 when
    `is_after_the_fact` is true and 1.0 otherwise; each per-type result is
    rounded half-up to two decimal places and stored in
    `required_credits_by_type`."

    2.0 FORESTED_WETLAND acres on the ATF_INDIVIDUAL pathway:
    2.0 * 3.0 * 1.5 = {FORESTED_WETLAND: 9.00}, not 6.00.

    Design: Corner/calculations/corner_atf_multiplier_in_plan_credits
    """
    ctx = setup_atf_application_linked()
    applicant = ctx["applicant"]
    app = walk_application_to_alternatives_review(ctx["app"], applicant)
    assert app["is_after_the_fact"] is True
    ctx["app"] = app
    ctx = setup_aa_accepted(ctx)

    plan = create_plan(ctx["app"], applicant)
    assert_credit_requirement(plan, {"FORESTED_WETLAND": 9.00})


def test_corner_ilf_wrong_amount_rejected(api):
    """PRD §3.6: "For `IN_LIEU_FEE`, securing instead happens by paying the
    fee: the supplied `amount_dollars` must equal `ilf_fee_due_dollars`
    exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), whereupon
    `ilf_fee_paid_dollars` records the amount paid."

    One cent short of the 330000.00 fee is rejected; the exact amount secures
    the plan.

    Design: Corner/calculations/corner_ilf_wrong_amount_rejected
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant, mechanism="IN_LIEU_FEE")
    assert plan["ilf_fee_due_dollars"] == pytest.approx(330000.00, abs=0.005)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)

    resp = api.pay_in_lieu_fee(
        plan["id"], pay_in_lieu_fee_payload(329999.99),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    paid = pay_ilf_fee(plan, applicant, 330000.00)
    assert paid["status"] == PlanStatus.CREDITS_SECURED.value
    assert paid["ilf_fee_paid_dollars"] == pytest.approx(330000.00, abs=0.005)


def test_corner_penalty_cap_applies(api, officer_confirmer_headers):
    """PRD §3.9: "From that instant, `penalty_accrued_dollars` accrues at
    250.0 dollars per unauthorized acre per day — the whole days elapsed from
    `confirmed_date` to the current logical clock, computed as the floor of
    the difference in seconds divided by 86400 — capped at 500000.0 dollars,
    so the accrual is the smaller of the running product and the cap."

    2.0 acres at 250.0/day over 3000 days would accrue 1500000.00 raw; the
    read clamps to the 500000.00 cap.

    Design: Corner/calculations/corner_penalty_cap_applies
    """
    _, _, case = setup_case_confirmed(2.0)
    set_clock(iso_add_days(case["confirmed_date"], 3000))
    case = validate_success(api.get_enforcement_case(case["id"], officer_confirmer_headers))
    assert case["penalty_accrued_dollars"] == pytest.approx(500000.00, abs=0.005), (
        f"cap binds: expected 500000.00, got {case['penalty_accrued_dollars']}"
    )


def test_corner_atf_closure_fixes_full_penalty(api):
    """PRD §3.7: "Finally, for an after-the-fact application, issuance closes
    the enforcement loop: the linked case moves `RESOLUTION_PENDING` to
    `CLOSED`, and `penalty_final_dollars` is fixed at the full
    `penalty_accrued_dollars` evaluated at this clock — the after-the-fact
    track carries no good-faith offset."

    Confirmed at the 2026-09-01 startup clock, issued at 2026-10-02:
    31 days * 2.0 acres * 250.0 = 15500.00 fixed in full at closure.

    Design: Corner/calculations/corner_atf_closure_fixes_full_penalty
    """
    ctx = setup_issued_atf_permit()
    assert ctx["app"]["status"] == "ISSUED"
    case = ctx["case"]
    assert case["case_status"] == CaseStatus.CLOSED.value
    assert case["penalty_final_dollars"] == pytest.approx(15500.00, abs=0.005), (
        "no 0.5 offset on the ATF track: "
        f"expected 15500.00, got {case['penalty_final_dollars']}"
    )


def test_corner_pricing_tier_boundary_exact_half(api):
    """PRD §3.6: "The price tier is read from the bank's depletion before
    this purchase: take the bank's `credits_purchased_by_type` for the
    resource type — only `PURCHASED` transactions count; reservations hold
    inventory but do not move the tier — divide by the type's
    `credit_capacity` (treated as fraction zero when capacity is zero), and
    apply a multiplier of 1.0 when that sold fraction is less than 0.5, 1.15
    when it is at least 0.5 but less than 0.8, and 1.30 when it is at least
    0.8."

    Capacity 20 at base 30000: the purchase that reaches exactly 0.5
    depletion itself paid tier 1.0 (10.0 credits, 300000.00); the next
    purchase at pre-fraction exactly 0.5 pays the 1.15 tier (1.0 credit,
    34500.00) — the boundary is left-closed.

    Design: Corner/calculations/corner_pricing_tier_boundary_exact_half
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()

    txn1 = reserve_and_purchase(bank, plan, applicant, credits=10.0)
    assert txn1["total_price_dollars"] == pytest.approx(300000.00, abs=0.005), (
        "pre-fraction 0.0 -> tier 1.0 even though this purchase reaches "
        "exactly 0.5 depletion"
    )

    txn2 = reserve_credits(bank, plan, applicant, credits=1.0)
    txn2 = purchase_credits(txn2, applicant)
    assert txn2["price_per_credit_dollars"] == pytest.approx(34500.00, abs=0.005)
    assert txn2["total_price_dollars"] == pytest.approx(34500.00, abs=0.005), (
        "pre-fraction exactly 0.5 -> tier 1.15 (left-closed boundary)"
    )


def test_corner_monitoring_schedule_shape(api, reviewer_headers):
    """PRD §3.7: "Issuance also activates the mitigation: the application's
    `CREDITS_SECURED` plan transitions to `ACTIVE`, and when the application
    has such a plan, exactly five monitoring reports are generated for the
    new permit and plan — `period_index` running 1 through 5, each report's
    `due_date` set at the permit's `issue_date` plus 365 days times its
    period index, each opening in `DUE`."
    PRD §2.3: "The monitoring report list is the one pinned exception: its
    results are sorted by `period_index` ascending."

    Issued at 2026-10-02: due dates 2027-10-02, 2028-10-01, ..., 2031-10-01.

    Design: Corner/calculations/corner_monitoring_schedule_shape
    """
    ctx = setup_issued_permit()
    permit = ctx["permit"]
    reports = ctx["reports"]
    assert_monitoring_schedule_shape(reports, permit["issue_date"])

    data, meta = validate_paginated(
        api.list_monitoring_reports(
            reviewer_headers, params={"permit_id": permit["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 5
    assert [r["period_index"] for r in data] == [1, 2, 3, 4, 5]
    assert data[0]["status"] == ReportStatus.DUE.value
    assert_iso_instants_equal(data[0]["due_date"], "2027-10-02T00:00:00Z",
                              label="report 1 due_date")
    assert_iso_instants_equal(data[1]["due_date"], "2028-10-01T00:00:00Z",
                              label="report 2 due_date")
    assert_iso_instants_equal(data[4]["due_date"], "2031-10-01T00:00:00Z",
                              label="report 5 due_date")

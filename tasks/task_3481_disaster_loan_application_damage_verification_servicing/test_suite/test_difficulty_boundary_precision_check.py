"""Difficulty queue: boundary_precision_check — exact threshold boundaries."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    application_decision_payload,
    credit_review_payload,
    setup_application_in_decision_pending,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def test_collateral_threshold_exact_vs_plus_one_cent(api):
    """PRD §3.6: "When the computed `approved_amount_cents` is strictly greater than the collateral threshold for the loan's purpose — 2500000 cents for `PHYSICAL_DAMAGE`, 5000000 cents for `ECONOMIC_INJURY` — the loan requires collateral, recorded as `collateral_required` true, and the approval payload must include a free-text `collateral_description` and a `collateral_value_cents` at least equal to `approved_amount_cents`; a missing field or a shortfall is rejected with `ERR_COLLATERAL_REQUIRED` (HTTP 422)."
    PRD §3.6: "At or below the threshold, `collateral_required` is false and the collateral fields are absent."

    Design: Difficulty/boundary_precision_check/collateral_threshold_exact_vs_plus_one_cent
    """
    # Application 1: approved amount lands exactly on the 2500000 threshold
    # (min of requested 2500000, homeowner cap 50000000, net loss 2500000,
    # affordability — all slack except the exact tie).
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=2500000,
        assessed_loss_cents=2500000,
        insurance_proceeds_cents=0,
    )
    app1_id = ctx["application"]["id"]

    # Application 2: one cent above, on the same declaration.
    ctx = setup_application_in_decision_pending(
        _ctx=ctx,
        requested_amount_cents=2500001,
        assessed_loss_cents=2500001,
        insurance_proceeds_cents=0,
    )
    app2_id = ctx["application"]["id"]

    # Exactly at the threshold: 2500000 is NOT > 2500000, so the approval
    # succeeds with no collateral fields supplied.
    resp = api.decide_application(
        app1_id, application_decision_payload(decision="APPROVED"),
        ctx["approver_headers"])
    decided = validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_application"])
    loan = validate_success(
        api.get_loan(decided["loan_id"], ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["get_loan"])
    assert loan["approved_amount_cents"] == 2500000
    assert loan["collateral_required"] is False

    # One cent above: 2500001 > 2500000, so the identical payload is rejected.
    resp = api.decide_application(
        app2_id, application_decision_payload(decision="APPROVED"),
        ctx["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_REQUIRED)
    app2 = validate_success(api.get_application(app2_id, ctx["approver_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_application"])
    assert app2["status"] == "DECISION_PENDING"
    assert app2["loan_id"] is None


def test_credit_score_640_passes_639_declines(api):
    """PRD §3.3: "Second, `score_pass` is true exactly when the `credit_score` is at least 640."
    PRD §3.3: "A `PASS` on a `PHYSICAL_DAMAGE` application moves it to `VERIFICATION`, where it awaits damage verification."
    PRD §3.3: "A `FAIL` moves the application to `DECLINED`, writing `decline_reason` `CREDIT_FAIL` when `score_pass` was false and `DTI_EXCEEDED` otherwise."
    PRD §2.8: "A `BUSINESS` borrowing for `PHYSICAL_DAMAGE` pays an annual rate of 0.04 over 360 months."

    Design: Difficulty/boundary_precision_check/credit_score_640_passes_639_declines
    """
    # Two BUSINESS applicants, identical SUBMITTED physical applications for
    # 1500000; DTI slack on both: (100000 + 7161) * 100 <= 43 * 500000.
    ctx = setup_submitted_application(
        applicant_type="BUSINESS",
        annual_income_cents=6000000,
        monthly_debt_cents=100000,
        requested_amount_cents=1500000,
    )
    app1_id = ctx["application"]["id"]
    ctx = setup_submitted_application(
        _ctx=ctx,
        applicant_type="BUSINESS",
        annual_income_cents=6000000,
        monthly_debt_cents=100000,
        requested_amount_cents=1500000,
    )
    app2_id = ctx["application"]["id"]

    # STANDARD payment on 1500000 at (0.04/12) over 360 months = 7161
    # (round-half-up) — identical on both reviews; only the score differs.
    resp = api.create_credit_review(
        app1_id,
        credit_review_payload(credit_score=640,
                              verified_monthly_debt_cents=100000),
        ctx["officer_headers"])
    review640 = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    assert review640["proposed_payment_cents"] == 7161
    assert review640["dti_pass"] is True
    assert review640["score_pass"] is True
    assert review640["verdict"] == "PASS"

    resp = api.create_credit_review(
        app2_id,
        credit_review_payload(credit_score=639,
                              verified_monthly_debt_cents=100000),
        ctx["officer_headers"])
    review639 = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    assert review639["proposed_payment_cents"] == 7161
    assert review639["dti_pass"] is True
    assert review639["score_pass"] is False
    assert review639["verdict"] == "FAIL"

    # One point flips the transition.
    app1 = validate_success(api.get_application(app1_id, ctx["officer_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_application"])
    assert app1["status"] == "VERIFICATION"
    app2 = validate_success(api.get_application(app2_id, ctx["officer_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_application"])
    assert app2["status"] == "DECLINED"
    assert app2["decline_reason"] == "CREDIT_FAIL"

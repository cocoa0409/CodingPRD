"""Difficulty queue: dual_variant_calc — two formula variants over one domain."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    application_decision_payload,
    complete_verification_payload,
    create_verification_payload,
    credit_review_payload,
    decide_application,
    open_verification,
    setup_application_in_verification,
    setup_submitted_application,
    validate_success,
)


def test_verified_loss_diverges_between_replacement_cost_and_actual_cash_value(api):
    """PRD §3.4: "The system then computes `verified_loss_cents`: under `REPLACEMENT_COST` it equals `assessed_loss_cents`; under `ACTUAL_CASH_VALUE` it is the assessed loss multiplied by the quantity (1 minus `depreciation_pct`), multiplied in exact decimal and rounded half-up to integer cents — so the same assessed loss yields a strictly smaller verified loss whenever depreciation is positive."
    PRD §3.4: "The `net_verified_loss_cents` is then the verified loss minus `insurance_proceeds_cents`, floored at zero; this is the duplication-of-benefits deduction."
    PRD §3.4: "The first completion cascades: the linked application advances from `VERIFICATION` to `DECISION_PENDING` and its `version` increments."

    Design: Difficulty/dual_variant_calc/valuation_basis_rcv_vs_acv_divergence
    """
    # Setup: two BUSINESS applicants, each with a SUBMITTED physical application
    # (requested 30000000) credit-passed into VERIFICATION.
    ctx = setup_application_in_verification(
        applicant_type="BUSINESS",
        annual_income_cents=120000000,
        monthly_debt_cents=100000,
        requested_amount_cents=30000000,
    )
    app1_id = ctx["application"]["id"]
    v1 = open_verification(ctx, method="INSPECTION",
                           valuation_basis="REPLACEMENT_COST")

    ctx = setup_application_in_verification(
        _ctx=ctx,
        applicant_type="BUSINESS",
        annual_income_cents=120000000,
        monthly_debt_cents=100000,
        requested_amount_cents=30000000,
    )
    app2_id = ctx["application"]["id"]
    v2 = open_verification(ctx, method="INSPECTION",
                           valuation_basis="ACTUAL_CASH_VALUE",
                           depreciation_pct=0.20)

    # Trigger: complete both with identical assessed loss and zero insurance.
    resp1 = api.complete_damage_verification(
        v1["id"],
        complete_verification_payload(assessed_loss_cents=30000000,
                                      insurance_proceeds_cents=0),
        ctx["verifier_headers"])
    done1 = validate_success(
        resp1, EXPECTED_SUCCESS_STATUS["complete_damage_verification"])
    resp2 = api.complete_damage_verification(
        v2["id"],
        complete_verification_payload(assessed_loss_cents=30000000,
                                      insurance_proceeds_cents=0),
        ctx["verifier_headers"])
    done2 = validate_success(
        resp2, EXPECTED_SUCCESS_STATUS["complete_damage_verification"])

    # REPLACEMENT_COST passes the assessed loss through unmodified.
    assert done1["verified_loss_cents"] == 30000000
    # ACTUAL_CASH_VALUE: round_half_up(30000000 * (1 - 0.20)) = 24000000.
    assert done2["verified_loss_cents"] == 24000000
    # Identical inputs, only the basis differs: divergence is exactly 6000000.
    assert done1["verified_loss_cents"] - done2["verified_loss_cents"] == 6000000
    # Zero insurance proceeds: net equals verified on both.
    assert done1["net_verified_loss_cents"] == 30000000
    assert done2["net_verified_loss_cents"] == 24000000

    # First completion cascades each application to DECISION_PENDING.
    app1 = validate_success(api.get_application(app1_id, ctx["officer_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_application"])
    app2 = validate_success(api.get_application(app2_id, ctx["officer_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_application"])
    assert app1["status"] == "DECISION_PENDING"
    assert app2["status"] == "DECISION_PENDING"


def test_monthly_payment_standard_vs_deferred_capitalized(api):
    """PRD §3.3: "First, `proposed_payment_cents` is the standard amortized monthly payment on the `requested_amount_cents`, using the rate and term implied by the applicant's type crossed with the loan purpose per Section 2.8: the monthly rate is the annual rate divided by 12 in exact decimal, and the payment is the principal times the monthly rate times the quantity (1 plus the monthly rate) raised to the number of months in the term, divided by the quantity (1 plus the monthly rate) raised to the term minus one, computed in exact decimal and rounded half-up to integer cents at the final step only."
    PRD §3.6: "The loan's scheduled `monthly_payment_cents` uses the deferred-capitalized variant of the payment formula: interest accrues simply over the 12 deferral months at the monthly rate and is capitalized into principal — the principal is multiplied by the quantity (1 plus the monthly rate times 12) — and that enlarged principal is then amortized over the term with the standard formula, rounding half-up to integer cents at the final step."
    PRD §2.8: "A `HOMEOWNER` borrowing for `PHYSICAL_DAMAGE` pays an annual `interest_rate` of 0.03125 over a `term_months` of 360."
    PRD §3.6: "When the computed `approved_amount_cents` is strictly greater than the collateral threshold for the loan's purpose — 2500000 cents for `PHYSICAL_DAMAGE`, 5000000 cents for `ECONOMIC_INJURY` — the loan requires collateral, recorded as `collateral_required` true, and the approval payload must include a free-text `collateral_description` and a `collateral_value_cents` at least equal to `approved_amount_cents`; a missing field or a shortfall is rejected with `ERR_COLLATERAL_REQUIRED` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/monthly_payment_standard_vs_deferred_capitalized
    """
    ctx = setup_submitted_application(
        applicant_type="HOMEOWNER",
        annual_income_cents=12000000,
        monthly_debt_cents=100000,
        requested_amount_cents=20000000,
    )
    app_id = ctx["application"]["id"]

    # Trigger step 1: credit review computes the STANDARD variant on the full
    # requested 20000000 at monthly rate 0.03125/12 over 360 months:
    # pay = 20000000 * r * (1+r)^360 / ((1+r)^360 - 1) = 85675 (round-half-up).
    resp = api.create_credit_review(
        app_id,
        credit_review_payload(credit_score=700,
                              verified_monthly_debt_cents=100000),
        ctx["officer_headers"])
    review = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    assert review["proposed_payment_cents"] == 85675

    # Trigger step 2: verification (net loss 25000000 - 5000000 = 20000000).
    resp = api.create_damage_verification(
        app_id,
        create_verification_payload(method="INSPECTION",
                                    valuation_basis="REPLACEMENT_COST"),
        ctx["verifier_headers"])
    verification = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_damage_verification"])
    resp = api.complete_damage_verification(
        verification["id"],
        complete_verification_payload(assessed_loss_cents=25000000,
                                      insurance_proceeds_cents=5000000),
        ctx["verifier_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["complete_damage_verification"])

    # Trigger step 3: approval originates the loan.
    resp = api.decide_application(
        app_id,
        application_decision_payload(
            decision="APPROVED",
            collateral_description="primary residence",
            collateral_value_cents=30000000),
        ctx["approver_headers"])
    decided = validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_application"])
    loan_id = decided["loan_id"]
    assert loan_id is not None

    loan = validate_success(api.get_loan(loan_id, ctx["servicing_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_loan"])
    # DEFERRED_CAPITALIZED: principal grossed to 20000000 * (1 + 0.03125/12 * 12)
    # = 20625000, then amortized over 360 -> 88352; delta 88352 - 85675 = 2677.
    assert loan["monthly_payment_cents"] == 88352
    assert loan["monthly_payment_cents"] - review["proposed_payment_cents"] == 2677
    # approved = min(requested 20000000, homeowner cap 50000000,
    #                net loss 20000000, affordability cap) = 20000000.
    assert loan["approved_amount_cents"] == 20000000
    # 20000000 > 2500000 threshold -> collateral required.
    assert loan["collateral_required"] is True
    assert loan["interest_rate"] == 0.03125
    assert loan["term_months"] == 360

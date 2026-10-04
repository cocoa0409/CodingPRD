"""Difficulty queue: combinatorial_formula — multi-term formulas, pinned order."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    application_decision_payload,
    apply_settlement_payload,
    list_receivable_data,
    list_tranche_data,
    loan_version,
    read_loan,
    report_grant,
    report_settlement,
    set_clock,
    setup_application_in_decision_pending,
    setup_loan_with_t1_released,
    validate_success,
)


def test_approved_amount_net_loss_minus_grants_binds(api):
    """PRD §3.6: "Step two bounds the amount by the loss: for `PHYSICAL_DAMAGE` this bound is the `net_verified_loss_cents` of the latest completed verification minus the sum of `award_amount_cents` over all grants on the application with `purpose_category` `PHYSICAL_DAMAGE`, floored at zero; for `ECONOMIC_INJURY` the loss bound is omitted entirely."
    PRD §3.6: "Step four sets `approved_amount_cents` to the smallest of the requested amount, the statutory cap, the loss bound, and the affordability cap — for `ECONOMIC_INJURY`, the minimum is taken over the requested amount, the cap, and the affordability cap only."
    PRD §2.8: "A `RENTER` borrowing for `PHYSICAL_DAMAGE` pays an annual rate of 0.03125 over 84 months."
    PRD §3.6: "Hop one creates the `Loan` in `PENDING_ACCEPTANCE` lifecycle status with `servicing_status` `CURRENT`: `application_id` and a denormalized `applicant_id` tie it to the file, `loan_purpose` is copied from the application, `interest_rate` and `term_months` follow Section 2.8, `deferral_months` is 12, and `commitment_amount_cents` starts equal to `approved_amount_cents`."

    Design: Difficulty/combinatorial_formula/approved_amount_net_loss_minus_grants_binds
    """
    # Setup: RENTER physical application, requested 9000000, credit PASS,
    # verification COMPLETED at assessed 9000000 / insurance 0 (net 9000000).
    ctx = setup_application_in_decision_pending(
        applicant_type="RENTER",
        annual_income_cents=20000000,
        monthly_debt_cents=0,
        requested_amount_cents=9000000,
        credit_score=700,
        verified_monthly_debt_cents=0,
        assessed_loss_cents=9000000,
        insurance_proceeds_cents=0,
    )
    # STANDARD payment on 9000000 at (0.03125/12) over 84 months = 119427
    # (round-half-up); debt 0 keeps DTI slack, so affordability never binds.
    assert ctx["credit_review"]["proposed_payment_cents"] == 119427

    # Setup: 1000000 PHYSICAL_DAMAGE grant reported before the decision
    # (DOB ceiling: 1000000 <= verified loss 9000000, allowed).
    report_grant(ctx, 1000000)

    # Trigger: approve; the loss bound 9000000 - 1000000 = 8000000 binds the
    # min (requested 9000000 and RENTER cap 10000000 stay slack).
    resp = api.decide_application(
        ctx["application"]["id"],
        application_decision_payload(
            decision="APPROVED",
            collateral_description="renter contents rider",
            collateral_value_cents=10000000),
        ctx["approver_headers"])
    decided = validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_application"])
    loan_id = decided["loan_id"]

    loan = validate_success(api.get_loan(loan_id, ctx["servicing_headers"]),
                            EXPECTED_SUCCESS_STATUS["get_loan"])
    assert loan["approved_amount_cents"] == 8000000
    assert loan["interest_rate"] == 0.03125
    assert loan["term_months"] == 84
    # 8000000 > 2500000 -> collateral required; commitment starts at approved.
    assert loan["collateral_required"] is True
    assert loan["commitment_amount_cents"] == 8000000


def test_clawback_evaluation_order_pinned_steps(api):
    """PRD §3.8: "The apply runs the clawback computation in this exact, pinned order."
    PRD §3.8: "First, total insurance is summed: the `insurance_proceeds_cents` of the latest completed verification (zero if none), plus every applied settlement's `settlement_amount_cents`, plus this settlement's amount."
    PRD §3.8: "Second, the new net loss is the `verified_loss_cents` minus that total, floored at zero."
    PRD §3.8: "Third, the new commitment is the smaller of `approved_amount_cents` and the new net loss, and the loan's `commitment_amount_cents` is set to it."
    PRD §3.8: "Fourth, the waterfall walks the un-released tranches in descending `stage_number`: whole tranches are cancelled, largest stage first, while the sum of un-released amounts minus the tranche's amount stays at or above the target — the target being the new commitment minus `disbursed_total_cents`, floored at zero — and the tranche where that test fails is instead reduced so the sum of un-released amounts lands exactly on the target; reduced amounts never go below zero, and cancelled tranches move to `CANCELLED` from either `SCHEDULED` or `ELIGIBLE`."
    PRD §3.8: "Fifth, once the tranche cascade has settled, any excess is computed as `disbursed_total_cents` minus the new commitment, floored at zero."

    Design: Difficulty/combinatorial_formula/clawback_evaluation_order_pinned_steps
    """
    # Setup: homeowner loan approved 20000000 (verified 25000000, insurance
    # 5000000), accepted 2026-11-01; only tranche stage 1 (2500000) RELEASED.
    ctx = setup_loan_with_t1_released()
    settlement = report_settlement(ctx, 12000000)

    # Trigger: apply at 2026-12-15 with the fresh loan version (OCC).
    set_clock("2026-12-15T00:00:00Z", ctx["admin_headers"])
    version = loan_version(ctx)
    resp = api.apply_insurance_settlement(
        settlement["id"],
        apply_settlement_payload(expected_loan_version=version),
        ctx["servicing_headers"])
    applied = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["apply_insurance_settlement"])

    # Steps (1)-(3): total insurance 5000000 + 12000000 = 17000000;
    # new net loss 25000000 - 17000000 = 8000000;
    # new commitment = min(20000000, 8000000) = 8000000; delta 12000000.
    assert applied["status"] == "APPLIED"
    assert applied["clawback_commitment_delta_cents"] == 12000000
    # Step (5): excess = max(0, disbursed 2500000 - commitment 8000000) = 0.
    assert applied["excess_due_cents"] == 0

    loan = read_loan(ctx)
    assert loan["commitment_amount_cents"] == 8000000
    assert loan["disbursed_total_cents"] == 2500000
    assert loan["outstanding_balance_cents"] == 2500000

    # Step (4): descending-stage waterfall over un-released T3 (8750000) and
    # T2 (8750000) toward target max(0, 8000000 - 2500000) = 5500000:
    # T3 cancelled (17500000 - 8750000 = 8750000 >= 5500000), then T2 fails the
    # test (8750000 - 8750000 = 0 < 5500000) and is reduced to exactly 5500000.
    tranches = list_tranche_data(ctx)
    assert tranches[0]["status"] == "RELEASED"
    assert tranches[1]["status"] == "SCHEDULED"
    assert tranches[1]["amount_cents"] == 5500000
    assert tranches[2]["status"] == "CANCELLED"

    # Excess is zero: no ExcessFundsReceivable exists.
    assert list_receivable_data(ctx) == []

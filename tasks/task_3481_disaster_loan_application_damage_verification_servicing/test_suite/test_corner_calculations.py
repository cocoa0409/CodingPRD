"""Corner queue: calculations — disbursement split, interest accrual,
DTI boundary integer arithmetic, duplication-of-benefits ceiling, and
late-fee aging thresholds."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    credit_review_payload,
    decide_application,
    grant_award_payload,
    list_tranche_data,
    read_loan,
    release_stage,
    report_grant,
    set_clock,
    setup_application_in_decision_pending,
    setup_approved_loan,
    setup_loan_with_t1_released,
    setup_submitted_application,
    validate_error,
    validate_success,
    verify_milestone,
)


def test_tranche_schedule_split_and_zero_tranche_omission(api):
    """PRD §3.6: "Hop two spawns the disbursement schedule: tranche stage 1 is the smaller of 2500000 cents and the approved amount, and any remainder is split into stage 2 taking the floor of half the remainder and stage 3 taking the rest; a tranche whose computed amount would be zero is not created. Each tranche is born `SCHEDULED` with its `stage_number` and `amount_cents` fixed."
    PRD §3.6: "At or below the threshold, `collateral_required` is false and the collateral fields are absent."

    Design: Corner/calculations/tranche_schedule_split_and_zero_tranche_omission
    """
    # Loan A: approved 20000000 -> T1 capped at 2500000, remainder 1750000
    # splits into floor(17500000/2) = 8750000 and the rest 8750000.
    ctx = setup_approved_loan(
        requested_amount_cents=20000000,
        assessed_loss_cents=25000000,
        insurance_proceeds_cents=0)
    loan_a_id = ctx["loan"]["id"]

    # Loan B: approved exactly 2500000 -> T1 2500000, remainder zero, so no
    # stage 2/3 rows exist. 2500000 is not > 2500000, so no collateral.
    ctx = setup_application_in_decision_pending(
        _ctx=ctx,
        requested_amount_cents=2500000,
        assessed_loss_cents=2500000,
        insurance_proceeds_cents=0)
    decide_application(ctx, decision="APPROVED", with_collateral=False)
    loan_b_id = ctx["application"]["loan_id"]

    tranches_a = list_tranche_data(ctx, loan_id=loan_a_id)
    assert [t["amount_cents"] for t in tranches_a] == [
        2500000, 8750000, 8750000]
    assert [t["stage_number"] for t in tranches_a] == [1, 2, 3]
    assert all(t["status"] == "SCHEDULED" for t in tranches_a)

    tranches_b = list_tranche_data(ctx, loan_id=loan_b_id)
    assert len(tranches_b) == 1
    assert tranches_b[0]["amount_cents"] == 2500000
    assert tranches_b[0]["status"] == "SCHEDULED"
    loan_b = read_loan(ctx, loan_id=loan_b_id)
    assert loan_b["collateral_required"] is False


def test_interest_accrual_folded_at_second_release(api):
    """PRD §3.7: "On release the tranche's `released_at` is stamped with the current instant, the loan's `disbursed_total_cents` and `outstanding_balance_cents` each increase by the released amount, and the loan's `version` increments. The first release on a loan also sets `last_accrual_date` to the release date and `next_due_date` to the release date advanced by `deferral_months` plus 1 calendar months; each later release first folds the interest accrued since `last_accrual_date` into `accrued_interest_balance_cents` and advances `last_accrual_date`."
    PRD §3.9: "First, the interest due is computed as `accrued_interest_balance_cents` plus the interest accrued since the last accrual: `outstanding_balance_cents` times the annual `interest_rate` times the number of calendar days since `last_accrual_date`, divided by 365, rounded half-up to integer cents — and this accrual rounding happens exactly once, here, before any allocation."

    Design: Corner/calculations/interest_accrual_folded_at_second_release
    """
    ctx = setup_loan_with_t1_released()  # T1 2500000 released 2026-11-01
    verify_milestone(ctx, claimed_cost_cents=2500000)  # flips T2 to ELIGIBLE
    set_clock("2026-12-01T00:00:00Z", ctx["admin_headers"])

    release_stage(ctx, 1)  # release T2 8750000 at 2026-12-01

    loan = ctx["loan"]
    # 30 days (2026-11-01 -> 2026-12-01) on outstanding 2500000 at 0.03125:
    # round_half_up(2500000 * 0.03125 * 30 / 365) = round_half_up(6421.23)
    # = 6421.
    assert loan["accrued_interest_balance_cents"] == 6421
    assert loan["last_accrual_date"].startswith("2026-12-01T00:00:00")
    # outstanding = 2500000 + 8750000.
    assert loan["outstanding_balance_cents"] == 11250000
    # next_due was fixed by the FIRST release (2026-11-01 + 13 months).
    assert loan["next_due_date"].startswith("2027-12-01T00:00:00")


def test_dti_exactly_43_percent_passes_one_cent_over_fails(api):
    """PRD §3.3: "Third, `dti_pass` is true exactly when the sum of `verified_monthly_debt_cents` and `proposed_payment_cents`, multiplied by 100, is less than or equal to 43 times the applicant's `annual_income_cents` divided by 12 and floored to a whole number — that is, a back-end debt-to-income ratio capped at 43 percent of gross monthly income, with the monthly income computed by integer-dividing the annual figure by 12 and discarding the remainder."
    PRD §3.3: "A `FAIL` moves the application to `DECLINED`, writing `decline_reason` `CREDIT_FAIL` when `score_pass` was false and `DTI_EXCEEDED` otherwise."

    Design: Corner/calculations/dti_exactly_43_percent_passes_one_cent_over_fails
    """
    # RENTER physical 1500000 -> STANDARD payment 19905 at 0.03125/84.
    # Monthly income floor(5160000/12) = 430000; 43 * 430000 = 18490000.
    # Debt 164995: (164995 + 19905) * 100 = 18490000 -> exactly 43% -> pass.
    ctx = setup_submitted_application(
        applicant_type="RENTER",
        annual_income_cents=5160000,
        monthly_debt_cents=0,
        requested_amount_cents=1500000)
    app1_id = ctx["application"]["id"]
    ctx = setup_submitted_application(
        _ctx=ctx,
        applicant_type="RENTER",
        annual_income_cents=5160000,
        monthly_debt_cents=0,
        requested_amount_cents=1500000)
    app2_id = ctx["application"]["id"]

    resp = api.create_credit_review(
        app1_id,
        credit_review_payload(credit_score=700,
                              verified_monthly_debt_cents=164995),
        ctx["officer_headers"])
    review_pass = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    assert review_pass["proposed_payment_cents"] == 19905
    assert review_pass["dti_pass"] is True
    assert review_pass["verdict"] == "PASS"

    # One cent more of monthly debt: 184901 * 100 = 18490100 > 18490000.
    resp = api.create_credit_review(
        app2_id,
        credit_review_payload(credit_score=700,
                              verified_monthly_debt_cents=164996),
        ctx["officer_headers"])
    review_fail = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    assert review_fail["proposed_payment_cents"] == 19905
    assert review_fail["dti_pass"] is False
    assert review_fail["verdict"] == "FAIL"

    application = validate_success(
        api.get_application(app2_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DECLINED"
    assert application["decline_reason"] == "DTI_EXCEEDED"


def test_dob_ceiling_equality_allowed_excess_rejected(api):
    """PRD §3.5: "If that assistance total is strictly greater than the `verified_loss_cents` of the latest completed verification (zero if none exists), the grant is rejected with `ERR_DUPLICATION_OF_BENEFITS` (HTTP 422). An assistance total exactly equal to the verified loss is allowed — the rejection boundary is strictly greater."

    Design: Corner/calculations/dob_ceiling_equality_allowed_excess_rejected
    """
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=9000000,
        assessed_loss_cents=9000000,
        insurance_proceeds_cents=0)

    # Assistance total lands exactly on verified_loss 9000000: allowed.
    grant = report_grant(ctx, 9000000)
    assert grant["award_amount_cents"] == 9000000

    # One more cent: 9000001 > 9000000 -> rejected.
    resp = api.create_grant_award(
        ctx["application"]["id"],
        grant_award_payload(program_name="STATE-RELIEF",
                            award_amount_cents=1,
                            purpose_category="PHYSICAL_DAMAGE"),
        ctx["grant_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATION_OF_BENEFITS)

    rows = validate_success(
        api.list_grant_awards(ctx["application"]["id"],
                              ctx["grant_coordinator_headers"]),
        EXPECTED_SUCCESS_STATUS["list_grant_awards"])
    assert [row["id"] for row in rows] == [grant["id"]]


def test_late_fee_assessed_at_15_days_not_14(api):
    """PRD §3.9: "At 15 or more days past due, and provided no late fee has yet been assessed for that due-date cycle, a late fee of 5 percent (0.05) of `monthly_payment_cents`, rounded half-up to integer cents, is added to `late_fee_balance_cents` — at most one fee per due-date cycle."
    PRD §3.9: "Status boundaries are inclusive at every rung: at 30 or more days past due a `CURRENT` loan becomes `DELINQUENT`; at 120 or more a `DELINQUENT` loan becomes `DEFAULT`; at 180 or more a loan in `DEFAULT` is charged off, moving `lifecycle_status` to `CHARGED_OFF`, which is terminal and accepts no further payments (`ERR_LOAN_NOT_ACTIVE`)."

    Design: Corner/calculations/late_fee_assessed_at_15_days_not_14
    """
    ctx = setup_loan_with_t1_released()  # T1 released 2026-11-01
    # DEFERRED_CAPITALIZED payment on 20000000 at 0.03125/360 = 88352.
    assert ctx["loan"]["monthly_payment_cents"] == 88352

    # 2027-12-15 is 14 days past the 2027-12-01 due date: no fee, CURRENT.
    set_clock("2027-12-15T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["days_past_due"] == 14
    assert loan["late_fee_balance_cents"] == 0
    assert loan["servicing_status"] == "CURRENT"

    # 2027-12-16 is 15 days past due: exactly one fee of
    # round_half_up(0.05 * 88352) = round_half_up(4417.6) = 4418; still
    # CURRENT because delinquency starts at 30 days.
    set_clock("2027-12-16T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["days_past_due"] == 15
    assert loan["late_fee_balance_cents"] == 4418
    assert loan["servicing_status"] == "CURRENT"

"""Difficulty queue: compensating_invariant — reversal/void restores the stock."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    apply_settlement_payload,
    list_receivable_data,
    list_tranche_data,
    loan_version,
    payment_payload,
    read_loan,
    release_stage,
    report_settlement,
    set_clock,
    setup_loan_with_t1_released,
    setup_loan_with_t1_t2_released,
    validate_success,
    verify_milestone,
)


def test_payment_reverse_conserve_principal_stock(api):
    """PRD §3.9: "First, the interest due is computed as `accrued_interest_balance_cents` plus the interest accrued since the last accrual: `outstanding_balance_cents` times the annual `interest_rate` times the number of calendar days since `last_accrual_date`, divided by 365, rounded half-up to integer cents — and this accrual rounding happens exactly once, here, before any allocation."
    PRD §3.9: "Second, the payment covers late fees: `fee_portion_cents` is the smaller of the payment amount and `late_fee_balance_cents`."
    PRD §3.9: "Third, `interest_portion_cents` is the smaller of the remainder and the interest due."
    PRD §3.9: "Fourth, `principal_portion_cents` takes whatever remains — the remainder always lands on principal."
    PRD §3.9: "The reversal compensates the allocation exactly: `outstanding_balance_cents` grows back by `principal_portion_cents`, `total_principal_paid_cents` falls by the same, `total_interest_paid_cents` falls by `interest_portion_cents`, `accrued_interest_balance_cents` grows back by the interest portion, `late_fee_balance_cents` grows back by `fee_portion_cents`, and `last_accrual_date` is restored to its pre-payment value."

    Design: Difficulty/compensating_invariant/payment_reverse_conserve_principal_stock
    """
    # Setup: T1 (2500000) and T2 (8750000) both released 2026-11-01;
    # outstanding 11250000, accrued 0, last_accrual_date 2026-11-01.
    ctx = setup_loan_with_t1_t2_released()
    loan_id = ctx["loan"]["id"]
    assert ctx["loan"]["outstanding_balance_cents"] == 11250000

    # Exactly 30 days of accrual elapse.
    set_clock("2026-12-01T00:00:00Z", ctx["admin_headers"])

    # Trigger 1: a 100000-cent payment. Interest due =
    # round_half_up(11250000 * 0.03125 * 30 / 365) = round_half_up(28895.54...)
    # = 28896 (computed once, before allocation); principal takes the rest.
    resp = api.create_payment(loan_id, payment_payload(100000),
                              ctx["applicant_headers"])
    payment = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_payment"])
    assert payment["fee_portion_cents"] == 0
    assert payment["interest_portion_cents"] == 28896
    assert payment["principal_portion_cents"] == 71104
    assert payment["status"] == "POSTED"

    # Conserved principal stock: outstanding + total_principal_paid is
    # invariant at 11250000 across the payment.
    loan = read_loan(ctx)
    assert loan["outstanding_balance_cents"] == 11178896
    assert loan["total_principal_paid_cents"] == 71104
    assert loan["outstanding_balance_cents"] + loan["total_principal_paid_cents"] == 11250000

    # Trigger 2: the compensating reverse restores every touched field.
    resp = api.reverse_payment(payment["id"], ctx["servicing_headers"])
    reversed_payment = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["reverse_payment"])
    assert reversed_payment["status"] == "REVERSED"

    loan = read_loan(ctx)
    assert loan["outstanding_balance_cents"] == 11250000
    assert loan["total_principal_paid_cents"] == 0
    assert loan["total_interest_paid_cents"] == 0
    assert loan["accrued_interest_balance_cents"] == 28896
    assert loan["last_accrual_date"].startswith("2026-11-01T00:00:00")
    assert loan["lifecycle_status"] == "ACTIVE"


def test_settlement_void_restores_commitment_and_schedule(api):
    """PRD §3.8: "An apply can be undone: a `ServicingAgent` voids a settlement that is `APPLIED` (else `ERR_SETTLEMENT_NOT_APPLIED`)."
    PRD §3.8: "The void exactly compensates the apply cascade: `commitment_amount_cents` grows back by `clawback_commitment_delta_cents`, tranche amounts and statuses are restored to their pre-apply values, and when `excess_due_cents` was positive the receivable's `amount_due_cents` is reduced by that amount — a receivable whose `amount_due_cents` thereby falls to its `amount_paid_cents` becomes `PAID`, and one reduced to zero due with zero paid is removed outright."

    Design: Difficulty/compensating_invariant/settlement_void_restores_commitment_and_schedule
    """
    # Setup: T1+T2 released (disbursed 11250000); milestones 9000000 + 3000000
    # VERIFIED so stage 3 (8750000) is ELIGIBLE; settlement of 16000000.
    ctx = setup_loan_with_t1_released()
    verify_milestone(ctx, claimed_cost_cents=9000000)
    release_stage(ctx, 1)
    verify_milestone(ctx, claimed_cost_cents=3000000)
    settlement = report_settlement(ctx, 16000000)

    # Pre-apply snapshot of the conserved commitment stock.
    loan = read_loan(ctx)
    assert loan["commitment_amount_cents"] == 20000000
    tranches_pre = list_tranche_data(ctx)
    assert tranches_pre[2]["status"] == "ELIGIBLE"
    assert tranches_pre[2]["amount_cents"] == 8750000

    # Apply: commitment drops to 4000000, stage 3 cancelled, one receivable
    # of 7250000 OPEN (the apply-side of the compensation pair).
    set_clock("2026-12-15T00:00:00Z", ctx["admin_headers"])
    version = loan_version(ctx)
    resp = api.apply_insurance_settlement(
        settlement["id"],
        apply_settlement_payload(expected_loan_version=version),
        ctx["servicing_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["apply_insurance_settlement"])
    loan = read_loan(ctx)
    assert loan["commitment_amount_cents"] == 4000000
    tranches = list_tranche_data(ctx)
    assert tranches[2]["status"] == "CANCELLED"
    receivables = list_receivable_data(ctx)
    assert len(receivables) == 1
    assert receivables[0]["amount_due_cents"] == 7250000
    assert receivables[0]["status"] == "OPEN"

    # Void: the cascade is compensated exactly — zero drift.
    resp = api.void_insurance_settlement(settlement["id"],
                                         ctx["servicing_headers"])
    voided = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["void_insurance_settlement"])
    assert voided["status"] == "VOIDED"

    loan = read_loan(ctx)
    # 4000000 + clawback_commitment_delta_cents 16000000 = 20000000 restored.
    assert loan["commitment_amount_cents"] == 20000000
    assert loan["disbursed_total_cents"] == 11250000
    tranches = list_tranche_data(ctx)
    assert tranches[2]["status"] == "ELIGIBLE"
    assert tranches[2]["amount_cents"] == 8750000
    # The receivable fell to zero due with zero paid: removed outright.
    assert list_receivable_data(ctx) == []

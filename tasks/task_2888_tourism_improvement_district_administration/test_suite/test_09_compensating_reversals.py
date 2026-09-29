"""Undo operations that must restore the previous state exactly.

Two acts in this system are declared to be exact inverses.  Reversing a
remittance subtracts the four per-bucket amounts that record itself wrote rather
than re-running the waterfall backwards, and withdrawing a petition signature
subtracts exactly that signature's own weight snapshot.  Each test compares the
state after the undo against the state before the act, field by field.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_conserved_collection_identity,
    assert_fields,
    assert_ratio_four_dp,
    assert_waterfall_allocation,
)
from test_helpers.test_users import ADMIN, operator_headers


def _statement(api, statement_id):
    return validate_success(api.get_assessment_statement(statement_id, headers=ADMIN))


# --------------------------------------------------------------------------
# Remittance reversal against the statement and the district ledger
# --------------------------------------------------------------------------
def test_a_reversal_returns_a_fully_paid_statement_to_its_part_paid_state(api):
    """A 500000 payment and a 324500 payment retire the 824500 assessment; undoing
    the second returns every bucket to exactly its post-first-payment value.

    PRD 3.4: "The reversal then subtracts exactly the four per-bucket amounts
    recorded on that record — it does not re-run the waterfall backwards — so
    interest_paid_cents, penalty_paid_cents, principal_paid_cents and
    credit_balance_cents are each reduced by that record's own allocation."

    Design: Difficulty/compensating_invariant/remittance_reversals_restore_the_statement_and_district_ledger_exactly
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 500000, method="ACH", key="rem_a")

    after_a = _statement(api, ctx.st1_id)
    assert_fields(
        after_a,
        principal_paid_cents=500000,
        total_due_cents=324500,
        payment_status="PARTIALLY_PAID",
        credit_balance_cents=0,
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=500000)

    remittance_b = fx.remit(api, ctx, "st1_id", "b1_id", 324500, method="WIRE", key="rem_b")
    assert_waterfall_allocation(remittance_b, interest=0, penalty=0, principal=324500, credit=0)
    paid = _statement(api, ctx.st1_id)
    assert_fields(paid, principal_paid_cents=824500, total_due_cents=0, payment_status="PAID_IN_FULL")
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=824500)

    reversed_record = fx.reverse(api, ctx, "st1_id", remittance_key="rem_b")
    assert_fields(reversed_record, status="REVERSED")

    restored = _statement(api, ctx.st1_id)
    for field in (
        "interest_paid_cents",
        "penalty_paid_cents",
        "principal_paid_cents",
        "credit_balance_cents",
        "total_due_cents",
        "payment_status",
    ):
        assert restored[field] == after_a[field], (
            f"{field}: reversal left {restored[field]!r}, expected {after_a[field]!r}"
        )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=500000)


def test_reversing_an_overpayment_removes_the_credit_and_reopens_the_balance(api):
    """A 400000 payment against a 324500 balance puts 75500 into credit; undoing it
    empties the credit and restores the 324500 owing.

    PRD 3.4: "unwinding a payment that had filled both principal and credit — one
    whose applied_to_credit_cents and applied_to_principal_cents are both greater
    than zero — moves it from REFUND_DUE to PARTIALLY_PAID, because removing the
    credit also reopens a positive balance."

    Design: Difficulty/compensating_invariant/remittance_reversals_restore_the_statement_and_district_ledger_exactly
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 500000, method="ACH", key="rem_a")
    overpayment = fx.remit(api, ctx, "st1_id", "b1_id", 400000, method="CHECK", key="rem_c")
    assert_waterfall_allocation(
        overpayment, interest=0, penalty=0, principal=324500, credit=75500
    )

    refund_due = _statement(api, ctx.st1_id)
    assert_fields(
        refund_due,
        principal_paid_cents=824500,
        credit_balance_cents=75500,
        total_due_cents=0,
        payment_status="REFUND_DUE",
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=900000)

    fx.reverse(api, ctx, "st1_id", remittance_key="rem_c")

    restored = _statement(api, ctx.st1_id)
    assert_fields(
        restored,
        credit_balance_cents=0,
        principal_paid_cents=500000,
        total_due_cents=324500,
        payment_status="PARTIALLY_PAID",
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=500000)


def test_the_conserved_collection_identity_survives_payments_and_reversals(api):
    """After two payments, a reversal, an overpayment and a second reversal the
    district's collected total still equals the sum of the statement's four
    buckets, and the period's collected total is back to 500000.

    PRD 2.12: "At every instant, a district's collected_to_date_cents equals the
    sum, over every one of that district's assessment statements, of
    interest_paid_cents plus penalty_paid_cents plus principal_paid_cents plus
    credit_balance_cents."

    Design: Difficulty/compensating_invariant/remittance_reversals_restore_the_statement_and_district_ledger_exactly
    """
    ctx = fx.statements_filed(api)

    def check(label, expected_collected):
        statements = validate_success(api.list_period_statements(ctx.ap_id, headers=ADMIN))
        district = validate_success(api.get_district(ctx.d_id))
        assert_conserved_collection_identity(district, statements)
        assert district["collected_to_date_cents"] == expected_collected, (
            f"{label}: collected_to_date_cents was "
            f"{district['collected_to_date_cents']}, expected {expected_collected}"
        )

    check("before any payment", 0)
    fx.remit(api, ctx, "st1_id", "b1_id", 500000, method="ACH", key="rem_a")
    check("after the first payment", 500000)
    fx.remit(api, ctx, "st1_id", "b1_id", 324500, method="WIRE", key="rem_b")
    check("after the second payment", 824500)
    fx.reverse(api, ctx, "st1_id", remittance_key="rem_b")
    check("after reversing the second payment", 500000)
    fx.remit(api, ctx, "st1_id", "b1_id", 400000, method="CHECK", key="rem_c")
    check("after the overpayment", 900000)
    fx.reverse(api, ctx, "st1_id", remittance_key="rem_c")
    check("after reversing the overpayment", 500000)

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, collected_total_cents=500000)


# --------------------------------------------------------------------------
# Signature withdrawal against a drive's support figures
# --------------------------------------------------------------------------
def _circulating_drive_signed_by_the_largest_property(api):
    """Open a formation drive and record one signature, from the property holding
    60000000 of the district's 100000000 assessable basis."""
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    return ctx


def test_a_withdrawal_restores_the_support_the_drive_held_before_the_signature(api):
    """Adding the smallest property's signature and then withdrawing it returns
    signed_basis_cents, valid_signature_count and both percentages to exactly the
    values they held with only the largest property signed.

    PRD 3.2: "The signature moves VALID to WITHDRAWN, the drive's
    signed_basis_cents is reduced by exactly that signature's
    weight_basis_revenue_cents, valid_signature_count is reduced by one, and both
    support percentages are recomputed — restoring, exactly, the values the drive
    held immediately before the signature was recorded."

    Design: Difficulty/compensating_invariant/signature_withdrawal_restores_petition_support_to_its_prior_value
    """
    ctx = _circulating_drive_signed_by_the_largest_property(api)

    before = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(before, signed_basis_cents=60000000, valid_signature_count=1)
    assert_ratio_four_dp(before["weighted_support_pct"], 0.6000, "weighted_support_pct")
    assert_ratio_four_dp(before["headcount_support_pct"], 0.2500, "headcount_support_pct")

    fx.sign(api, ctx, "b4_id")
    signature = validate_success(api.get_petition_signature(ctx.sig_b4, headers=ADMIN))
    assert_fields(signature, status="VALID", weight_basis_revenue_cents=5000000)

    joined = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(joined, signed_basis_cents=65000000, valid_signature_count=2)
    assert_ratio_four_dp(joined["weighted_support_pct"], 0.6500, "weighted_support_pct")
    assert_ratio_four_dp(joined["headcount_support_pct"], 0.5000, "headcount_support_pct")

    withdrawn = validate_success(
        api.withdraw_signature(
            ctx.sig_b4,
            f.withdrawal_payload("ownership change at the property"),
            headers=operator_headers(ctx.b4_id),
        )
    )
    assert_fields(withdrawn, status="WITHDRAWN")

    after = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(after, signed_basis_cents=60000000, valid_signature_count=1)
    assert_ratio_four_dp(after["weighted_support_pct"], 0.6000, "weighted_support_pct")
    assert_ratio_four_dp(after["headcount_support_pct"], 0.2500, "headcount_support_pct")


def test_a_withdrawn_signature_does_not_block_the_property_signing_again(api):
    """After withdrawing, the same property signs a second time and the drive
    returns to the higher support, because only a VALID signature blocks a fresh
    one.

    PRD 3.2: "at most one VALID signature may exist for a given drive-and-property
    pair, a second attempt yielding ERR_DUPLICATE_SIGNATURE — though a prior
    signature that was withdrawn or disqualified does not block a fresh one,
    because those signatures are no longer VALID."

    Design: Difficulty/compensating_invariant/signature_withdrawal_restores_petition_support_to_its_prior_value
    """
    ctx = _circulating_drive_signed_by_the_largest_property(api)
    fx.sign(api, ctx, "b4_id")
    validate_success(
        api.withdraw_signature(
            ctx.sig_b4,
            f.withdrawal_payload("ownership change at the property"),
            headers=operator_headers(ctx.b4_id),
        )
    )

    fresh = validate_success(
        api.sign_petition(ctx.pd_id, f.signature_payload(ctx.b4_id), headers=ADMIN),
        expected_status=201,
    )
    assert_fields(fresh, status="VALID", weight_basis_revenue_cents=5000000)

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, signed_basis_cents=65000000, valid_signature_count=2)
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.6500, "weighted_support_pct")


def test_the_other_signature_weight_snapshot_is_never_rewritten(api):
    """Through the whole join-and-withdraw cycle the first signature stays VALID
    and keeps the 60000000 weight it snapshotted when it was recorded.

    PRD 3.2: "captures weight_basis_revenue_cents as a snapshot of the signer's
    prior_year_gross_room_revenue_cents at the moment of signing, which is never
    re-read afterwards."

    Design: Difficulty/compensating_invariant/signature_withdrawal_restores_petition_support_to_its_prior_value
    """
    ctx = _circulating_drive_signed_by_the_largest_property(api)
    fx.sign(api, ctx, "b4_id")
    validate_success(
        api.withdraw_signature(
            ctx.sig_b4,
            f.withdrawal_payload("ownership change at the property"),
            headers=operator_headers(ctx.b4_id),
        )
    )

    signature = validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN))
    assert_fields(
        signature,
        status="VALID",
        disqualification_reason="NONE",
        weight_basis_revenue_cents=60000000,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="PETITION_CIRCULATING")

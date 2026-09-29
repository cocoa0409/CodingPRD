"""Queue A — compensating_invariant.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId, DisputeOutcome, DisputeStatus, FulfillmentStatus,
    LedgerEntryType, VerificationStatus, VoidReason, api_client,
    assertions as A, constants as C, factories as F, fixtures as fx,
    make_employee_headers,
)

ACCRUAL = LedgerEntryType.COMMISSION_ACCRUAL.value
SHARE = LedgerEntryType.EMPLOYER_SHARE.value
REVERSAL = LedgerEntryType.COMMISSION_REVERSAL.value
SHARE_REVERSAL = LedgerEntryType.EMPLOYER_SHARE_REVERSAL.value
CREDIT = LedgerEntryType.DISPUTE_CREDIT.value
RECOVERY = LedgerEntryType.DISPUTE_CREDIT_RECOVERY.value


def _disputed_line_with_goodwill():
    """A verified 8,396 cent line, disputed, then resolved `MERCHANT_FAULT`.

    Commission is 1,200 bps and the employer share 2,500 bps of that, so the
    line accrues 806 cents of commission of which 202 cents is paid away.  The
    goodwill credit is 500 cents, well inside the 6,717 cent net charge.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        offer_overrides={"min_spend_cents": 1000, "inventory_limit": 10},
    )
    created = fx.create_redemption(
        program["offer"]["id"], program["memberships"][0]["id"],
        intended_gross_amount_cents=8396,
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    verified = fx.verify_redemption(
        created, program["merchant"]["id"], gross_amount_cents=8396
    )
    A.assert_line_economics(verified, 8396, 1679, 6717, 806, 202, 604)
    program["redemption"] = verified
    program["dispute"] = fx.file_dispute(
        verified["id"], program["memberships"][0]["id"],
        reason="NOT_HONORED", description="The discount was refused at the till.",
    )
    return program


def test_dispute_reversal_and_goodwill_credit_net_the_redemption_ledger_to_zero():
    """Six rows over one redemption: two accruals, two reversals and a credit pair.

    PRD: "The entries are paired so that reversals cancel exactly: a confirmed-then-released slot nets to zero, a verified-then-refunded redemption nets its commission to zero, and a goodwill credit and its recovery net to zero."

    Design: Difficulty/compensating_invariant/dispute_reversal_and_goodwill_credit_return_the_redemption_ledger_to_zero
    """
    program = _disputed_line_with_goodwill()
    redemption_id = program["redemption"]["id"]

    assert A.ledger_signature(fx.redemption_ledger_entries(redemption_id)) == [
        (ACCRUAL, 806), (SHARE, -202),
    ]

    resolved = fx.resolve_dispute(
        program["dispute"]["id"], DisputeOutcome.MERCHANT_FAULT,
        outcome_credit_cents=500,
    )

    assert resolved["status"] == DisputeStatus.RESOLVED_MERCHANT_FAULT.value
    assert resolved["outcome_credit_cents"] == 500
    entries = fx.redemption_ledger_entries(redemption_id)
    assert len(entries) == 6
    A.assert_ledger_signature(entries, [
        (ACCRUAL, 806), (SHARE, -202),
        (REVERSAL, -806), (SHARE_REVERSAL, 202),
        (CREDIT, -500), (RECOVERY, 500),
    ])
    A.assert_ledger_nets_to_zero(entries)


def test_the_reversal_zeroes_the_employer_accrual_and_leaves_only_the_recovery():
    """Both balances are re-derived from the rows, not decremented in place.

    PRD: "A partner's `accrued_commission_payable_cents` is the sum of `amount_cents` over that partner's entries whose `entry_type` is one of `COMMISSION_ACCRUAL`, `COMMISSION_REVERSAL`, `PLACEMENT_FEE`, `PLACEMENT_FEE_REFUND` or `DISPUTE_CREDIT_RECOVERY`."

    Design: Difficulty/compensating_invariant/dispute_reversal_and_goodwill_credit_return_the_redemption_ledger_to_zero
    """
    program = _disputed_line_with_goodwill()
    merchant_id = program["merchant"]["id"]
    employer_id = program["employer"]["id"]

    assert fx.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 806
    assert fx.get_employer(employer_id)["accrued_share_cents"] == 202

    fx.resolve_dispute(
        program["dispute"]["id"], DisputeOutcome.MERCHANT_FAULT,
        outcome_credit_cents=500,
    )

    # 806 - 806 + 500: the accrual and its reversal cancel and the goodwill
    # recovery is the only surviving payable row.
    assert fx.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 500
    # -(-202 + 202) = 0: the employer's lifetime accrual is fully unwound.
    assert fx.get_employer(employer_id)["accrued_share_cents"] == 0


def test_the_refunded_line_keeps_the_economics_its_verification_crystallised():
    """Unwinding the money never rewrites the five figures on the redemption.

    PRD: "`REFUNDED` is terminal on the fulfilment dimension; the verification dimension stays `VERIFIED` and its economics figures are never rewritten."

    Design: Difficulty/compensating_invariant/dispute_reversal_and_goodwill_credit_return_the_redemption_ledger_to_zero
    """
    program = _disputed_line_with_goodwill()
    merchant_id = program["merchant"]["id"]
    redemption_id = program["redemption"]["id"]

    fx.resolve_dispute(
        program["dispute"]["id"], DisputeOutcome.MERCHANT_FAULT,
        outcome_credit_cents=500,
    )

    refunded = fx.get_redemption(redemption_id, merchant_id=merchant_id)
    A.assert_fields(refunded, {
        "verification_status": VerificationStatus.VERIFIED.value,
        "fulfillment_status": FulfillmentStatus.REFUNDED.value,
    }, "redemption")
    A.assert_line_economics(refunded, 8396, 1679, 6717, 806, 202, 604)
    A.assert_iso_equals(refunded["refunded_at"], "2026-08-02T00:00:00Z")


def _offer_with_three_units_and_four_members():
    """An `ACTIVE` offer capped at three units and a four-member roster.

    `per_member_limit` stays at its default of 1, so each membership holds at
    most one live redemption and the ceiling that binds is the offer's own
    inventory.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=4, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
        offer_overrides={"min_spend_cents": 1000, "inventory_limit": 3},
    )
    program["reservations"] = [
        fx.create_redemption(
            program["offer"]["id"], membership["id"],
            intended_gross_amount_cents=5000,
        )
        for membership in program["memberships"][:3]
    ]
    return program


def _inventory(program):
    offer = fx.get_offer(program["offer"]["id"], merchant_id=program["merchant"]["id"])
    return (
        offer["inventory_reserved"], offer["inventory_redeemed"], offer["sold_out"]
    )


def _reserve_as(program, member_index):
    membership = program["memberships"][member_index]
    return api_client.create_redemption(
        F.redemption_payload(
            program["offer"]["id"], membership["id"],
            intended_gross_amount_cents=5000,
        ),
        make_employee_headers(membership["id"]),
    )


def test_three_live_reservations_exhaust_the_inventory_and_the_fourth_is_refused():
    """Reserved plus redeemed reaching the limit is what closes the offer.

    PRD: "the offer must not be sold out, meaning that if `inventory_limit` is not null the sum of `inventory_reserved` and `inventory_redeemed` must be strictly below it (`ERR_OFFER_SOLD_OUT`)"

    Design: Difficulty/compensating_invariant/voided_and_verified_units_keep_offer_inventory_conserved_at_three
    """
    program = _offer_with_three_units_and_four_members()

    assert _inventory(program) == (3, 0, True)

    validate_error(_reserve_as(program, 3), ApiErrorId.OFFER_SOLD_OUT)

    assert _inventory(program) == (3, 0, True)


def test_cancelling_one_unit_frees_it_while_verifying_another_conserves_the_sum():
    """A void lowers the total by one; a verification only moves a unit sideways.

    PRD: "It moves the offer's unit from the reserved count to the redeemed count — since both are counts of redemptions, their sum is unchanged — and recomputes `sold_out`."

    Design: Difficulty/compensating_invariant/voided_and_verified_units_keep_offer_inventory_conserved_at_three
    """
    program = _offer_with_three_units_and_four_members()
    first, second = program["reservations"][0], program["reservations"][1]

    voided = fx.void_redemption(first["id"], membership_id=first["membership_id"])
    A.assert_fields(voided, {
        "verification_status": VerificationStatus.VOID.value,
        "void_reason": VoidReason.MEMBER_CANCELLED.value,
    }, "redemption")
    assert voided["void_reason"] == C.MEMBER_CANCELLED
    assert _inventory(program) == (2, 0, False)

    fx.set_clock("2026-08-02T00:00:00Z")
    verified = fx.verify_redemption(
        second, program["merchant"]["id"], gross_amount_cents=5000
    )

    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    # 1 + 1 is still the 2 units the offer held before the till was rung.
    assert _inventory(program) == (1, 1, False)


def test_the_freed_unit_is_reusable_and_refills_the_offer_to_sold_out():
    """Conservation is observable in reverse: the third member may take the gap.

    PRD: "Cancellation moves the redemption `PENDING → VOID`, stamps `voided_at` from the logical clock, sets `void_reason` to `MEMBER_CANCELLED`, lowers the offer's `inventory_reserved` by 1, recomputes `sold_out` and increments `version`."

    Design: Difficulty/compensating_invariant/voided_and_verified_units_keep_offer_inventory_conserved_at_three
    """
    program = _offer_with_three_units_and_four_members()
    first, second, third = program["reservations"]
    merchant_id = program["merchant"]["id"]

    fx.void_redemption(first["id"], membership_id=first["membership_id"])
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.verify_redemption(second, merchant_id, gross_amount_cents=5000)

    fourth = fx.create_redemption(
        program["offer"]["id"], program["memberships"][3]["id"],
        intended_gross_amount_cents=5000,
    )

    assert _inventory(program) == (2, 1, True)
    assert fourth["verification_status"] == VerificationStatus.PENDING.value
    assert fx.get_redemption(third["id"], merchant_id=merchant_id)[
        "verification_status"
    ] == VerificationStatus.PENDING.value

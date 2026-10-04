"""Difficulty tests: compensating invariants — charge/restore conservation and
assumption entitlement substitution."""
from __future__ import annotations

from test_helpers import (
    add_standard_service_period,
    create_assumption_payload,
    create_coe_request_payload,
    create_loan_payload,
    create_restoration_payload,
    create_veteran_payload,
    get_entitlement_account,
    setup_closed_loan,
    setup_veteran_with_issued_coe,
    validate_success,
)

BONUS_CAPACITY_CENTS = 76655000 // 4  # 19,163,750


class TestEntitlementChargeRestoreConservation:
    def test_entitlement_charge_restore_conservation(self, api):
        """PRD §2.6: "Define the entitlement in use as `total_charged_cents`
        minus `total_restored_cents`."
        PRD §3.7: "On grant, the request's `restored_amount_cents` is set to the
        loan's `entitlement_charged_cents`, the status becomes the terminal
        `GRANTED`, the account's `total_restored_cents` increases by the restored
        amount, both remaining-entitlement variants recompute"
        PRD §3.4: "`entitlement_charged_cents` becomes the smaller of one quarter
        of the loan amount (rounded half up to whole cents) and the account's
        `remaining_with_bonus_cents`"

        Design: Difficulty/compensating_invariant/entitlement_charge_restore_conservation
        """
        ctx = setup_closed_loan(price_cents=30000000)
        veteran_id = ctx["veteran"]["id"]

        after_close = get_entitlement_account(veteran_id)
        assert after_close["remaining_with_bonus_cents"] == 11663750
        # Invariant at the charged step:
        assert (
            after_close["total_charged_cents"]
            - after_close["total_restored_cents"]
            + after_close["remaining_with_bonus_cents"]
            == BONUS_CAPACITY_CENTS
        )

        validate_success(api.record_payoff(ctx["loan"]["id"], "SALE"))
        request = validate_success(
            api.create_restoration_request(
                veteran_id,
                create_restoration_payload(ctx["loan"]["id"],
                                           restoration_type="SALE_PAYOFF"),
            ),
            expected_status=201,
        )
        granted = validate_success(api.grant_restoration(request["id"]))
        assert granted["restored_amount_cents"] == 7500000

        after_grant = get_entitlement_account(veteran_id)
        assert after_grant["total_charged_cents"] == 7500000
        assert after_grant["total_restored_cents"] == 7500000
        assert after_grant["remaining_with_bonus_cents"] == 19163750
        # Conservation across the forward + compensating pair.
        assert (
            after_grant["total_charged_cents"]
            - after_grant["total_restored_cents"]
            + after_grant["remaining_with_bonus_cents"]
            == BONUS_CAPACITY_CENTS
        )

    def test_entitlement_in_use_never_decrements_total_charged(self, api):
        """PRD §2.6: "`total_charged_cents`, the sum of entitlement charges
        posted at loan closings, which is never decremented by repayment or
        passage of time"
        PRD §2.6: "Both readings are recomputed on every loan close, every
        restoration grant, and every entitlement-substituting assumption
        approval."

        Design: Difficulty/compensating_invariant/entitlement_charge_restore_conservation
        """
        ctx = setup_closed_loan(price_cents=30000000)
        veteran_id = ctx["veteran"]["id"]
        validate_success(api.record_payoff(ctx["loan"]["id"], "SALE"))
        # Payoff alone does not restore: total_charged stands, no restored yet.
        mid = get_entitlement_account(veteran_id)
        assert mid["total_charged_cents"] == 7500000
        assert mid["total_restored_cents"] == 0
        assert mid["remaining_with_bonus_cents"] == 11663750


class TestAssumptionSubstitutionConservation:
    def test_assumption_substitution_conserves_global_entitlement(self, api):
        """PRD §3.7: "Approval moves the request to its terminal `APPROVED`
        state; when entitlement is substituted, the buyer's account absorbs the
        charge (`total_charged_cents` increases by the loan's charged amount),
        the seller's account is relieved (`total_restored_cents` increases by
        the same amount), both accounts recompute their remaining variants, and
        both veterans' `charged_loan_count` recompute."

        Design: Difficulty/compensating_invariant/assumption_substitution_conserves_global_entitlement
        """
        seller_ctx = setup_closed_loan(price_cents=30000000)
        seller_id = seller_ctx["veteran"]["id"]
        loan_id = seller_ctx["loan"]["id"]

        buyer = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Buy")),
            expected_status=201,
        )
        # A short 122-day period is enough to register the buyer's account; the
        # buyer needs no COE for an assumption.
        request = validate_success(
            api.create_assumption_request(loan_id, create_assumption_payload(
                buyer_name="V Buy",
                buyer_is_veteran=True,
                buyer_veteran_id=buyer["id"],
                substitute_entitlement=True,
                release_of_liability=True,
            )),
            expected_status=201,
        )
        approved = validate_success(api.approve_assumption(request["id"]))
        assert approved["status"] == "APPROVED"

        seller_account = get_entitlement_account(seller_id)
        assert seller_account["total_charged_cents"] == 7500000
        assert seller_account["total_restored_cents"] == 7500000
        assert seller_account["remaining_with_bonus_cents"] == 19163750

        buyer_account = get_entitlement_account(buyer["id"])
        assert buyer_account["total_charged_cents"] == 7500000
        assert buyer_account["remaining_with_bonus_cents"] == 11663750

        # Global conservation: the system-wide in-use sum is unchanged.
        in_use = (
            seller_account["total_charged_cents"]
            - seller_account["total_restored_cents"]
            + buyer_account["total_charged_cents"]
            - buyer_account["total_restored_cents"]
        )
        assert in_use == 7500000

    def test_assumption_approval_moves_request_to_terminal(self, api):
        """PRD §3.7: "Approval is an `Underwriter` action with three
        preconditions: the loan must be `CLOSED` rather than `PAID_IN_FULL`;
        when `substitute_entitlement` is set the buyer must be a veteran with a
        resolvable `buyer_veteran_id`; and the buyer's entitlement account must
        hold `remaining_with_bonus_cents` at least equal to the loan's
        `entitlement_charged_cents`."

        Design: Difficulty/compensating_invariant/assumption_substitution_conserves_global_entitlement
        """
        seller_ctx = setup_closed_loan(price_cents=30000000)
        loan_id = seller_ctx["loan"]["id"]
        buyer = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Buy2")),
            expected_status=201,
        )
        request = validate_success(
            api.create_assumption_request(loan_id, create_assumption_payload(
                buyer_name="V Buy2",
                buyer_is_veteran=True,
                buyer_veteran_id=buyer["id"],
                substitute_entitlement=True,
                release_of_liability=False,
            )),
            expected_status=201,
        )
        assert request["status"] == "SUBMITTED"
        approved = validate_success(api.approve_assumption(request["id"]))
        assert approved["status"] == "APPROVED"
        # The buyer now carries exactly the seller's original charge.
        buyer_account = get_entitlement_account(buyer["id"])
        assert buyer_account["total_charged_cents"] == 7500000

"""Cyclic and forking state machines: the credit-program renewal round and
the transaction posted/disputed cycle.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    setup_program,
    issue_program,
    setup_program_with_account,
    post_promo_purchase,
    get_plan_for_transaction,
    program_summary,
    promote_to_renewal,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


class TestCreditProgramRenewalFork:

    def test_failed_renewal_round_rolls_the_program_into_wind_down(self, api, admin_headers):
        """PRD §3.2: "If the round fails, the same renewal-opening capability is
        invoked again against the `RENEWAL_NEGOTIATION` program, this time
        supplying a `to_status` of `WINDING_DOWN`". PRD §3.2: "The cycle is
        therefore `ACTIVE` → `RENEWAL_NEGOTIATION` → either `ACTIVE`
        (renewed) or `WINDING_DOWN` (failed)."

        Design: Difficulty/non_linear_state_machine/credit_program_renewal_cycle_with_failed_round_arm
        """
        _partner, _agreement, program = setup_program(api)
        assert program["program_status"] == "ACTIVE"
        assert program["version"] == 1

        negotiating = validate_success(
            api.open_renewal(program["id"], program["version"], "RENEWAL_NEGOTIATION", admin_headers),
            200,
        )
        assert negotiating["program_status"] == "RENEWAL_NEGOTIATION"
        first_version = negotiating["version"]

        winding = validate_success(
            api.open_renewal(program["id"], first_version, "WINDING_DOWN", admin_headers),
            200,
        )
        assert winding["program_status"] == "WINDING_DOWN", (
            f"the failed renewal arm should land in WINDING_DOWN, got {winding['program_status']}"
        )
        assert winding["version"] == 3, f"version should be 3, got {winding['version']}"

    def test_successful_renewal_round_returns_the_program_to_active(self, api, admin_headers):
        """PRD §3.2: "If the round succeeds, a `ProgramAdmin` completes the
        renewal, which requires the program to still be in `RENEWAL_NEGOTIATION`
        and an expected version match" and "the original program returns to
        `ACTIVE` with its version incremented".

        Design: Difficulty/non_linear_state_machine/credit_program_renewal_cycle_with_failed_round_arm
        """
        partner, agreement, program = setup_program(api)
        negotiating = promote_to_renewal(api, program["id"], program["version"])
        assert negotiating["program_status"] == "RENEWAL_NEGOTIATION"

        # Record the successor program the renewal attaches, then close the round.
        issue_program(api, partner["id"], agreement["id"], supersedes_program_id=program["id"])
        renewed = validate_success(
            api.complete_renewal(program["id"], negotiating["version"], admin_headers), 200
        )
        assert renewed["program_status"] == "ACTIVE", (
            f"a completed renewal returns the program to ACTIVE, got {renewed['program_status']}"
        )


class TestTransactionPostedDisputedCycle:

    def test_merchant_resolution_recomputes_the_plan_exposure_back_up(self, api, admin_headers):
        """PRD §3.8: "The disputed promotional plan's `subsidy_at_risk_cents` is
        recomputed from its principal and the agreement's `promo_subsidy_rate`,
        which is the first hop; the purchase's `transaction_status` returns to
        `POSTED`". PRD §3.8: "the two resolution branches differ precisely in
        whether the exposure is restored or permanently discharged."

        Design: Difficulty/non_linear_state_machine/transaction_posted_disputed_cyclic_reversal
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])
        assert plan["subsidy_at_risk_cents"] == 5756

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"],
                                "dispute_reason": "GOODS_NOT_RECEIVED"}, SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        validate_success(api.resolve_dispute(dispute["id"], "MERCHANT", SERVICE), 200)

        tx = validate_success(api.get_transaction(transaction["id"], admin_headers), 200)
        assert tx["transaction_status"] == "POSTED", (
            "merchant resolution returns the disputed purchase to POSTED"
        )
        refreshed = get_success_data(api.get_promo_plan(plan["id"], admin_headers))
        assert refreshed["plan_status"] == "ACTIVE"
        assert refreshed["subsidy_at_risk_cents"] == 5756, (
            "the merchant branch restores the exposure rather than discharging it"
        )

    def test_merchant_resolution_restores_the_program_exposure_rollup(self, api, admin_headers):
        """PRD §3.8: "and the owning program's `free_look_exposure_cents` is
        recomputed as the second hop. So the two resolution branches differ
        precisely in whether the exposure is restored or permanently discharged."

        Design: Difficulty/non_linear_state_machine/transaction_posted_disputed_cyclic_reversal
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)

        exposed = program_summary(api, program["id"])
        assert exposed["free_look_exposure_cents"] == 5756

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"],
                                "dispute_reason": "GOODS_NOT_RECEIVED"}, SERVICE)
        )
        disputed = program_summary(api, program["id"])
        assert disputed["free_look_exposure_cents"] == 0, "opening the dispute zeroes the exposure"

        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        validate_success(api.resolve_dispute(dispute["id"], "MERCHANT", SERVICE), 200)

        restored = program_summary(api, program["id"])
        assert restored["free_look_exposure_cents"] == 5756, (
            "the cycle is observable in the exposure rollup as well as the status"
        )
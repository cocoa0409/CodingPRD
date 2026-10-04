"""Compensating invariants: a forward earn and its clawback must leave the
conserved quantity exactly where it started.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_paginated,
    get_success_data,
    setup_program_with_account,
    post_promo_purchase,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


class TestLoyaltyClawbackRestoresPoints:

    def test_earn_then_clawback_returns_the_balance_to_its_pre_earn_value(self, api, admin_headers):
        """PRD §3.8: "A clawback arises from the cardholder-favored dispute branch
        just described. It requires that a benefit posting with reason
        `PURCHASE_EARN` exists on the disputed transaction. When it fires, it
        creates a new `BenefitPosting` with reason `DISPUTE_CLAWBACK` whose
        `points_amount` is negative one times the original posting's points".

        Design: Difficulty/compensating_invariant/loyalty_clawback_restores_cardholder_points_to_zero
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)

        before = get_success_data(api.get_account_loyalty(account["id"], SERVICE))
        assert before["linked_loyalty_balance"] == 0

        get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PURCHASE_EARN", "points_amount": 2400,
                 "posts_to_retailer_loyalty": True}, SERVICE),
            201,
        )
        assert get_success_data(api.get_account_loyalty(account["id"], SERVICE))[
            "linked_loyalty_balance"] == 2400

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"], "dispute_reason": "UNAUTHORIZED"},
                               SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        validate_success(api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE), 200)

        after = validate_success(api.get_account_loyalty(account["id"], SERVICE), 200)
        assert after["linked_loyalty_balance"] == 0, (
            "the compensating clawback restores the balance to its pre-earn value"
        )

    def test_the_posting_pair_sums_to_zero_and_the_earn_is_reversed(self, api, admin_headers):
        """PRD §3.8: "decrements the account's `linked_loyalty_balance` by the
        original points amount, and marks the original posting's `posted_status`
        as `REVERSED`." PRD §3.8: "A posting so reversed is terminal."

        Design: Difficulty/compensating_invariant/loyalty_clawback_restores_cardholder_points_to_zero
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        earn = get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PURCHASE_EARN", "points_amount": 2400,
                 "posts_to_retailer_loyalty": True}, SERVICE),
            201,
        )

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"], "dispute_reason": "UNAUTHORIZED"},
                               SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        validate_success(api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE), 200)

        refreshed = validate_success(api.get_benefit_posting(earn["id"], admin_headers), 200)
        assert refreshed["posted_status"] == "REVERSED"

        postings, _meta = validate_paginated(
            api.list_benefit_postings(admin_headers, {"transaction_id": transaction["id"]})
        )
        assert len(postings) == 2
        assert sum(p["points_amount"] for p in postings) == 0, (
            "the forward earn and its compensating clawback conserve the point count"
        )
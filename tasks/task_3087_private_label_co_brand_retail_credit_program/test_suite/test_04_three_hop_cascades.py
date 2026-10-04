"""Three-hop cascades: the cardholder-favoured dispute chain and the
charge-off chain. Each hop is caused by the previous one.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_paginated,
    get_success_data,
    setup_program_with_account,
    post_promo_purchase,
    get_plan_for_transaction,
    apply_principal,
    program_summary,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


def _loyalty_balance(api, account_id, headers):
    return get_success_data(api.get_account_loyalty(account_id, headers))["linked_loyalty_balance"]


class TestCardholderDisputeThreeHopCascade:

    def test_resolution_reverses_the_earn_and_claws_back_the_points(self, api, admin_headers):
        """PRD §3.8: "applying that clawback decrements the account's
        `linked_loyalty_balance` by the original points amount and marks the
        original posting `REVERSED`". PRD §3.8: "it creates a new `BenefitPosting`
        with reason `DISPUTE_CLAWBACK` whose `points_amount` is negative one times
        the original posting's points".

        Design: Difficulty/transitive_cascade/cardholder_dispute_three_hop_exposure_cascade
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        earn = get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PURCHASE_EARN", "points_amount": 1200,
                 "posts_to_retailer_loyalty": True}, SERVICE),
            201,
        )
        assert _loyalty_balance(api, account["id"], SERVICE) == 1200

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"], "dispute_reason": "FRAUD"}, SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        validate_success(api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE), 200)

        refreshed = validate_success(api.get_benefit_posting(earn["id"], admin_headers), 200)
        assert refreshed["posted_status"] == "REVERSED", "the original earn posting is marked REVERSED"

        postings, _meta = validate_paginated(
            api.list_benefit_postings(admin_headers, {"transaction_id": transaction["id"]})
        )
        assert len(postings) == 2, f"expected the earn plus its clawback, got {len(postings)}"
        clawback = [p for p in postings if p["posting_reason"] == "DISPUTE_CLAWBACK"]
        assert len(clawback) == 1
        assert clawback[0]["points_amount"] == -1200
        assert _loyalty_balance(api, account["id"], SERVICE) == 0

    def test_resolution_discharges_exposure_and_records_the_chargeback(self, api, admin_headers):
        """PRD §3.8: "On that branch the case records `chargeback_amount_cents`
        equal to the disputed purchase's `amount_cents`". PRD §3.8: "keeps a
        `subsidy_at_risk_cents` of zero rather than being recomputed."

        Design: Difficulty/transitive_cascade/cardholder_dispute_three_hop_exposure_cascade
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PURCHASE_EARN", "points_amount": 1200,
                 "posts_to_retailer_loyalty": True}, SERVICE),
            201,
        )

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"], "dispute_reason": "FRAUD"}, SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        resolved = validate_success(api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE), 200)

        assert resolved["chargeback_amount_cents"] == 120000
        assert resolved["case_status"] == "RESOLVED_FAVOR_CARDHOLDER"
        tx = validate_success(api.get_transaction(transaction["id"], admin_headers), 200)
        assert tx["transaction_status"] == "POSTED", "the purchase is chargeback-discharged"
        summary = program_summary(api, program["id"])
        assert summary["free_look_exposure_cents"] == 0


class TestChargeOffThreeHopCascade:

    def test_charge_off_expires_every_promo_plan_on_the_account(self, api, admin_headers):
        """PRD §3.5: "The second hop is caused by the first: every promotional
        plan whose `account_id` names this account has its `plan_status` set to
        `EXPIRED` and its `subsidy_at_risk_cents` set to zero."

        Design: Difficulty/transitive_cascade/charge_off_three_hop_expiry_cascade
        """
        _partner, _agreement, _program, account = setup_program_with_account(
            api, credit_limit_cents=500000
        )
        apply_principal(api, account["id"], 120000)
        get_success_data(api.schedule_payment(account["id"], "2026-09-10T00:00:00Z", admin_headers))
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])
        assert plan["plan_status"] == "ACTIVE"
        assert plan["subsidy_at_risk_cents"] == 5756

        get_success_data(api.advance_clock(200, admin_headers))
        charged = validate_success(api.charge_off(account["id"], admin_headers), 200)
        assert charged["account_status"] == "CHARGED_OFF"

        refreshed = get_success_data(api.get_promo_plan(plan["id"], admin_headers))
        assert refreshed["plan_status"] == "EXPIRED"
        assert refreshed["subsidy_at_risk_cents"] == 0

    def test_charge_off_recomputes_the_program_exposure_and_receivable(self, api, admin_headers):
        """PRD §3.5: "The third hop is caused by the second: because those plans
        have left the `ACTIVE` exposure set, the owning program's
        `free_look_exposure_cents` is recomputed, and because the account is now
        `CHARGED_OFF` its `ScheduledBalance` rows stop summing into the program's
        `outstanding_receivable_cents`".

        Design: Difficulty/transitive_cascade/charge_off_three_hop_expiry_cascade
        """
        _partner, _agreement, program, account = setup_program_with_account(
            api, credit_limit_cents=500000
        )
        apply_principal(api, account["id"], 120000)
        get_success_data(api.schedule_payment(account["id"], "2026-09-10T00:00:00Z", admin_headers))
        post_promo_purchase(api, account["id"], 120000, 12)

        before = program_summary(api, program["id"])
        assert before["free_look_exposure_cents"] == 5756
        assert before["outstanding_receivable_cents"] == 120000

        get_success_data(api.advance_clock(200, admin_headers))
        validate_success(api.charge_off(account["id"], admin_headers), 200)

        after = program_summary(api, program["id"])
        assert after["free_look_exposure_cents"] == 0
        assert after["outstanding_receivable_cents"] == 0
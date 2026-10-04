"""Corner coverage for endpoint-level behaviour: standard creation, computed
reads and the clock advance guards.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_program_with_account,
    setup_program_with_two_promo_plans,
    post_purchase,
    post_promo_purchase,
    apply_principal,
    program_summary,
    make_cardholder_headers,
    CLOCK_MAX_ADVANCE_DAYS,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


class TestTransactionCreation:

    def test_a_non_promotional_purchase_persists_its_declared_inputs(self, api, admin_headers):
        """PRD §3.4: "Posting a purchase names an `account_id`, a `merchant_name`,
        an `amount_cents`, and a `transaction_channel` of `IN_STORE` or `DIGITAL`."
        PRD §3.4: "A new transaction starts in `POSTED`."

        Design: Corner/endpoints/transaction_create_persists_email_declared_inputs
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        result = validate_success(
            api.create_transaction(
                {"account_id": account["id"], "merchant_name": "Coldgate Lanterns",
                 "amount_cents": 25000, "transaction_channel": "DIGITAL",
                 "promo_requested": False},
                make_cardholder_headers(account["id"])),
            201,
        )
        assert result["merchant_name"] == "Coldgate Lanterns"
        assert result["amount_cents"] == 25000
        assert result["transaction_channel"] == "DIGITAL"
        assert result["transaction_status"] == "POSTED"

        plans, _meta = validate_paginated(
            api.list_promo_plans(admin_headers, {"transaction_id": result["id"]})
        )
        assert plans == [], "no plan is synthesized when promo_requested is false"


class TestComputedReads:

    def test_program_summary_and_program_read_agree_on_the_rollups(self, api, admin_headers):
        """PRD §3.2: "`outstanding_receivable_cents` is the sum of
        `outstanding_balance_cents` across every account on the program whose
        `account_status` is not `CHARGED_OFF`." PRD §3.2: "`free_look_exposure_cents`
        is the sum of `subsidy_at_risk_cents` across every promotional plan on the
        program whose `plan_status` is `ACTIVE`."

        Design: Corner/endpoints/program_summary_computed_read_matches_the_rollups
        """
        _p, _a, program, account, _plan12, _plan6 = setup_program_with_two_promo_plans(
            api, principal_balance_cents=300000, credit_limit_cents=500000
        )
        summary = validate_success(api.get_program_summary(program["id"], admin_headers), 200)
        resource = validate_success(api.get_credit_program(program["id"], admin_headers), 200)

        assert summary["outstanding_receivable_cents"] == 300000
        assert summary["account_count"] == 1
        assert summary["free_look_exposure_cents"] == 10432
        assert summary["program_status"] == "ACTIVE"
        assert summary["settled_batch_count"] == 0
        assert resource["outstanding_receivable_cents"] == summary["outstanding_receivable_cents"]
        assert resource["free_look_exposure_cents"] == summary["free_look_exposure_cents"]

    def test_account_loyalty_view_lists_the_posting_count(self, api, admin_headers):
        """PRD §3.8: "An accepted posting increments the account's
        `linked_loyalty_balance` by `points_amount` — which is exactly how a
        negative clawback decrements it."

        Design: Corner/endpoints/account_loyalty_read_lists_posting_count
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_purchase(api, account["id"], amount_cents=40000)
        get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PURCHASE_EARN", "points_amount": 400,
                 "posts_to_retailer_loyalty": True}, SERVICE), 201)
        get_success_data(
            api.create_benefit_posting(
                {"account_id": account["id"], "transaction_id": transaction["id"],
                 "posting_reason": "PROMO_BONUS", "points_amount": 800,
                 "posts_to_retailer_loyalty": True}, SERVICE), 201)

        loyalty = validate_success(api.get_account_loyalty(account["id"], SERVICE), 200)
        assert loyalty["linked_loyalty_balance"] == 1200
        assert loyalty["posting_count"] == 2
        assert loyalty["last_posted_at"] is not None


class TestClockAdvanceGuards:

    def test_advance_rejects_zero_and_over_range_day_counts(self, api, admin_headers):
        """PRD §2.5: "The second advances the clock by a whole number of days
        supplied in `days`; the accepted range is 1 to 3650 inclusive, and a
        request outside that range is rejected with `ERR_INVALID_ADVANCE_DAYS`
        (HTTP 422)."

        Design: Corner/endpoints/clock_advance_rejects_zero_and_over_range_day_counts
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", admin_headers))

        zero = api.advance_clock(0, admin_headers)
        validate_error(zero, ApiErrorId.ERR_INVALID_ADVANCE_DAYS, 422)

        boundary = validate_success(api.advance_clock(CLOCK_MAX_ADVANCE_DAYS, admin_headers), 200)
        assert boundary["advanced_days"] == CLOCK_MAX_ADVANCE_DAYS

        too_far = api.advance_clock(4000, admin_headers)
        validate_error(too_far, ApiErrorId.ERR_INVALID_ADVANCE_DAYS, 422)
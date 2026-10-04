"""Corner coverage for the business validations: satisfaction and violation
sides of the credit-limit, minimum-charge, prescreen, revenue-share,
supersedes and purchase-price rules.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    onboard_partner,
    setup_program,
    setup_program_with_account,
    setup_closed_program,
    apply_principal,
    make_cardholder_headers,
    propose_transfer,
    roll_into_winding_down,
    MINIMUM_CHARGE_CENTS_DEFAULT,
)


class TestCreditLimitBoundary:

    def test_a_purchase_that_lands_exactly_on_the_limit_succeeds(self, api, admin_headers):
        """PRD §3.4: "The new `amount_cents` added to the account's current
        `outstanding_balance_cents` may not exceed the account's
        `credit_limit_cents`, and a purchase that would breach the line is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/delinquency_two_percent_floor_rule_passes_when_met
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        apply_principal(api, account["id"], 190000)

        result = validate_success(
            api.create_transaction(
                {"account_id": account["id"], "merchant_name": "Coldgate Cleats",
                 "amount_cents": 10000, "transaction_channel": "IN_STORE",
                 "promo_requested": False},
                make_cardholder_headers(account["id"])),
            201,
        )
        assert result["amount_cents"] == 10000
        rows, _meta = validate_paginated(
            api.list_transactions(admin_headers, {"account_id": account["id"]})
        )
        assert len(rows) == 1

    def test_one_cent_over_the_limit_trips_the_credit_limit_error(self, api, admin_headers):
        """PRD §3.4: "The credit check is applied to every purchase regardless of
        promotional election. The new `amount_cents` added to the account's current
        `outstanding_balance_cents` may not exceed the account's
        `credit_limit_cents`, and a purchase that would breach the line is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/credit_limit_exceeded_fires_one_cent_over
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        apply_principal(api, account["id"], 190000)

        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Coldgate Charts",
             "amount_cents": 10001, "transaction_channel": "DIGITAL",
             "promo_requested": False},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 422)
        rows, _meta = validate_paginated(
            api.list_transactions(admin_headers, {"account_id": account["id"]})
        )
        assert rows == []


class TestMinimumChargeBoundary:

    def test_one_cent_below_the_floor_is_rejected_and_the_floor_is_accepted(self, api, admin_headers):
        """PRD §3.4: "Second, the purchase amount must meet the governing
        agreement's `minimum_charge_cents`; a deferred-interest purchase below that
        floor is rejected with `ERR_PROMO_MINIMUM_CHARGE` (HTTP 422)."

        Design: Corner/validations/promo_below_minimum_charge_violation
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=500000)

        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Coldgate Pins",
             "amount_cents": MINIMUM_CHARGE_CENTS_DEFAULT - 1, "transaction_channel": "IN_STORE",
             "promo_requested": True, "promo_term_months": 12},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROMO_MINIMUM_CHARGE, 422)

        at_floor = validate_success(
            api.create_transaction(
                {"account_id": account["id"], "merchant_name": "Coldgate Nails",
                 "amount_cents": MINIMUM_CHARGE_CENTS_DEFAULT, "transaction_channel": "IN_STORE",
                 "promo_requested": True, "promo_term_months": 12},
                make_cardholder_headers(account["id"])),
            201,
        )
        assert at_floor["amount_cents"] == MINIMUM_CHARGE_CENTS_DEFAULT
        rows, _meta = validate_paginated(
            api.list_transactions(admin_headers, {"account_id": account["id"]})
        )
        assert len(rows) == 1, "only the qualifying purchase landed"


class TestPrescreenReference:

    def test_prescreened_application_without_a_reference_is_rejected(self, api, admin_headers):
        """PRD §3.3: "an application captured through the prescreened channel must
        additionally carry a `prescreen_reference` that resolves to a live offer;
        a `PRESCREENED` application that omits the reference or supplies one that
        does not resolve is rejected with `ERR_PRESCREEN_REQUIRED` (HTTP 422)."

        Design: Corner/validations/prescreened_application_without_reference_violation
        """
        _partner, _agreement, program = setup_program(api)
        resp = api.create_application(
            {"program_id": program["id"], "source_channel": "PRESCREENED",
             "requested_credit_limit_cents": 150000},
            TEST_USERS["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PRESCREEN_REQUIRED, 422)
        rows, _meta = validate_paginated(
            api.list_applications(admin_headers, {"program_id": program["id"]})
        )
        assert rows == [], "the rejected application is not stored"


class TestRevenueShareCeiling:

    def test_a_sum_above_one_is_rejected_and_exactly_one_is_accepted(self, api, admin_headers):
        """PRD §3.1: "Their sum may never exceed 1.0, and a draft or an execution
        that would breach that ceiling is rejected with `ERR_REVENUE_SHARE_INVALID`
        (HTTP 422)."

        Design: Corner/validations/revenue_share_over_one_hundred_percent_violation
        """
        partner = onboard_partner(api)
        resp = api.create_agreement(
            {"partner_id": partner["id"], "revenue_share_rate": 0.70,
             "promo_subsidy_rate": 0.40, "promo_term_months": 12}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_REVENUE_SHARE_INVALID, 422)

        accepted = validate_success(
            api.create_agreement(
                {"partner_id": partner["id"], "revenue_share_rate": 0.60,
                 "promo_subsidy_rate": 0.40, "promo_term_months": 12}, admin_headers),
            201,
        )
        assert accepted["revenue_share_rate"] + accepted["promo_subsidy_rate"] == 1.0


class TestSupersedesReference:

    def test_naming_a_closed_predecessor_is_rejected(self, api, admin_headers):
        """PRD §3.2: "When a predecessor is named it must resolve to a program
        that exists and whose `program_status` is not `CLOSED`; a named
        predecessor that is missing or already closed is rejected with
        `ERR_SUPERSEDES_INVALID` (HTTP 422)."

        Design: Corner/validations/supersedes_closed_program_violation
        """
        partner, agreement, closed, _account, _transfer = setup_closed_program(api)
        resp = api.create_credit_program(
            {"partner_id": partner["id"], "agreement_id": agreement["id"],
             "supersedes_program_id": closed["id"], "cycle_day": 16}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_INVALID, 422)

    def test_naming_a_live_predecessor_is_accepted(self, api, admin_headers):
        """PRD §3.2: "A first-generation program carries no predecessor at all and
        leaves the field null." PRD §3.2: "it must resolve to a program that exists
        and whose `program_status` is not `CLOSED`".

        Design: Corner/validations/supersedes_closed_program_violation
        """
        partner, agreement, predecessor = setup_program(api)
        successor = validate_success(
            api.create_credit_program(
                {"partner_id": partner["id"], "agreement_id": agreement["id"],
                 "supersedes_program_id": predecessor["id"], "cycle_day": 16}, admin_headers),
            201,
        )
        assert successor["supersedes_program_id"] == predecessor["id"]


class TestPurchasePriceFloor:

    def test_a_price_below_book_value_times_the_rate_is_rejected(self, api, admin_headers):
        """PRD §3.9: "Any proposed price must be at least the program's book value
        multiplied by the agreement's `purchase_right_rate`; a lower proposal is
        rejected with `ERR_PURCHASE_PRICE_BELOW_FLOOR` (HTTP 422)."

        Design: Corner/validations/purchase_price_below_floor_violation
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        apply_principal(api, account["id"], 100000)
        roll_into_winding_down(api, program["id"], program["version"])

        resp = api.create_transfer(
            {"program_id": program["id"], "buyer_role": "ISSUER",
             "proposed_price_cents": 103999}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_PURCHASE_PRICE_BELOW_FLOOR, 422)

    def test_the_floor_price_itself_is_accepted(self, api, admin_headers):
        """PRD §3.9: "The accepted `purchase_price_cents` is the supplied
        `proposed_price_cents` when one was given, and otherwise the book value
        multiplied by the rate, rounded half-up to the nearest cent."

        Design: Corner/validations/purchase_price_below_floor_violation
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        apply_principal(api, account["id"], 100000)
        roll_into_winding_down(api, program["id"], program["version"])

        transfer = validate_success(
            api.create_transfer({"program_id": program["id"], "buyer_role": "ISSUER",
                                 "proposed_price_cents": 104000}, admin_headers),
            201,
        )
        assert transfer["portfolio_book_value_cents"] == 100000
        assert transfer["purchase_price_cents"] == 104000
"""The fixed order in which guards are evaluated when several of them fail at once."""

from test_helpers import (
    ApiErrorId,
    create_purchase_payload,
    money,
    open_active_account,
    read_registration,
    set_clock,
    setup_closed_account_against_small_registration,
    setup_unregistered_state_account,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]

CLOCK_MONDAY = "2026-08-03T09:00:00Z"
UNKNOWN_SHARE_CLASS_ID = "00000000-0000-4000-8000-000000000003"


class TestAccountStateOutranksCapacity:
    def test_a_closed_account_surfaces_the_state_error_not_the_capacity_error(self, api):
        """PRD §2.7: "The server evaluates guards in the following fixed precedence; the
        first guard that fails determines the response, and no later guard is consulted."
        PRD §2.7: "**Account state.** The account referenced by the operation is in a state
        that permits it: purchase-side and redemption-side order capture, systematic plan
        creation and systematic plan execution all require the account's `status` to be
        `ACTIVE` or `RESTRICTED`, and `PENDING_DOCS` or `CLOSED` is rejected with
        `ERR_ACCOUNT_NOT_ACTIVE` (409)."
        PRD §2.7: "**Registration capacity.** `ERR_BLUE_SKY_CAPACITY_EXCEEDED` (422) on
        `POST /trades`, as described in §3.4."

        Design: Difficulty/priority_pair_validation_conflict/closed_account_state_error_outranks_blue_sky_capacity_error
        """
        setup = setup_closed_account_against_small_registration()
        assert setup["account"]["status"] == "CLOSED"
        assert setup["registration"]["registered_amount"] == money(50000.00)

        response = api.create_trade(
            create_purchase_payload(
                setup["account"]["id"], setup["share_class"]["id"], 60000.00
            ),
            OPERATOR,
        )
        assert response.status_code == 409
        error = validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)
        assert error["error_id"] != ApiErrorId.ERR_BLUE_SKY_CAPACITY_EXCEEDED.value

    def test_the_rejected_capture_reserves_no_registration_capacity(self, api):
        """PRD §2.7: "Two consequences of this ordering are worth stating plainly. Because
        account state (rule 9) is evaluated before the declared-transition check (rule 10),
        an operation aimed at a `CLOSED` account surfaces as `ERR_ACCOUNT_NOT_ACTIVE` rather
        than as a state-machine rejection."
        PRD §3.4: "A new filing starts with `reserved_amount` and `consumed_amount` at
        `0.00`, `remaining_amount` equal to `registered_amount`, and `status` `ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/closed_account_state_error_outranks_blue_sky_capacity_error
        """
        setup = setup_closed_account_against_small_registration()

        api.create_trade(
            create_purchase_payload(
                setup["account"]["id"], setup["share_class"]["id"], 60000.00
            ),
            OPERATOR,
        )

        registration = read_registration(setup["registration"]["id"])
        assert registration["reserved_amount"] == money(0.00)
        assert registration["remaining_amount"] == money(50000.00)

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": setup["account"]["id"]})
        )
        assert meta["total_count"] == 0


class TestAsOfWindowOutranksRegistrationCoverage:
    def test_the_as_of_window_error_wins_over_the_unregistered_state_error(self, api):
        """PRD §2.7: "The server evaluates guards in the following fixed precedence; the
        first guard that fails determines the response, and no later guard is consulted."
        PRD §2.7: "**As-of window.** The number of business days separating the
        `as_of_date` from the current business date must be at most three, otherwise
        `ERR_AS_OF_WINDOW_EXCEEDED` (422). Applies to `POST /trades`."
        PRD §2.7: "**State registration coverage.** `ERR_BLUE_SKY_NOT_REGISTERED` (422) on
        `POST /trades`, as described in §3.4."

        Design: Difficulty/priority_pair_validation_conflict/as_of_window_safety_error_outranks_unregistered_state_referential_error
        """
        setup = setup_unregistered_state_account()
        assert setup["account"]["state_code"] == "TX"

        response = api.create_trade(
            create_purchase_payload(
                setup["account"]["id"], setup["share_class"]["id"], 5000.00,
                as_of_date=MONDAY,
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        error = validate_error(response, ApiErrorId.ERR_AS_OF_WINDOW_EXCEEDED.value)
        assert error["error_id"] != ApiErrorId.ERR_BLUE_SKY_NOT_REGISTERED.value

    def test_the_rejected_backdated_capture_creates_no_order(self, api):
        """PRD §2.4: "Where the specification counts business days between two dates —
        written here as the number of business days separating an earlier date from a later
        one — the count includes every business day strictly after the earlier date and up
        to and including the later date."
        PRD §3.4: "Third, the number of business days separating the `as_of_date` from the
        current business date must be at most three; a wider gap is refused with
        `ERR_AS_OF_WINDOW_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/as_of_window_safety_error_outranks_unregistered_state_referential_error
        """
        setup = setup_unregistered_state_account()

        api.create_trade(
            create_purchase_payload(
                setup["account"]["id"], setup["share_class"]["id"], 5000.00,
                as_of_date=MONDAY,
            ),
            OPERATOR,
        )

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": setup["account"]["id"]})
        )
        assert meta["total_count"] == 0


class TestBodyReferenceOutranksAccountState:
    def test_an_unknown_share_class_is_caught_before_the_account_state_check(self, api):
        """PRD §2.7: "**Body reference existence.** Every foreign key supplied in a request
        body resolves to an existing row, answered with the same 404 family
        (`ERR_FUND_NOT_FOUND`, `ERR_SHARE_CLASS_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_NAV_RECORD_NOT_FOUND`, `ERR_TRADE_NOT_FOUND`)."
        PRD §2.7: "**Account state.** The account referenced by the operation is in a state
        that permits it: purchase-side and redemption-side order capture, systematic plan
        creation and systematic plan execution all require the account's `status` to be
        `ACTIVE` or `RESTRICTED`, and `PENDING_DOCS` or `CLOSED` is rejected with
        `ERR_ACCOUNT_NOT_ACTIVE` (409)."

        Design: Corner/validations/unknown_share_class_in_the_body_is_caught_before_the_account_state_check
        """
        set_clock(CLOCK_MONDAY)
        account = open_active_account(primary_owner_name="Cleo Closed")
        closed = validate_success(
            api.close_shareholder_account(account["id"], OPERATOR), 200
        )
        assert closed["status"] == "CLOSED"

        response = api.create_trade(
            create_purchase_payload(
                account["id"], UNKNOWN_SHARE_CLASS_ID, 1000.00
            ),
            OPERATOR,
        )
        assert response.status_code == 404
        error = validate_error(response, ApiErrorId.ERR_SHARE_CLASS_NOT_FOUND.value)
        assert error["error_id"] != ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value

"""Forward pricing, the logical clock, as-of controls and capture-time eligibility."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_trade,
    buy_and_settle,
    capture_purchase,
    create_exchange_payload,
    create_purchase_payload,
    create_redemption_payload,
    money,
    only_position,
    read_registration,
    set_clock,
    setup_trading_desk,
    shares,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    TUESDAY,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestForwardPricingClock:
    def test_capture_at_exactly_the_cutoff_prices_on_the_next_business_day(self, api):
        """PRD §3.4: "Otherwise, if the clock's date is a business day and the clock's
        time-of-day is strictly earlier than the cutoff, `trade_date` is the clock's date;
        in every other case — the clock's date falls on a weekend, or the time-of-day is
        exactly at or later than the cutoff — `trade_date` is the earliest business day
        strictly after the clock's date."
        PRD §3.4: "The comparison against the cutoff is strict in the shareholder's
        disfavour: an order arriving at exactly the cutoff second prices on the next
        business day, not the current one."
        PRD §3.4: "For a `PURCHASE`, the order's `gross_amount` must be less than or equal
        to that registration's `remaining_amount` — equality is accepted and drives the
        registration straight to `EXHAUSTED` — and an amount above it is refused with
        `ERR_BLUE_SKY_CAPACITY_EXCEEDED`; on success `reserved_amount` increases by
        `gross_amount`."

        Design: Corner/calculations/capture_at_exactly_the_cutoff_prices_on_the_next_business_day
        """
        desk = setup_trading_desk(
            clock="2026-08-03T15:59:59Z",
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            fund_overrides={"cutoff_time_utc": "16:00:00"},
            account_overrides={"primary_owner_name": "Fred Forward"},
        )
        before_cutoff = validate_success(
            api.create_trade(
                create_purchase_payload(
                    desk["account"]["id"], desk["share_class"]["id"], 1000.00
                ),
                OPERATOR,
            ),
            201,
        )
        assert_trade(before_cutoff)
        assert before_cutoff["trade_date"] == MONDAY

        set_clock("2026-08-03T16:00:00Z")
        at_cutoff = validate_success(
            api.create_trade(
                create_purchase_payload(
                    desk["account"]["id"], desk["share_class"]["id"], 1000.00
                ),
                OPERATOR,
            ),
            201,
        )
        assert at_cutoff["trade_date"] == TUESDAY
        assert before_cutoff["execution_status"] == "RECEIVED"
        assert at_cutoff["execution_status"] == "RECEIVED"

        registration = read_registration(desk["registration"]["id"])
        assert registration["reserved_amount"] == money(2000.00)

    def test_untouched_clock_starts_on_saturday_and_rolls_to_monday(self, api):
        """PRD §2.4: "Before that clock has been moved for the first time, it reads
        exactly `2026-08-01T00:00:00Z`, which is a Saturday."
        PRD §3.4: "Capture stamps `received_at` from the current logical clock instant and
        `captured_by_user_id` from the caller's `X-User-ID`, and computes `trade_date`, the
        effective pricing date."
        PRD §2.4: "Business days are Monday through Friday. No holiday calendar is
        modelled, so every weekday is a business day and Saturday and Sunday are not."

        Design: Corner/calculations/unset_clock_starts_on_saturday_so_capture_prices_the_following_monday
        """
        desk = setup_trading_desk(
            clock=None,
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            account_overrides={"primary_owner_name": "Una Unset"},
        )
        trade = validate_success(
            api.create_trade(
                create_purchase_payload(
                    desk["account"]["id"], desk["share_class"]["id"], 2500.00
                ),
                OPERATOR,
            ),
            201,
        )
        assert_instant_equals(
            trade["received_at"], "2026-08-01T00:00:00Z", "received_at"
        )
        assert trade["trade_date"] == MONDAY


class TestAsOfControls:
    def test_same_day_as_of_at_the_cutoff_is_refused_as_a_late_trade(self, api):
        """PRD §3.4: "First, late trading: an `as_of_date` equal to the current logical
        clock date while the clock's time-of-day is at or after the fund's cutoff is refused
        outright with `ERR_LATE_TRADE_PROHIBITED` — this is the prohibition against handing
        a shareholder today's already-known price after today's book has closed."
        PRD §3.4: "A new filing starts with `reserved_amount` and `consumed_amount` at
        `0.00`, `remaining_amount` equal to `registered_amount`, and `status` `ACTIVE`."

        Design: Corner/errors/same_day_as_of_after_the_cutoff_is_rejected_as_a_late_trade
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            fund_overrides={"cutoff_time_utc": "16:00:00"},
            account_overrides={"primary_owner_name": "Lou Late"},
        )
        set_clock("2026-08-04T16:00:00Z")

        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 5000.00,
                as_of_date=TUESDAY,
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_LATE_TRADE_PROHIBITED.value)

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert meta["total_count"] == 0
        assert read_registration(desk["registration"]["id"])["reserved_amount"] == money(0.00)

    def test_as_of_date_beyond_the_clock_date_is_refused(self, api):
        """PRD §3.4: "Second, an `as_of_date` strictly after the current logical clock
        date, or one that falls on a Saturday or a Sunday, is refused with
        `ERR_AS_OF_FUTURE_DATE`."

        Design: Corner/errors/as_of_date_after_the_clock_date_returns_future_date_error
        """
        desk = setup_trading_desk(
            clock="2026-08-04T10:00:00Z",
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            account_overrides={"primary_owner_name": "Fay Future"},
        )
        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 5000.00,
                as_of_date="2026-08-05",
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_AS_OF_FUTURE_DATE.value)

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert meta["total_count"] == 0


class TestCaptureEligibility:
    def test_purchase_on_a_fund_closed_to_new_money_is_refused(self, api):
        """PRD §3.1: "A fund that has moved to `CLOSED_TO_NEW` still supports redemptions
        and still pays distributions, but purchase-side capture against any of its classes
        is refused with `ERR_FUND_CLOSED_TO_NEW`."
        PRD §3.4: "A `PURCHASE` or `EXCHANGE` on a class whose fund is `CLOSED_TO_NEW` is
        refused with `ERR_FUND_CLOSED_TO_NEW`."
        PRD §3.4: "A new filing starts with `reserved_amount` and `consumed_amount` at
        `0.00`, `remaining_amount` equal to `registered_amount`, and `status` `ACTIVE`."

        Design: Corner/errors/purchase_on_a_fund_closed_to_new_money_returns_fund_closed_to_new
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            fund_overrides={"name": "Meridian Closed Fund", "status": "CLOSED_TO_NEW"},
            account_overrides={"primary_owner_name": "Fio Closed"},
        )
        assert desk["fund"]["status"] == "CLOSED_TO_NEW"

        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 1000.00
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_FUND_CLOSED_TO_NEW.value)

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert meta["total_count"] == 0
        assert read_registration(desk["registration"]["id"])["reserved_amount"] == money(0.00)

    def test_purchase_from_an_unregistered_state_is_refused(self, api):
        """PRD §3.4: "The system selects among the registrations for the class being
        bought — for an `EXCHANGE`, the *target* class — whose `state_code` equals the
        owning account's `state_code`, whose `status` is `ACTIVE` or `EXHAUSTED`, and whose
        window covers the `trade_date` in the half-open sense of `effective_date` on or
        before the trade date and `expiration_date` strictly after it."
        PRD §3.4: "If no candidate survives, capture is refused with
        `ERR_BLUE_SKY_NOT_REGISTERED`."
        PRD §3.4: "A new filing starts with `reserved_amount` and `consumed_amount` at
        `0.00`, `remaining_amount` equal to `registered_amount`, and `status` `ACTIVE`."

        Design: Corner/errors/purchase_in_an_unregistered_state_returns_blue_sky_not_registered
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            state_code="CA",
            strike_seed_nav=False,
            account_overrides={"state_code": "FL", "primary_owner_name": "Flo Sunshine"},
        )
        assert desk["account"]["state_code"] == "FL"

        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 1000.00
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_BLUE_SKY_NOT_REGISTERED.value)

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert meta["total_count"] == 0
        assert read_registration(desk["registration"]["id"])["reserved_amount"] == money(0.00)

    def test_exchange_into_the_source_class_is_refused(self, api):
        """PRD §3.4: "An `EXCHANGE` additionally names its
        `exchange_target_share_class_id`, the class being exchanged into, which must be
        present for an exchange, must be null otherwise, and must differ from
        `share_class_id` — an exchange into the same class is refused with
        `ERR_EXCHANGE_TARGET_INVALID`."

        Design: Corner/errors/exchange_into_the_source_class_returns_exchange_target_invalid
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Xu Target"},
        )
        buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 30000.00)

        response = api.create_trade(
            create_exchange_payload(
                desk["account"]["id"], desk["share_class"]["id"], 100.000,
                desk["share_class"]["id"],
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_EXCHANGE_TARGET_INVALID.value)

        _, meta = validate_paginated(
            api.list_trades(
                OPERATOR,
                params={"account_id": desk["account"]["id"], "trade_type": "EXCHANGE"},
            )
        )
        assert meta["total_count"] == 0
        assert only_position(desk["account"]["id"])["shares"] == shares(2827.500)

    def test_redemption_beyond_the_position_balance_is_refused(self, api):
        """PRD §3.4: "A `REDEMPTION` or `EXCHANGE` asking for more shares than the owning
        position holds is refused with `ERR_INSUFFICIENT_SHARES`."

        Design: Corner/validations/redemption_beyond_the_position_balance_returns_insufficient_shares
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Sam Shortfall"},
        )
        buy_and_settle(desk["account"]["id"], desk["share_class"]["id"], 30000.00)
        assert only_position(desk["account"]["id"])["shares"] == shares(2827.500)

        response = api.create_trade(
            create_redemption_payload(
                desk["account"]["id"], desk["share_class"]["id"], 3000.000
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SHARES.value)

        _, meta = validate_paginated(
            api.list_trades(
                OPERATOR,
                params={"account_id": desk["account"]["id"], "trade_type": "REDEMPTION"},
            )
        )
        assert meta["total_count"] == 0
        assert only_position(desk["account"]["id"])["shares"] == shares(2827.500)

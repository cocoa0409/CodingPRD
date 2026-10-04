"""Lifetime buys: historical price lock, create/cancel compensation, floor gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_lifetime_buy,
    create_lifetime_buy_payload,
    get_customer,
    get_part,
    make_customer,
    make_customer_headers,
    make_eol_notice,
    make_ltb_ready_part,
    make_stocked_priced_part,
    place_lifetime_buy,
    publish_price,
    set_clock,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestLifetimeBuys:
    def test_ltb_price_locks_to_notice_date_schedule(self, api):
        """PRD §3.7: "Among all of the part's pricing schedules with
        `effective_from` at or before the notice's `notice_date` — regardless of
        whether the schedule is `PUBLISHED` or `SUPERSEDED` today, since locking the
        price the customer could see at notification time is intentional — the
        schedule with the latest `effective_from` is selected, with ties on
        `effective_from` broken toward the earliest `created_at`."
        PRD §3.7: "The buy's value, `ltb_value_cents`, is `unit_price_cents`
        multiplied by `quantity`."

        Design: Corner/calculations/ltb_price_locks_to_notice_date_schedule
        """
        part, pool = make_stocked_priced_part(
            "LM317T-STEEL", on_hand=3000, unit_price_cents=300,
            demand_rate=40, buffer_multiple=1.5,
            package_family="TO39", pool_total_units=5000,
            effective_from="2026-08-01T00:00:00Z",
        )
        publish_price(part["id"], unit_price_cents=200,
                      effective_from="2026-08-15T00:00:00Z")
        # Notice date falls between the two effective dates:
        # 2026-08-10 + 180d = 2027-02-06; 2027-02-06 + 90d = 2027-05-07.
        notice = make_eol_notice(
            part["id"],
            notice_date="2026-08-10T00:00:00Z",
            last_order_date="2027-02-06T00:00:00Z",
            last_ship_date="2027-05-07T00:00:00Z",
            reason="Package EOL",
        )
        cust = make_customer(name="Legacy Systems", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)

        ltb = place_lifetime_buy(notice, part["id"], cust["id"], 2080)
        assert_lifetime_buy(ltb)
        assert ltb["unit_price_cents"] == 300, "price locked at the notice date"
        assert ltb["ltb_value_cents"] == 624000  # 300 * 2080
        assert ltb["status"] == "APPROVED"
        assert get_part(part["id"])["reserved_units"] == 2080

    def test_ltb_create_and_cancel_release_reservation_and_exposure(self, api):
        """PRD §3.7: "A lifetime buy is created directly in `APPROVED` status: its
        `quantity` is added to the part's `reserved_units`, its `ltb_value_cents` is
        added to the customer's `open_exposure_cents`, and the part's `posture` is
        recomputed."
        PRD §3.7: "Cancelling — by the owning `Customer` or a `ChannelManager`, and
        only from `APPROVED`, otherwise `ERR_INVALID_STATE` — reverses all three
        effects: the part's `reserved_units` decreases by the `quantity`, the
        customer's `open_exposure_cents` decreases by the `ltb_value_cents`,
        `posture` is recomputed, and the buy settles into the terminal `CANCELLED`."

        Design: Corner/endpoints/ltb_create_and_cancel_release_reservation_and_exposure
        """
        part, _, notice = make_ltb_ready_part(
            "LF412CN", demand_rate=40, on_hand=3000, unit_price_cents=150
        )
        cust = make_customer(name="Lifetime Buyer", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)

        ltb = place_lifetime_buy(notice, part["id"], cust["id"], 2080)
        assert ltb["status"] == "APPROVED"
        assert ltb["unit_price_cents"] == 150
        assert ltb["ltb_value_cents"] == 312000
        assert get_part(part["id"])["reserved_units"] == 2080
        assert get_customer(cust["id"])["open_exposure_cents"] == 312000

        cancelled = validate_success(
            api.cancel_lifetime_buy(ltb["id"], make_customer_headers(cust["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_part(part["id"])["reserved_units"] == 0
        assert get_customer(cust["id"])["open_exposure_cents"] == 0

    def test_ltb_below_min_quantity_rejected(self, api):
        """PRD §3.7: "The `quantity` must cover at least one year of trailing
        demand: at least the part's `demand_rate_units_per_week` multiplied by 52,
        else `ERR_LTB_QUANTITY_BELOW_MIN` (HTTP 422)."

        Design: Corner/validations/ltb_below_min_quantity_rejected
        """
        part, _, notice = make_ltb_ready_part(
            "TL494CN", demand_rate=40, on_hand=3000, unit_price_cents=150
        )
        cust = make_customer(name="Min Violator", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)

        res = api.create_lifetime_buy(
            create_lifetime_buy_payload(notice["id"], part["id"], cust["id"], 2079),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LTB_QUANTITY_BELOW_MIN)
        assert get_part(part["id"])["reserved_units"] == 0

    def test_ltb_after_last_order_date_rejected(self, api):
        """PRD §3.7: "The logical clock must not be past the notice's
        `last_order_date`, else `ERR_LAST_ORDER_DATE_PASSED` (HTTP 422)."
        PRD §2.5: "A part in `EOL_ANNOUNCED` advances to `LAST_TIME_BUY` once the
        clock reaches the `last_order_date` of its `ANNOUNCED` end-of-life notice".

        Design: Corner/validations/ltb_after_last_order_date_rejected
        """
        part, pool = make_stocked_priced_part(
            "UC3842N", on_hand=3000, unit_price_cents=150, demand_rate=40,
            pool_total_units=5000,
        )
        notice = make_eol_notice(part["id"], reason="EOL")
        cust = make_customer(name="Late Buyer", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        set_clock("2027-03-01T00:00:00Z")  # one day past last_order_date

        res = api.create_lifetime_buy(
            create_lifetime_buy_payload(notice["id"], part["id"], cust["id"], 2080),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LAST_ORDER_DATE_PASSED)

        after = get_part(part["id"])
        assert after["lifecycle_status"] == "LAST_TIME_BUY"
        assert after["reserved_units"] == 0

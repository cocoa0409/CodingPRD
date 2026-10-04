"""Boundary precision: PRINT coupon daily redemption limit (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    create_active_item,
    create_coupon_payload,
    get_success_data,
    make_completed_sale,
    make_customer,
    make_open_sale,
    make_store,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

MM = TEST_USERS["marketing_manager_headers"]
SC = TEST_USERS["store_clerk_headers"]


class TestPrintCouponDailyLimit:

    def test_print_coupon_daily_limit_exact_boundary(self, api):
        """PRD §3.7: "Per-customer limit: the customer's `usage_records` count
        for the coupon must be below `per_customer_limit`; a count equal to the
        limit rejects with `ERR_COUPON_CUSTOMER_LIMIT_REACHED`. Channel cadence
        refines what the count means: for `PRINT` coupons the limit applies per
        calendar day of redemption (the count resets daily)"

        Design: Difficulty/boundary_precision_check/print_coupon_daily_limit_exact_boundary
        """
        item = create_active_item(sku="BD1", unit_retail_cents=1000,
                                  member_price_cents=1000)
        store = make_store([item["id"]], store_code="ST8",
                           format="SMALL_FORMAT", market_tier="SECONDARY",
                           receiving_capacity_units=300)
        cust = make_customer(email="c8@x.com")
        coupon_payload = create_coupon_payload(
            code="PRN10", channel="PRINT",
            discount_type="PERCENT_OFF_BASKET", discount_value=10,
            per_customer_limit=2, budget_cents=100000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z")
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))
        set_clock("2026-09-05T10:00:00Z")

        # 1st and 2nd same-day redemptions complete fine; all activity stays
        # on the same clock day (the PRINT per-customer limit counts
        # redemptions per calendar day).
        for _ in range(2):
            s = make_open_sale(store["id"], cust["id"])
            add_line(s["id"], item["id"], 1)
            validate_success(api.apply_coupon(s["id"], "PRN10", SC))
            validate_success(api.complete_sale(s["id"], {}, SC))

        # 3rd same-day redemption: count == limit -> rejected.
        s3 = make_open_sale(store["id"], cust["id"])
        add_line(s3["id"], item["id"], 1)
        resp = api.apply_coupon(s3["id"], "PRN10", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_CUSTOMER_LIMIT_REACHED)

        # Daily reset: next day the same coupon applies again.
        set_clock("2026-09-06T00:00:01Z")
        applied = validate_success(api.apply_coupon(s3["id"], "PRN10", SC))
        assert applied["applied_coupon_id"] == coupon["id"]

    def test_email_coupon_limit_is_lifetime_not_daily(self, api):
        """PRD §3.7: "for `PRINT` coupons the limit applies per calendar day of
        redemption (the count resets daily), while for `EMAIL` and `APP`
        coupons it applies across the coupon's entire life."

        Design: Difficulty/boundary_precision_check/print_coupon_daily_limit_exact_boundary
        """
        item = create_active_item(sku="BD1E", unit_retail_cents=1000,
                                  member_price_cents=1000)
        store = make_store([item["id"]])
        cust = make_customer()
        coupon_payload = create_coupon_payload(
            code="EML1", channel="EMAIL",
            discount_type="PERCENT_OFF_BASKET", discount_value=10,
            per_customer_limit=1, budget_cents=100000)
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))
        set_clock("2026-09-05T10:00:00Z")

        s1 = make_open_sale(store["id"], cust["id"])
        add_line(s1["id"], item["id"], 1)
        validate_success(api.apply_coupon(s1["id"], "EML1", SC))
        validate_success(api.complete_sale(s1["id"], {}, SC))

        # Next day: EMAIL coupon lifetime limit still rejects.
        set_clock("2026-09-06T00:00:01Z")
        s2 = make_open_sale(store["id"], cust["id"])
        add_line(s2["id"], item["id"], 1)
        resp = api.apply_coupon(s2["id"], "EML1", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_CUSTOMER_LIMIT_REACHED)

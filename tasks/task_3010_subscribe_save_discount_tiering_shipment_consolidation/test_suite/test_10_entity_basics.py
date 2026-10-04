"""Entity-level claims: defaults, computed fields, not-found errors, and
append-only records (PRD §2.7, §2.9, §3.1, §3.2, §3.3)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_customer,
    assert_price_event,
    assert_product,
    create_customer_payload,
    create_price_event_payload,
    create_product,
    create_product_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestCustomerDefaults:
    def test_customer_create_applies_default_delivery_day_and_system_fields(self):
        """PRD §3.2: "A `PlatformAdmin` provisions a customer account with an
        `email` (unique across customers), a `full_name`, a fulfillment
        `region` code, and an optional `preferred_delivery_day` — the day of
        month on which consolidated deliveries are scheduled, between 1 and 28
        inclusive, defaulting to 15 when omitted. New accounts start `ACTIVE`
        with a `credit_balance_cents` of zero".

        Design: Corner/entities/customer_create_applies_default_delivery_day_and_system_fields
        """
        set_clock()
        payload = create_customer_payload()
        payload.pop("preferred_delivery_day")
        customer = validate_success(
            api_client.create_customer(payload, ADMIN), expected_status=201)
        assert_customer(customer)
        assert customer["preferred_delivery_day"] == 15
        assert customer["account_status"] == "ACTIVE"
        assert customer["credit_balance_cents"] == 0
        assert customer["version"] == 1


class TestProductComputedFields:
    def test_product_create_computed_fields_before_stock_and_price(self):
        """PRD §2.9: "if no such event exists, the price is undefined and the
        product is treated as having no current price. The product's
        `current_price_cents` field always reflects this resolution against
        the logical clock and is null while no effective event exists."
        PRD §2.10: "otherwise `IN_STOCK` when the sum of `on_hand_units`
        across the product's placements in the product's own region is
        greater than zero; otherwise `OUT_OF_STOCK`."
        PRD §3.1: "three optional flags: `subscription_eligible` (defaulting
        to true), `discontinued` (defaulting to false)".

        Design: Corner/entities/product_create_computed_fields_before_stock_and_price
        """
        set_clock()
        product = validate_success(api_client.create_product(
            create_product_payload(), ADMIN), expected_status=201)
        assert_product(product)
        assert product["current_price_cents"] is None
        assert product["availability_status"] == "OUT_OF_STOCK"
        assert product["subscription_eligible"] is True
        assert product["discontinued"] is False


class TestSubscriptionNotFound:
    def test_subscription_get_with_unknown_id_returns_not_found(self):
        """PRD §2.5: "(5) existence of path- and body-referenced resources,
        validated left-to-right so an outer identifier is checked before an
        inner one, each with its own not-found error".
        PRD §5: `ERR_SUBSCRIPTION_NOT_FOUND` maps to 404 Not Found.

        Design: Corner/entities/subscription_get_with_unknown_id_returns_not_found
        """
        set_clock()
        resp = api_client.get_subscription(GHOST_ID, ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND)
        assert error["error_id"] == "ERR_SUBSCRIPTION_NOT_FOUND"
        assert resp.json()["response_type"] == "error"


class TestPriceEventAppendOnly:
    def test_price_event_is_append_only_without_version_or_update(self):
        """PRD §2.7: "A PriceEvent carries only `id` and `created_at` — it is
        an immutable append-only record, so both `updated_at` and `version`
        are absent."

        Design: Corner/entities/price_event_is_append_only_without_version_or_update
        """
        set_clock()
        product = create_product()
        event = validate_success(api_client.create_price_event(
            product["id"],
            create_price_event_payload(1000, "2026-09-01T00:00:00Z"),
            ADMIN), expected_status=201)
        assert_price_event(event)
        assert "updated_at" not in event
        assert "version" not in event
        assert event["price_cents"] == 1000
        assert event["product_id"] == product["id"]


class TestSubscriptionPagination:
    def test_subscriptions_list_paginates_total_count_and_has_more(self):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of leading items and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/subscriptions_list_paginates_total_count_and_has_more
        """
        from test_helpers import (
            create_customer,
            create_stocked_product,
            create_subscription,
            make_customer_headers,
        )
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        create_subscription(customer, product, cadence_months=1,
                            start_date="2026-09-10")
        create_subscription(customer, product, cadence_months=2,
                            start_date="2026-09-11")
        create_subscription(customer, product, cadence_months=3,
                            start_date="2026-09-12")
        headers = make_customer_headers(customer["id"])
        page1, meta1 = validate_paginated(api_client.list_customer_subscriptions(
            customer["id"], headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api_client.list_customer_subscriptions(
            customer["id"], headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestCadenceMonthEndClamping:
    def test_cadence_advance_month_end_clamps_oct31_to_nov30(self):
        """PRD §3.3: "Month arithmetic everywhere in the subscription
        lifecycle uses clamped month addition: the target year and month are
        computed from the source date plus the cadence, and the day-of-month
        is the lesser of the source day and the number of days in the target
        month".
        PRD §3.5: "Every subscription consolidated into the plan immediately
        has its `next_delivery_date` advanced by its cadence per the clamped
        arithmetic of §3.3."

        Design: Corner/entities/cadence_advance_month_end_clamps_oct31_to_nov30
        """
        from test_helpers import (
            create_customer,
            create_stocked_product,
            create_subscription,
            generate_plan_for,
            get_subscription_by_id,
        )
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product, start_date="2026-10-31")
        plan = generate_plan_for(customer, "2026-10")
        assert plan["delivery_date"] == "2026-10-10"
        sub_after = get_subscription_by_id(sub["id"], customer)
        assert sub_after["next_delivery_date"] == "2026-11-30"

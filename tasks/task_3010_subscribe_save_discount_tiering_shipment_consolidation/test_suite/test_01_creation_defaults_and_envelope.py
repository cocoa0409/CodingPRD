"""Creation defaults, computed fields, append-only records, response envelope,
and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_price_event,
    create_customer_payload,
    create_price_event_payload,
    create_product_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_customer_headers,
    make_platform_admin_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestCreationDefaults:
    def test_customer_create_applies_default_delivery_day_and_system_fields(self, api):
        """PRD §3.2: "an optional `preferred_delivery_day` — the day of month on
        which consolidated deliveries are scheduled, between 1 and 28 inclusive,
        defaulting to 15 when omitted. New accounts start `ACTIVE` with a
        `credit_balance_cents` of zero".
        PRD §2.7: "`version` (integer): a system-managed counter that increments
        by exactly 1 on every mutation, powering optimistic concurrency control."

        Design: Corner/entities/customer_create_applies_default_delivery_day_and_system_fields
        """
        set_clock()
        payload = create_customer_payload()
        payload.pop("preferred_delivery_day")
        resp = api.create_customer(payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["preferred_delivery_day"] == 15
        assert data["account_status"] == "ACTIVE"
        assert data["credit_balance_cents"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_product_create_computed_fields_before_stock_and_price(self, api):
        """PRD §2.9: "if no such event exists, the price is undefined and the
        product is treated as having no current price. The product's
        `current_price_cents` field always reflects this resolution against the
        logical clock and is null while no effective event exists."
        PRD §2.10: "otherwise `IN_STOCK` when the sum of `on_hand_units` across
        the product's placements in the product's own region is greater than
        zero; otherwise `OUT_OF_STOCK`."
        PRD §3.1: "three optional flags: `subscription_eligible` (defaulting to
        true), `discontinued` (defaulting to false)".

        Design: Corner/entities/product_create_computed_fields_before_stock_and_price
        """
        set_clock()
        resp = api.create_product(create_product_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["current_price_cents"] is None
        assert data["availability_status"] == "OUT_OF_STOCK"
        assert data["subscription_eligible"] is True
        assert data["discontinued"] is False

    def test_subscription_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "existence of path- and body-referenced resources,
        validated left-to-right so an outer identifier is checked before an
        inner one, each with its own not-found error".
        PRD §5: "`ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found".

        Design: Corner/entities/subscription_get_with_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_subscription(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value, 404)
        assert resp.json()["response_type"] == "error"

    def test_price_event_is_append_only_without_version_or_update(self, api):
        """PRD §2.7: "A PriceEvent carries only `id` and `created_at` — it is an
        immutable append-only record, so both `updated_at` and `version` are
        absent."

        Design: Corner/entities/price_event_is_append_only_without_version_or_update
        """
        set_clock()
        product = get_success_data(
            api.create_product(create_product_payload(), ADMIN), 201,
        )
        resp = api.create_price_event(
            product["id"], create_price_event_payload(1000), ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert "version" not in data
        assert "updated_at" not in data
        assert_price_event(data)
        assert data["price_cents"] == 1000
        assert data["product_id"] == product["id"]


class TestEnvelopeAndPagination:
    def test_list_endpoint_uses_array_envelope_with_pagination_fields(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/list_endpoint_uses_array_envelope_with_pagination_fields
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        headers = make_customer_headers(customer["id"])
        resp = api.list_plan_lines_global(
            headers, params={"subscription_id": subs[0]["id"]},
        )
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_subscriptions_list_paginates_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of leading items and defaults to 0."

        Design: Corner/entities/subscriptions_list_paginates_total_count_and_has_more
        """
        set_clock()
        from test_helpers import (
            create_customer,
            create_stocked_product,
            create_subscription,
        )
        customer = create_customer()
        product, _ = create_stocked_product()
        create_subscription(customer, product, cadence_months=1, start_date="2026-09-10")
        create_subscription(customer, product, cadence_months=2, start_date="2026-09-11")
        create_subscription(customer, product, cadence_months=3, start_date="2026-09-12")
        headers = make_customer_headers(customer["id"])

        resp = api.list_customer_subscriptions(
            customer["id"], headers, params={"limit": 2, "offset": 0},
        )
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp = api.list_customer_subscriptions(
            customer["id"], headers, params={"limit": 2, "offset": 2},
        )
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

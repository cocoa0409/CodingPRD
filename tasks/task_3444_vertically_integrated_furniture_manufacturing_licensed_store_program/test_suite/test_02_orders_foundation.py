"""Order foundation: retrieval round-trip, list pagination and filters, 404
specificity, and buyer-shape validation (PRD §2.1, §2.3, §2.7, §2.9, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_supply_order,
    build_user_headers,
    create_licensee_order,
    create_order_payload,
    create_retail_account,
    make_wholesale_buyer_headers,
    setup_open_cycle,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderRetrieval:
    def test_order_get_round_trips_stored_fields(self, api, platform_admin_headers):
        """PRD §3.5: "A successful create returns HTTP 201 with the order priced
        provisionally: `unit_price_cents` and `provisional_total_cents` are filled, while
        `final_total_cents`, `submitted_at`, `delivered_at`, and `cancel_reason` remain
        null."
        PRD §3.5: "For a licensee buyer, the unit price is the base times (1 − 0.30),
        rounded half-up to cents"
        PRD §3.5: "orders are born `UNALLOCATED`" and "orders are born `PENDING`".
        PRD §2.1: "All read endpoints are open to all six declared roles."

        Design: Corner/entities/order_get_round_trips_stored_fields
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3
        )
        # Reads are role-agnostic: a WholesaleBuyer identity may read the order.
        reader = build_user_headers(NON_EXISTENT_UUID, "WholesaleBuyer")
        fetched = validate_success(
            api.get_order(order["id"], reader), 200
        )
        assert_supply_order(fetched)
        assert fetched["id"] == order["id"]
        # round_half_up(89900 * 0.70) == 62930; total 62930 * 3 == 188790.
        assert fetched["unit_price_cents"] == 62930
        assert fetched["provisional_total_cents"] == 188790
        assert fetched["retail_account_id"] is None
        assert fetched["licensee_id"] == ctx["licensee"]["id"]
        assert fetched["allocation_state"] == "UNALLOCATED"
        assert fetched["fulfillment_state"] == "PENDING"
        assert fetched["final_total_cents"] is None
        assert fetched["submitted_at"] is None
        assert fetched["delivered_at"] is None
        assert fetched["cancel_reason"] is None

    def test_order_get_unknown_id_returns_order_not_found(self, api, platform_admin_headers):
        """PRD §2.9: "the server resolves references in a fixed left-to-right order:
        path identifiers first, then body foreign keys in their declared field order,
        rejecting at the first unknown id with that entity's dedicated error:
        `ERR_FACTORY_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_LICENSEE_NOT_FOUND`,
        `ERR_TERRITORY_NOT_FOUND`, `ERR_RETAIL_ACCOUNT_NOT_FOUND`, `ERR_DC_NOT_FOUND`,
        `ERR_CYCLE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, or `ERR_PARTS_ORDER_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/order_get_unknown_id_returns_order_not_found
        """
        resp = api.get_order(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


class TestOrderListing:
    def test_orders_list_paginates_and_filters(self, api, platform_admin_headers):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §4: GET /api/orders carries "query params `licensee_id`, `retail_account_id`,
        `product_line_id`, `allocation_cycle_id`, `allocation_state`, `fulfillment_state`,
        `limit`, `offset`".

        Design: Corner/entities/orders_list_paginates_and_filters
        """
        ctx = setup_open_cycle()
        licensee = ctx["licensee"]
        o1 = create_licensee_order(licensee, ctx["cycle"], ctx["line"], quantity=3)
        o2 = create_licensee_order(licensee, ctx["cycle"], ctx["line"], quantity=1)
        o3 = create_licensee_order(licensee, ctx["cycle"], ctx["line"], quantity=1)
        submit_order(o2)

        page1, meta1 = validate_paginated(
            api.list_orders(
                platform_admin_headers,
                params={"licensee_id": licensee["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_orders(
                platform_admin_headers,
                params={"licensee_id": licensee["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        reserved, meta3 = validate_paginated(
            api.list_orders(
                platform_admin_headers,
                params={"licensee_id": licensee["id"], "allocation_state": "RESERVED"},
            )
        )
        assert len(reserved) == 1
        assert reserved[0]["id"] == o2["id"]

        all_orders, meta4 = validate_paginated(
            api.list_orders(
                platform_admin_headers, params={"licensee_id": licensee["id"]}
            )
        )
        assert len(all_orders) == 3
        assert meta4["limit"] == 10
        assert meta4["offset"] == 0
        assert meta4["has_more"] is False
        assert {o["id"] for o in all_orders} == {o1["id"], o2["id"], o3["id"]}


class TestOrderCreateShape:
    def test_order_create_with_version_input_ignored(self, api, platform_admin_headers):
        """PRD §2.7: "Exactly two write endpoints are guarded by optimistic concurrency
        control, and no other endpoint accepts a version field."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by
        exactly 1 on every successful mutating call against the resource."

        Design: Corner/entities/order_create_with_version_input_ignored
        """
        ctx = setup_open_cycle()
        payload = create_order_payload(
            allocation_cycle_id=ctx["cycle"]["id"],
            product_line_id=ctx["line"]["id"],
            buyer_type="LICENSEE",
            licensee_id=ctx["licensee"]["id"],
            retail_account_id=None,
            quantity=1,
            delivery_mode="FREIGHT_TO_STORE",
        )
        payload["version"] = 99
        from test_helpers import make_licensee_manager_headers

        resp = api.create_order(
            payload, make_licensee_manager_headers(ctx["licensee"]["id"])
        )
        order = validate_success(resp, 201)
        assert_supply_order(order)
        assert order["version"] != 99, (
            "client-supplied version must be ignored; version is system-managed"
        )

    def test_buyer_mismatch_licensee_with_retail_fk_rejected(self, api, platform_admin_headers):
        """PRD §3.5: "A `LicenseeManager` creates orders for their own licensee:
        `buyer_type` `LICENSEE`, a `licensee_id` equal to their `X-User-ID`, and
        `retail_account_id` null. A `WholesaleBuyer` creates for their own account:
        `buyer_type` `RETAIL_ACCOUNT`, a `retail_account_id` equal to their `X-User-ID`,
        and `licensee_id` null. Crossed foreign keys — a licensee id on a retail order
        or the reverse — are rejected with `ERR_BUYER_MISMATCH`"

        Design: Corner/entities/buyer_mismatch_licensee_with_retail_fk_rejected
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=1_000_000)
        payload = create_order_payload(
            allocation_cycle_id=ctx["cycle"]["id"],
            product_line_id=ctx["line"]["id"],
            buyer_type="LICENSEE",
            licensee_id=None,
            retail_account_id=account["id"],
            quantity=1,
            delivery_mode="FREIGHT_TO_STORE",
        )
        resp = api.create_order(
            payload, make_wholesale_buyer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BUYER_MISMATCH.value)

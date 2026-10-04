"""Order retrieval, list pagination/scoping, and entity-specific 404s."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_sales_order,
    get_order_lines,
    make_customer,
    make_order,
    make_part,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
FIELD = TEST_USERS["field_engineer_headers"]


class TestOrderReads:
    def test_order_get_round_trips_stored_fields(self, api):
        """PRD §3.4: "The order is created in `DRAFT` status with its `channel`
        snapshotted from the customer's current `channel`; each created line starts
        with `awarded_units` 0, with `unit_price_cents` and `line_total_cents` null
        while the order is in `DRAFT`, and with `allocation_run_id`,
        `allocation_rank`, and `allocation_priority_score` null until an allocation
        run awards the line."
        PRD §3.4: "`submitted_at` is likewise null while the order is in `DRAFT`."

        Design: Corner/entities/order_get_round_trips_stored_fields
        """
        part = make_part(part_number="TL072CP")
        cust = make_customer(
            name="Roundtrip Co", tier="STANDARD", channel="DIRECT_ONLINE",
            credit_limit_cents=1_000_000,
        )
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 3}])

        fetched = validate_success(api.get_order(order["id"], CHANNEL), 200)
        assert_sales_order(fetched)
        assert fetched["status"] == "DRAFT"
        assert fetched["channel"] == "DIRECT_ONLINE"
        assert fetched["customer_id"] == cust["id"]
        assert fetched["submitted_at"] is None

        lines = get_order_lines(order["id"])
        assert len(lines) == 1
        line = lines[0]
        assert line["awarded_units"] == 0
        assert line["unit_price_cents"] is None
        assert line["line_total_cents"] is None
        assert line["allocation_run_id"] is None
        assert line["allocation_rank"] is None
        assert line["allocation_priority_score"] is None
        assert line["order_id"] == order["id"]

    def test_orders_list_paginates_with_total_count_has_more_and_scope(self, api):
        """PRD §2.3: "The `meta` object of every list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a
        client can always tell how many records exist in total and whether further
        pages remain."
        PRD §3.4: "a `Customer` principal sees only its own orders in both the list
        and single-fetch views".

        Design: Corner/entities/orders_list_paginates_with_total_count_has_more_and_scope
        """
        part = make_part(part_number="LM324N")
        cust_a = make_customer(name="Paged A", credit_limit_cents=1_000_000)
        cust_b = make_customer(name="Paged B", credit_limit_cents=1_000_000)
        for qty in (1, 2, 3):
            make_order(cust_a["id"], [{"part_id": part["id"], "quantity": qty}])

        page1, meta1 = validate_paginated(
            api.list_orders(CHANNEL, params={"customer_id": cust_a["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_orders(CHANNEL, params={"customer_id": cust_a["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False

        drafts, meta3 = validate_paginated(api.list_orders(CHANNEL, params={"status": "DRAFT"}))
        assert len(drafts) == 3 and meta3["total_count"] == 3

        own, meta4 = validate_paginated(api.list_orders(make_customer_headers(cust_b["id"])))
        assert own == [] and meta4["total_count"] == 0

    def test_entity_gets_with_unknown_ids_return_specific_404(self, api):
        """PRD §2.8: "Each missing resource produces its entity-specific HTTP 404:
        `ERR_PART_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_ORDER_LINE_NOT_FOUND`, `ERR_CAPACITY_POOL_NOT_FOUND`,
        `ERR_ALLOCATION_RUN_NOT_FOUND`, `ERR_EOL_NOTICE_NOT_FOUND`,
        `ERR_LIFETIME_BUY_NOT_FOUND`, `ERR_SITE_QUALIFICATION_NOT_FOUND`,
        `ERR_REFERENCE_DESIGN_NOT_FOUND`, or `ERR_DESIGN_WIN_NOT_FOUND`."

        Design: Corner/entities/entity_gets_with_unknown_ids_return_specific_404
        """
        U = lambda s: f"00000000-0000-0000-0000-0000000000{s}"  # noqa: E731
        checks = [
            (api.get_part(U("a1"), ADMIN), ApiErrorId.ERR_PART_NOT_FOUND),
            (api.get_customer(U("a2"), ADMIN), ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api.get_order(U("a3"), ADMIN), ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_order_line(U("a4"), ADMIN), ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
            (api.get_capacity_pool(U("a5"), ADMIN), ApiErrorId.ERR_CAPACITY_POOL_NOT_FOUND),
            (api.get_lifetime_buy(U("a6"), ADMIN), ApiErrorId.ERR_LIFETIME_BUY_NOT_FOUND),
            (api.get_design_win(U("a7"), ADMIN), ApiErrorId.ERR_DESIGN_WIN_NOT_FOUND),
            (api.publish_allocation_run(U("a8"), PLANNER), ApiErrorId.ERR_ALLOCATION_RUN_NOT_FOUND),
            (api.rescind_eol_notice(U("a9"), PLANNER), ApiErrorId.ERR_EOL_NOTICE_NOT_FOUND),
            (
                api.transition_site_qualification(U("aa"), {"to_state": "IN_REVIEW"}, QUALITY),
                ApiErrorId.ERR_SITE_QUALIFICATION_NOT_FOUND,
            ),
            (api.publish_reference_design(U("ab"), FIELD), ApiErrorId.ERR_REFERENCE_DESIGN_NOT_FOUND),
        ]
        for response, error_id in checks:
            validate_error(response, error_id)

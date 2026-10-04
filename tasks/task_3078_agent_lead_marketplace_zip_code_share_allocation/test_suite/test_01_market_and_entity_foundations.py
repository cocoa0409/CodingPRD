"""Entity foundations: creation defaults, computed read purity, not-found, pagination,
required-field and enum validation, and append-only payment immutability."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_listing,
    create_agent_payload,
    create_brokerage,
    create_agent,
    create_market,
    create_market_payload,
    create_share_order,
    get_lead,
    get_market,
    get_share_order,
    get_success_data,
    make_agent_headers,
    set_clock,
    setup_assigned_lead,
    setup_market_with_active_order,
    create_routed_lead,
    accept_lead_offer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMarketCreation:
    def test_market_create_returns_defaults_and_system_fields(self, api, platform_admin_headers):
        """PRD §3.1: "a `participation_agreement` (one of `IDX_FULL`, `IDX_LIMITED`, or
        `NON_PARTICIPATING`, defaulting to `IDX_FULL` when not supplied)".
        PRD §3.1: "A market's `market_status` begins at `OPEN`."
        PRD §2.5: "Every market has a fixed share capacity of 10000 basis points. A `Market`
        carries two derived counters: `allocated_bps`, the sum of `share_bps` over that
        market's orders whose `order_status` is `ACTIVE`, and `available_bps`, which is
        10000 minus `allocated_bps`."

        Design: Corner/entities/market_create_returns_defaults_and_system_fields
        """
        set_clock()
        resp = api.create_market(
            create_market_payload(zip_code="90210", state_code="CA"), platform_admin_headers
        )
        market = validate_success(resp, 201)
        assert market["participation_agreement"] == "IDX_FULL"
        assert market["market_status"] == "OPEN"
        assert market["allocated_bps"] == 0
        assert market["available_bps"] == 10000
        assert market["version"] == 1
        assert market["id"] and market["created_at"] and market["updated_at"]

    def test_market_create_rejects_client_injected_status_and_counters(self, api, platform_admin_headers):
        """PRD §3.1: "A market's `market_status` begins at `OPEN`."
        PRD §2.5: "`available_bps`, which is 10000 minus `allocated_bps`."

        Design: Corner/entities/market_create_returns_defaults_and_system_fields
        """
        set_clock()
        payload = create_market_payload(zip_code="90211", state_code="CA")
        payload.update({"market_status": "SUSPENDED", "allocated_bps": 7000, "available_bps": 0})
        market = validate_success(api.create_market(payload, platform_admin_headers), 201)
        assert market["market_status"] == "OPEN"
        assert market["allocated_bps"] == 0
        assert market["available_bps"] == 10000

    def test_market_get_unknown_id_returns_404(self, api, marketplace_ops_headers):
        """PRD §2.9: "The request is rejected with the `404 Not Found` error corresponding
        to the first identifier that does not resolve to an existing resource of the
        expected type. Per-entity not-found errors are: `ERR_MARKET_NOT_FOUND` ..."

        Design: Corner/entities/market_get_unknown_id_returns_404
        """
        set_clock()
        resp = api.get_market(NON_EXISTENT_UUID, marketplace_ops_headers)
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_FOUND, 404)


class TestAgentCreation:
    def test_agent_create_ignores_counter_input_and_defaults(self, api, platform_admin_headers):
        """PRD §3.2: "New agents start in `ACTIVE` status with `performance_tier` of
        `UNRATED` and an `official_score` of zero. Their counters — `offers_received`,
        `offers_accepted`, `offers_expired`, `response_seconds_sum`, `leads_converted`,
        `leads_closed_lost`, `connections_missed`, `rating_sum`, `rating_count` — all
        start at zero, and their `rolling_score` is recomputed on every scoring event
        from these all-time counters."

        Design: Corner/entities/agent_create_ignores_counter_input_and_defaults
        """
        set_clock()
        brokerage = create_brokerage()
        payload = create_agent_payload(brokerage["id"])
        payload.update(
            {"offers_received": 99, "rolling_score": 88, "performance_tier": "HIGH",
             "official_score": 77, "agent_status": "SUSPENDED", "rating_sum": 50}
        )
        agent = validate_success(api.create_agent(payload, platform_admin_headers), 201)
        assert agent["offers_received"] == 0
        assert agent["offers_accepted"] == 0
        assert agent["offers_expired"] == 0
        assert agent["rolling_score"] == 0
        assert agent["official_score"] == 0
        assert agent["performance_tier"] == "UNRATED"
        assert agent["agent_status"] == "ACTIVE"
        assert agent["rating_sum"] == 0
        assert agent["rating_count"] == 0

    def test_fresh_agent_zero_counters_via_setup(self, api, platform_admin_headers):
        """PRD §3.2: "Their counters — `offers_received`, `offers_accepted`,
        `offers_expired`, `response_seconds_sum`, `leads_converted`, `leads_closed_lost`,
        `connections_missed`, `rating_sum`, `rating_count` — all start at zero".

        Design: Corner/entities/agent_create_ignores_counter_input_and_defaults
        """
        set_clock()
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        for counter in (
            "offers_received", "offers_accepted", "offers_expired", "response_seconds_sum",
            "leads_converted", "leads_closed_lost", "connections_missed",
            "rating_sum", "rating_count", "rolling_score", "official_score",
        ):
            assert agent[counter] == 0, f"expected fresh {counter} == 0, got {agent[counter]}"


class TestLeadListingPagination:
    def test_leads_list_paginates_and_filters(self, api, marketplace_ops_headers):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` and `offset`.
        `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        defaults to 0. Unless otherwise specified, list endpoints return resources sorted
        by their `created_at` timestamp in ascending order. The `meta` object of the
        response envelope for a list endpoint always includes `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/leads_list_paginates_and_filters
        """
        set_clock()
        market, brokerage, agent, _ = setup_market_with_active_order(zip_code="96001", state_code="CA")
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        for key in ("pg1@x.com", "pg2@x.com", "pg3@x.com"):
            create_routed_lead(market["id"], key, listing)
        page1, meta1 = validate_paginated(
            api.list_leads(marketplace_ops_headers, params={"market_id": market["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_leads(marketplace_ops_headers, params={"market_id": market["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        routed, meta3 = validate_paginated(
            api.list_leads(marketplace_ops_headers, params={"market_id": market["id"], "lead_status": "ROUTED"})
        )
        assert meta3["total_count"] == 3
        _, meta4 = validate_paginated(
            api.list_leads(marketplace_ops_headers, params={"market_id": market["id"], "lead_status": "CLOSED_LOST"})
        )
        assert meta4["total_count"] == 0

    def test_leads_list_limit_offset_window(self, api, marketplace_ops_headers):
        """PRD §2.3: "The `meta` object of the response envelope for a list endpoint
        always includes `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/leads_list_paginates_and_filters
        """
        set_clock()
        market, brokerage, agent, _ = setup_market_with_active_order(zip_code="96002", state_code="CA")
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        for key in ("w1@x.com", "w2@x.com", "w3@x.com"):
            create_routed_lead(market["id"], key, listing)
        page, meta = validate_paginated(
            api.list_leads(marketplace_ops_headers, params={"market_id": market["id"], "limit": 1, "offset": 1})
        )
        assert len(page) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


class TestValidationErrors:
    def test_share_order_missing_required_field_returns_400(self, api):
        """PRD §2.1: "A request whose body is malformed, missing a required field, or
        violates a field-level constraint (an enum outside its allowed set, a range
        violation, or a format violation) is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/share_order_missing_required_field_returns_400
        """
        set_clock()
        market = create_market(zip_code="97035", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        resp = api.create_share_order(
            {"market_id": market["id"], "buyer_agent_id": agent["id"], "duration_days": 30},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_invalid_enum_on_lead_close_returns_400(self, api):
        """PRD §2.1: "A request whose body is malformed, missing a required field, or
        violates a field-level constraint (an enum outside its allowed set, a range
        violation, or a format violation) is rejected with `ERR_VALIDATION` (HTTP 400)."
        PRD §3.9: "The assigned agent closes a lead by reporting an `outcome` of
        `CONVERTED` or `LOST`."

        Design: Corner/entities/invalid_enum_on_lead_close_returns_400
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(zip_code="97209")
        resp = api.close_lead(lead["id"], {"outcome": "MAYBE"}, make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        assert get_lead(lead["id"])["lead_status"] == "ASSIGNED"


class TestPaymentImmutability:
    def test_payment_entity_is_immutable_no_update(self, api, marketplace_ops_headers):
        """PRD §2.10: "The remaining resources — `Payment`, `CallRecording`, `Rating`,
        `PerformanceSnapshot`, and `OpsRun` — are append-only and carry only `id` and
        `created_at`. They do not have `updated_at` or `version` fields."
        PRD §3.3: "A `DECLINED` outcome transitions the order to `PAYMENT_FAILED` and
        leaves the market's counters untouched."
        PRD §3.3: "a `payment_status` that mirrors the outcome and is immutable once recorded."

        Design: Corner/entities/payment_entity_is_immutable_no_update
        """
        set_clock()
        market, brokerage, agent, _ = setup_market_with_active_order(zip_code="98109", state_code="WA")
        # build a fresh PENDING order for the same agent and decline it
        order = create_share_order(market["id"], agent["id"], share_bps=1000)
        current_market = get_market(market["id"])
        decline = api.capture_payment(
            order["id"],
            {"amount_cents": order["deposit_cents"], "outcome": "DECLINED",
             "expected_market_version": current_market["version"]},
            make_agent_headers(agent["id"]),
        )
        validate_success(decline, 201)
        payments, _ = validate_paginated(api.list_order_payments(order["id"], marketplace_ops_headers))
        assert len(payments) == 1
        assert payments[0]["payment_status"] == "DECLINED"
        assert "version" not in payments[0]
        assert "updated_at" not in payments[0]
        assert get_share_order(order["id"])["order_status"] == "PAYMENT_FAILED"
        again = api.capture_payment(
            order["id"],
            {"amount_cents": order["deposit_cents"], "outcome": "SUCCEEDED",
             "expected_market_version": get_market(market["id"])["version"]},
            make_agent_headers(agent["id"]),
        )
        validate_error(again, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_declined_payment_cannot_be_flipped(self, api, marketplace_ops_headers):
        """PRD §3.3: "a `payment_status` that mirrors the outcome and is immutable once recorded."
        PRD §3.3: "A `DECLINED` outcome transitions the order to `PAYMENT_FAILED` and
        leaves the market's counters untouched."

        Design: Corner/entities/payment_entity_is_immutable_no_update
        """
        set_clock()
        market, brokerage, agent, _ = setup_market_with_active_order(zip_code="98110", state_code="WA")
        allocated_before = get_market(market["id"])["allocated_bps"]
        order = create_share_order(market["id"], agent["id"], share_bps=500)
        api.capture_payment(
            order["id"],
            {"amount_cents": order["deposit_cents"], "outcome": "DECLINED",
             "expected_market_version": get_market(market["id"])["version"]},
            make_agent_headers(agent["id"]),
        )
        market_after = get_market(market["id"])
        assert market_after["allocated_bps"] == allocated_before, (
            "DECLINED payment must leave market counters untouched"
        )
        payments, _ = validate_paginated(api.list_order_payments(order["id"], marketplace_ops_headers))
        assert [p["payment_status"] for p in payments] == ["DECLINED"]


class TestPriceQuoteComputedRead:
    def test_price_quote_is_computed_read(self, api, marketplace_ops_headers):
        """PRD §3.3: "a caller may ask what `tier`, `unit_price_cents`, and `deposit_cents`
        would apply for a hypothetical `share_bps` against the market's current allocation,
        and the response contains exactly those three integers."
        PRD §2.5: "Each such mutation recomputes the market's `current_unit_price_cents`
        and increments the market's `version`."

        Design: Corner/endpoints/price_quote_is_computed_read
        """
        set_clock()
        market = create_market(zip_code="97218", state_code="OR")
        quote_a = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 1000))
        quote_b = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 1000))
        assert quote_a["unit_price_cents"] == quote_b["unit_price_cents"] == 10000
        assert quote_a["tier"] == 1
        assert get_market(market["id"])["version"] == 1, "a computed read must not mutate the market"

    def test_price_quote_response_shape(self, api, marketplace_ops_headers):
        """PRD §3.3: "the response contains exactly those three integers" (tier,
        unit_price_cents, deposit_cents).

        Design: Corner/endpoints/price_quote_is_computed_read
        """
        set_clock()
        market = create_market(zip_code="97228", state_code="OR")
        quote = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 2500))
        assert quote["tier"] == 1
        assert quote["unit_price_cents"] == 9500  # floor(10000 * 0.95)
        assert quote["deposit_cents"] == 950000  # 1 * 100 * 9500

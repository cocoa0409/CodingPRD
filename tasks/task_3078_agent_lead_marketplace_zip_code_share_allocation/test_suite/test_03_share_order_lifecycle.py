"""Share order lifecycle: pause/resume cycle, capacity, conservation invariant,
payment exactness, and optimistic concurrency on the market (PRD §2.5, §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_brokerage,
    create_market,
    create_share_order,
    get_market,
    get_share_order,
    make_agent_headers,
    set_clock,
    setup_market_with_active_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPauseResumeCycle:
    def test_pause_releases_capacity_and_resume_recapacity_checks(self, api, marketplace_ops_headers):
        """PRD §3.3: "The buyer may pause an `ACTIVE` order, which releases its share back
        to the market — `allocated_bps` decreases, `current_unit_price_cents` is
        recomputed, and the market's `version` increments — and may later resume a
        `PAUSED` order, which re-checks capacity against the market's `available_bps` at
        the resume instant."
        PRD §2.5: "The same re-check applies on resume."

        Design: Difficulty/non_linear_state_machine/share_order_pause_resume_cycle
        """
        set_clock()
        market, brokerage, agent_a, order_a = setup_market_with_active_order(
            zip_code="80202", state_code="CO", share_bps=6000
        )
        agent_b = create_agent(brokerage["id"], license_state="CO")
        # 6000 + 4001 = 10001 > 10000, so A's resume must fail once B is active.
        order_b = create_share_order(market["id"], agent_b["id"], share_bps=4001)
        validate_success(api.pause_share_order(order_a["id"], make_agent_headers(agent_a["id"])))
        market_mid = get_market(market["id"])
        assert market_mid["allocated_bps"] == 0
        assert get_share_order(order_a["id"])["order_status"] == "PAUSED"
        # B activates while A is paused — the pause released capacity.
        validate_success(
            api.capture_payment(
                order_b["id"],
                {"amount_cents": order_b["deposit_cents"], "outcome": "SUCCEEDED",
                 "expected_market_version": market_mid["version"]},
                make_agent_headers(agent_b["id"]),
            ),
            201,
        )
        assert get_market(market["id"])["allocated_bps"] == 4001
        # A's resume of 6000 would exceed capacity against B's 4001.
        resp = api.resume_share_order(order_a["id"], make_agent_headers(agent_a["id"]))
        validate_error(resp, ApiErrorId.ERR_SHARE_CAPACITY_EXCEEDED, 422)
        assert get_share_order(order_a["id"])["order_status"] == "PAUSED"

    def test_pause_then_cancel_releases_share_once(self, api, marketplace_ops_headers):
        """PRD §3.3: "A paused order may be cancelled outright, moving it to `CANCELLED`
        with no further market-counter change (the share was already released at pause)."

        Design: Difficulty/non_linear_state_machine/share_order_pause_resume_cycle
        """
        set_clock()
        market, _, agent, order = setup_market_with_active_order(
            zip_code="80203", state_code="CO", share_bps=6000
        )
        validate_success(api.pause_share_order(order["id"], make_agent_headers(agent["id"])))
        assert get_market(market["id"])["allocated_bps"] == 0
        validate_success(api.cancel_share_order(order["id"], make_agent_headers(agent["id"])))
        cancelled = get_share_order(order["id"])
        assert cancelled["order_status"] == "CANCELLED"
        assert get_market(market["id"])["allocated_bps"] == 0, "cancel after pause must not double-release"


class TestCapacityBoundary:
    def test_capacity_exact_fit_then_one_bps_over(self, api, marketplace_ops_headers):
        """PRD §2.5: "A buy request whose `share_bps` would push the aggregate over 10000
        at the activation or resume instant is rejected with `ERR_SHARE_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/share_capacity_disjoint_segments
        """
        set_clock()
        market, brokerage, agent1, _ = setup_market_with_active_order(
            zip_code="22201", state_code="VA", share_bps=6000
        )
        agent2 = create_agent(brokerage["id"], license_state="VA")
        agent3 = create_agent(brokerage["id"], license_state="VA")
        order2 = create_share_order(market["id"], agent2["id"], share_bps=4000)
        validate_success(
            api.capture_payment(
                order2["id"],
                {"amount_cents": order2["deposit_cents"], "outcome": "SUCCEEDED",
                 "expected_market_version": get_market(market["id"])["version"]},
                make_agent_headers(agent2["id"]),
            ),
            201,
        )
        market_full = get_market(market["id"])
        assert market_full["allocated_bps"] == 10000, "6000 + 4000 fits exactly"
        assert market_full["available_bps"] == 0
        order3 = create_share_order(market["id"], agent3["id"], share_bps=1)
        resp = api.capture_payment(
            order3["id"],
            {"amount_cents": order3["deposit_cents"], "outcome": "SUCCEEDED",
             "expected_market_version": market_full["version"]},
            make_agent_headers(agent3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHARE_CAPACITY_EXCEEDED, 422)

    def test_full_capacity_market_reports_zero_available(self, api, marketplace_ops_headers):
        """PRD §2.5: "Every market has a fixed share capacity of 10000 basis points."

        Design: Difficulty/resource_temporal_overlap/share_capacity_disjoint_segments
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="22202", state_code="VA", share_bps=10000
        )
        fresh = get_market(market["id"])
        assert fresh["allocated_bps"] == 10000
        assert fresh["available_bps"] == 0


class TestShareConservation:
    def test_activate_pause_resume_round_trip_conserves_share(self, api, marketplace_ops_headers):
        """PRD §2.5: "When an order transitions into `ACTIVE`, its `share_bps` is added to
        `allocated_bps`; when an order leaves `ACTIVE` (pause, completion, or
        expiry-cancel), its `share_bps` is subtracted."

        Design: Difficulty/compensating_invariant/market_share_conservation
        """
        set_clock()
        market, _, agent, order = setup_market_with_active_order(
            zip_code="19101", state_code="PA", share_bps=6000
        )
        m1 = get_market(market["id"])
        assert m1["allocated_bps"] == 6000 and m1["available_bps"] == 4000
        validate_success(api.pause_share_order(order["id"], make_agent_headers(agent["id"])))
        m2 = get_market(market["id"])
        assert m2["allocated_bps"] == 0 and m2["available_bps"] == 10000
        validate_success(api.resume_share_order(order["id"], make_agent_headers(agent["id"])))
        m3 = get_market(market["id"])
        assert m3["allocated_bps"] == 6000 and m3["available_bps"] == 4000
        assert m3["allocated_bps"] + m3["available_bps"] == 10000
        assert get_share_order(order["id"])["order_status"] == "ACTIVE"

    def test_second_pause_resume_cycle_still_conserves(self, api, marketplace_ops_headers):
        """PRD §2.5: "`available_bps`, which is 10000 minus `allocated_bps`."

        Design: Difficulty/compensating_invariant/market_share_conservation
        """
        set_clock()
        market, _, agent, order = setup_market_with_active_order(
            zip_code="19102", state_code="PA", share_bps=6000
        )
        for _ in range(2):
            validate_success(api.pause_share_order(order["id"], make_agent_headers(agent["id"])))
            validate_success(api.resume_share_order(order["id"], make_agent_headers(agent["id"])))
        fresh = get_market(market["id"])
        assert fresh["allocated_bps"] == 6000
        assert fresh["available_bps"] == 4000
        assert fresh["allocated_bps"] + fresh["available_bps"] == 10000


class TestPaymentAmountExactness:
    def test_overpay_by_one_cent_rejected(self, api):
        """PRD §3.3: "The amount must equal the deposit exactly, and the order must not
        already have a `SUCCEEDED` payment on file; a mismatch is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/payment_amount_must_equal_deposit
        """
        set_clock()
        market, _, agent, _ = setup_market_with_active_order(zip_code="97217", state_code="OR")
        order = create_share_order(market["id"], agent["id"], share_bps=1000)
        resp = api.capture_payment(
            order["id"],
            {"amount_cents": order["deposit_cents"] + 1, "outcome": "SUCCEEDED",
             "expected_market_version": get_market(market["id"])["version"]},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)
        assert get_share_order(order["id"])["order_status"] == "PENDING_PAYMENT"
        assert get_market(market["id"])["version"] == 2, "rejected payment must not mutate the market"

    def test_underpay_by_one_cent_rejected(self, api):
        """PRD §3.3: "The amount must equal the deposit exactly ... a mismatch is rejected
        with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/payment_amount_must_equal_deposit
        """
        set_clock()
        market, _, agent, _ = setup_market_with_active_order(zip_code="97218", state_code="OR")
        order = create_share_order(market["id"], agent["id"], share_bps=1000)
        resp = api.capture_payment(
            order["id"],
            {"amount_cents": order["deposit_cents"] - 1, "outcome": "SUCCEEDED",
             "expected_market_version": get_market(market["id"])["version"]},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)
        assert get_share_order(order["id"])["order_status"] == "PENDING_PAYMENT"


class TestStaleMarketVersion:
    def test_stale_expected_market_version_rejected_then_retry_succeeds(self, api):
        """PRD §2.7: "Capturing a payment against a share order requires the request body
        to carry `expected_market_version` matching the current `version` of the order's
        parent `Market`. If the market's version has advanced since the client last
        observed it — for example because another writer activated, paused, or resumed an
        order in the same market and so mutated `allocated_bps`, or an ops run swept
        expirations — the capture is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_market_version_triggerable
        """
        set_clock()
        market, brokerage, agent1, order1 = setup_market_with_active_order(
            zip_code="97221", state_code="OR", share_bps=6000
        )
        # PRD §2.5: activation increments the market's version, so the version
        # observed before activation is stale by the time order1 is ACTIVE.
        stale_version = market["version"] - 1
        agent2 = create_agent(brokerage["id"], license_state="OR")
        order2 = create_share_order(market["id"], agent2["id"], share_bps=2000)
        resp = api.capture_payment(
            order2["id"],
            {"amount_cents": order2["deposit_cents"], "outcome": "SUCCEEDED",
             "expected_market_version": stale_version},
            make_agent_headers(agent2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MARKET_VERSION, 412)
        assert get_share_order(order2["id"])["order_status"] == "PENDING_PAYMENT"
        # Retry with the fresh version succeeds.
        fresh_version = get_market(market["id"])["version"]
        retry = api.capture_payment(
            order2["id"],
            {"amount_cents": order2["deposit_cents"], "outcome": "SUCCEEDED",
             "expected_market_version": fresh_version},
            make_agent_headers(agent2["id"]),
        )
        validate_success(retry, 201)
        assert get_share_order(order2["id"])["order_status"] == "ACTIVE"

    def test_activation_increments_market_version(self, api):
        """PRD §2.7: "If the market's version has advanced since the client last observed
        it — for example because another writer activated, paused, or resumed an order in
        the same market and so mutated `allocated_bps` ... the capture is rejected with
        `ERR_STALE_MARKET_VERSION` (HTTP 412)."
        PRD §2.5: "Each such mutation recomputes the market's `current_unit_price_cents`
        and increments the market's `version`."

        Design: Corner/errors/error_stale_market_version_triggerable
        """
        set_clock()
        market, brokerage, agent1, _ = setup_market_with_active_order(
            zip_code="97222", state_code="OR", share_bps=6000
        )
        v_before = get_market(market["id"])["version"]
        agent2 = create_agent(brokerage["id"], license_state="OR")
        order2 = create_share_order(market["id"], agent2["id"], share_bps=1000)
        validate_success(
            api.capture_payment(
                order2["id"],
                {"amount_cents": order2["deposit_cents"], "outcome": "SUCCEEDED",
                 "expected_market_version": v_before},
                make_agent_headers(agent2["id"]),
            ),
            201,
        )
        assert get_market(market["id"])["version"] == v_before + 1


class TestLicenseGate:
    def test_license_mismatch_blocks_purchase(self, api):
        """PRD §2.6: "To buy share in a market, to be eligible as a routing candidate in
        that market, or to be manually assigned a lead in that market, the agent's
        `license_state` must equal the market's `state_code`. A mismatch is rejected with
        `ERR_LICENSE_STATE_MISMATCH` (HTTP 422) on share purchase, on offer acceptance,
        and on manual assignment."

        Design: Corner/validations/license_mismatch_blocks_purchase
        """
        set_clock()
        market = create_market(zip_code="90001", state_code="CA")
        brokerage = create_brokerage(primary_state="TX")
        agent = create_agent(brokerage["id"], license_state="TX")
        resp = api.create_share_order(
            {"market_id": market["id"], "buyer_agent_id": agent["id"],
             "share_bps": 1000, "duration_days": 30},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_STATE_MISMATCH, 422)
        orders, meta = validate_paginated(
            api.list_share_orders(make_agent_headers(agent["id"]), params={"market_id": market["id"]})
        )
        assert meta["total_count"] == 0

    def test_license_match_allows_purchase(self, api):
        """PRD §2.6: "the agent's `license_state` must equal the market's `state_code`."

        Design: Corner/validations/license_mismatch_blocks_purchase
        """
        set_clock()
        market, _, agent, order = setup_market_with_active_order(
            zip_code="90002", state_code="CA", share_bps=1000
        )
        assert order["order_status"] == "ACTIVE"
        assert order["market_id"] == market["id"]

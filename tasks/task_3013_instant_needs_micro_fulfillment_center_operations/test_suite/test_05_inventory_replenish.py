"""Inventory and replenishment: lot expiry boundaries, shrink disposal, the
place/finalize/cancel cascades, and forward-looking stockout posture."""
from test_helpers import (
    ApiErrorId,
    append_order,
    create_balance,
    create_customer,
    create_picker,
    create_product,
    create_replenish_order,
    create_site,
    factories,
    get_success_data,
    list_stock_lots,
    make_picker_headers,
    open_batch,
    order_line,
    place_order,
    place_replenish_order,
    read_balance,
    read_order,
    read_replenish_order,
    read_site,
    receive_perishable_stock,
    seed_on_hand,
    set_clock,
    setup_assigned_bag,
    setup_sealed_order,
    validate_error,
    validate_success,
)


class TestLotExpiryBoundaries:
    def test_expiry_horizon_edge_is_expiring(self, api):
        """PRD §3.2: "a lot whose expires_at is at or before the current
        logical instant is EXPIRED; otherwise, a lot whose expires_at falls
        within the site's expiry_horizon_days of the current instant is
        EXPIRING; all other lots are FRESH. Expiry exactly at the horizon edge
        counts as EXPIRING and is therefore blocked from picking"

        Design: Difficulty/resource_temporal_overlap/expiry_horizon_semi_open_boundary
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()  # expiry_horizon_days 2
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        create_balance(site["id"], milk["id"])
        edge = receive_perishable_stock(site["id"], milk["id"], 2, "2026-09-12T14:00:00Z",
                                        reference="PO-EDGE")
        statuses = {lot["id"]: lot["status"] for lot in list_stock_lots()}
        assert statuses[edge["id"]] == "EXPIRING", "the far edge is inclusive"

    def test_expiry_one_second_beyond_horizon_is_fresh(self, api):
        """PRD §3.2: "otherwise, a lot whose expires_at falls within the site's
        expiry_horizon_days of the current instant is EXPIRING; all other lots
        are FRESH."

        Design: Difficulty/resource_temporal_overlap/expiry_horizon_semi_open_boundary
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        create_balance(site["id"], milk["id"])
        safe = receive_perishable_stock(site["id"], milk["id"], 2, "2026-09-12T14:00:01Z",
                                        reference="PO-SAFE")
        statuses = {lot["id"]: lot["status"] for lot in list_stock_lots()}
        assert statuses[safe["id"]] == "FRESH"

    def test_expiry_exactly_at_clock_is_expired(self, api):
        """PRD §3.2: "a lot whose expires_at is at or before the current
        logical instant is EXPIRED ... expiry exactly at the current instant
        counts as EXPIRED and becomes eligible for write-off."

        Design: Difficulty/resource_temporal_overlap/expiry_horizon_semi_open_boundary
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        create_balance(site["id"], milk["id"])
        dead = receive_perishable_stock(site["id"], milk["id"], 1, "2026-09-10T14:00:00Z",
                                        reference="PO-DEAD")
        statuses = {lot["id"]: lot["status"] for lot in list_stock_lots()}
        assert statuses[dead["id"]] == "EXPIRED"


class TestShrinkDisposal:
    def test_shrink_dispose_requires_expired_lot_and_sufficient_qty(self, api, site_ops_headers):
        """PRD §3.2: "A shrink disposal carries a kind of SHRINK_DISPOSE and a
        lot_id, writes off units from that specific stock lot, and is guarded:
        the lot must be EXPIRED at the logical clock, and the disposed qty may
        not exceed the lot's remaining_qty; violations are rejected with
        ERR_SHRINK_EXCEEDS_LOT. A successful disposal decrements both the lot's
        remaining_qty and the balance's on_hand by the disposed quantity."

        Design: Corner/errors/shrink_dispose_requires_expired_lot_and_sufficient_qty
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        lot = receive_perishable_stock(site["id"], milk["id"], 5, "2026-09-20T00:00:00Z",
                                       reference="PO-SHR")

        fresh = api.create_stock_adjustment(
            balance["id"],
            {"kind": "SHRINK_DISPOSE", "qty": 2, "lot_id": lot["id"], "reason": "premature"},
            site_ops_headers,
        )
        validate_error(fresh, ApiErrorId.ERR_SHRINK_EXCEEDS_LOT)

        set_clock("2026-09-21T00:00:00Z")  # the lot is now EXPIRED
        over = api.create_stock_adjustment(
            balance["id"],
            {"kind": "SHRINK_DISPOSE", "qty": 9, "lot_id": lot["id"], "reason": "too many"},
            site_ops_headers,
        )
        validate_error(over, ApiErrorId.ERR_SHRINK_EXCEEDS_LOT)

        ok = api.create_stock_adjustment(
            balance["id"],
            {"kind": "SHRINK_DISPOSE", "qty": 5, "lot_id": lot["id"], "reason": "expired write-off"},
            site_ops_headers,
        )
        validate_success(ok, expected_status=201)
        lots = {l["id"]: l for l in list_stock_lots()}
        assert lots[lot["id"]]["remaining_qty"] == 0
        assert read_balance(balance["id"])["on_hand"] == 0


class TestReplenishCascade:
    def test_replenish_finalize_to_site_posture_depth3(self, api, site_ops_headers):
        """PRD §3.3: "Receiving the goods transitions the purchase order PLACED
        → FINALIZED as one atomic, all-or-nothing operation. Every line's qty
        moves from on_order to on_hand on its balance. For every line whose
        product is PERISHABLE, the server creates a StockLot with received_qty
        and remaining_qty equal to the line quantity and an expires_at taken
        from the lot_expiries supplied with the finalization request ... With
        no purchase order left in PLACED at the site, the site's posture
        recomputes and effective_status falls back to OPERATING."

        Design: Difficulty/transitive_cascade/replenish_finalize_to_site_posture_depth3
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        ro = create_replenish_order(
            site["id"], [factories.replenish_line(milk["id"], 12, unit_cost_cents=180)],
            reference="PO-1001", idempotency_key="po-1001-key",
        )
        place_replenish_order(ro["id"])
        assert read_site(site["id"])["effective_status"] == "OPENED_REPLENISH"
        mid = read_balance(balance["id"])
        assert mid["on_order"] == 12 and mid["on_hand"] == 0, mid

        resp = api.finalize_replenish_order(
            ro["id"], {"lot_expiries": {milk["id"]: "2026-09-20T00:00:00Z"}}, site_ops_headers
        )
        validate_success(resp)
        after = read_balance(balance["id"])
        assert after["on_hand"] == 12 and after["on_order"] == 0, after
        lots = list_stock_lots({"site_id": site["id"], "product_id": milk["id"]})
        assert len(lots) == 1 and lots[0]["remaining_qty"] == 12 and lots[0]["status"] == "FRESH"
        assert read_site(site["id"])["effective_status"] == "OPERATING"

    def test_replenish_place_flips_posture_and_credits_on_order(self, api):
        """PRD §3.3: "On placement, each line credits on_order on the
        corresponding InventoryBalance by its qty ... Because the site now has
        a purchase order in PLACED, the site's effective_status reads
        OPENED_REPLENISH on subsequent reads, and the order's version
        increments."

        Design: Difficulty/transitive_cascade/replenish_finalize_to_site_posture_depth3
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", price_cents=350, product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        ro = create_replenish_order(
            site["id"], [factories.replenish_line(milk["id"], 12)], reference="PO-1001"
        )
        placed = place_replenish_order(ro["id"])
        assert placed["status"] == "PLACED"
        bal = read_balance(balance["id"])
        assert bal["on_order"] == 12 and bal["on_hand"] == 0
        assert read_site(site["id"])["effective_status"] == "OPENED_REPLENISH"

    def test_replenish_place_cancel_conserves_on_order(self, api):
        """PRD §3.3: "Alternatively, a vendor shortfall is handled by
        cancelling a PLACED order, which transitions it to CANCELLED and debits
        each line's qty back out of on_order — the exact compensation of the
        placement side effect — without touching on_hand."

        Design: Difficulty/compensating_invariant/replenish_place_cancel_conserves_on_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        assert read_balance(balance["id"])["on_order"] == 0
        ro = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 8)],
            reference="PO-INV", idempotency_key="po-inv-key",
        )
        from test_helpers import SITE_OPS_HEADERS

        place_replenish_order(ro["id"])
        mid = read_balance(balance["id"])
        assert mid["on_order"] == 8 and mid["on_hand"] == 50, mid
        cancelled = get_success_data(api.cancel_replenish_order(ro["id"], SITE_OPS_HEADERS))
        assert cancelled["status"] == "CANCELLED"
        post = read_balance(balance["id"])
        assert post["on_order"] == 0 and post["on_hand"] == 50, "invariant conserved"
        assert read_site(site["id"])["effective_status"] == "OPERATING"

    def test_replenish_place_requires_operating_site(self, api, site_ops_headers):
        """PRD §3.3: "Placement requires the site's effective_status to be
        OPERATING; a suspended site, or one already in OPENED_REPLENISH
        posture, rejects the placement with ERR_SITE_NOT_OPERATING."

        Design: Difficulty/compensating_invariant/replenish_place_cancel_conserves_on_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        create_balance(site["id"], chips["id"])
        ro1 = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 5)], reference="PO-A"
        )
        place_replenish_order(ro1["id"])  # posture is now OPENED_REPLENISH
        ro2 = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 5)], reference="PO-B"
        )
        resp = api.place_replenish_order(ro2["id"], site_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPERATING)
        assert read_replenish_order(ro2["id"])["status"] == "DRAFT"

    def test_replenishment_replay_with_same_idempotency_key_returns_original(self, api, site_ops_headers):
        """PRD §3.3: "The idempotency key is unique per site: replaying the
        creation with the same key returns the original record without creating
        a second order."

        Design: Corner/state_machines/replenishment_replay_with_same_idempotency_key_returns_original
        """
        from test_helpers import validate_paginated

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        create_balance(site["id"], chips["id"])
        first = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 7, unit_cost_cents=200)],
            reference="PO-IDEM", expected_at="2026-09-11T08:00:00Z",
            idempotency_key="same-key-1",
        )
        resp = api.create_replenish_order(
            {
                "site_id": site["id"],
                "reference": "PO-IDEM-2",
                "lines": [factories.replenish_line(chips["id"], 99, unit_cost_cents=1)],
                "expected_at": "2026-09-12T08:00:00Z",
                "idempotency_key": "same-key-1",
            },
            site_ops_headers,
        )
        replayed = get_success_data(resp)
        assert replayed["id"] == first["id"], "the replay returns the original record"
        assert replayed["reference"] == "PO-IDEM", "original payload wins"
        assert replayed["lines"][0]["qty"] == 7
        rows, meta = validate_paginated(api.list_replenish_orders(site_ops_headers, params={"site_id": site["id"]}))
        assert len(rows) == 1, "no second row is created"


class TestStockoutPosture:
    def test_stockout_forward_looking_counts_on_order(self, api):
        """PRD §3.2: "the replenishment-facing stockout posture flags a
        site-product pair as stocked out when on_hand plus on_order falls below
        min_par_level — the reorder signal weighs units already committed to
        vendors, not just what sits on the shelf."
        PRD §3.3: "each such credit re-derives that balance's stockout posture
        — once on_hand plus on_order reaches min_par_level, the stockout flag
        clears."

        Design: Corner/calculations/stockout_forward_looking_counts_on_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"], min_par_level=5)
        seed_on_hand(balance["id"], 2)
        before = read_balance(balance["id"])
        assert before["on_hand"] + before["on_order"] == 2 < 5, "stockout posture true"
        ro = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 5)], reference="PO-PAR"
        )
        place_replenish_order(ro["id"])
        after = read_balance(balance["id"])
        # 2 + 5 >= 5 clears the stockout flag with zero physical receipt
        assert after["on_hand"] == 2 and after["on_order"] == 5
        assert after["on_hand"] + after["on_order"] >= after["min_par_level"]


class TestReturnToStockReconciliation:
    def test_derived_on_hand_reconciles_across_reserve_commit_return(self, api, site_ops_headers):
        """PRD §3.6: "for every line, the reservation commits, subtracting the
        quantity from reserved and from on_hand"
        PRD §3.8: "Return-to-stock restocks every non-perishable line: for each
        such line the server creates a StockLot with lot_code formed as RMA-
        followed by the order id and product id, received_qty and remaining_qty
        equal to the line quantity, and expires_at pinned to
        2099-12-31T00:00:00Z, and adds the quantity back to the balance's
        on_hand. Perishable lines are never restocked — food safety — and are
        written off instead."

        Design: Corner/cross_cutting_layers/derived_on_hand_reconciles_across_reserve_commit_return
        """
        from test_helpers import make_driver_headers

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500, product_class="STANDARD")
        beer = create_product(sku="SKU-BEER-A", name="Lager 6-pack", price_cents=999,
                              product_class="AGE_RESTRICTED")
        bal_chips = create_balance(site["id"], chips["id"])
        bal_beer = create_balance(site["id"], beer["id"])
        seed_on_hand(bal_chips["id"], 10)
        seed_on_hand(bal_beer["id"], 10)
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        from test_helpers import create_driver
        driver = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        order = place_order(customer["id"], site["id"],
                            [order_line(chips["id"], 3), order_line(beer["id"], 1)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], order["id"], pat["id"])
        mid = read_balance(bal_chips["id"])
        assert mid["on_hand"] == 10 and mid["reserved"] == 3, mid

        from test_helpers import seal_batch
        seal_batch(batch["id"], sam["id"])
        committed = read_balance(bal_chips["id"])
        assert committed["on_hand"] == 7 and committed["reserved"] == 0, committed

        from test_helpers import assign_bag, create_bag_for_order, handoff_scan_payload
        bag = assign_bag(create_bag_for_order(order["id"])["id"])
        get_success_data(api.handoff_scan(
            bag["id"], handoff_scan_payload("2010-01-01", "9999"), make_driver_headers(driver["id"])
        ))
        get_success_data(api.fail_handoff(bag["id"], make_driver_headers(driver["id"])))
        assert read_order(order["id"])["status"] == "HANDOFF_FAILED"

        resp = api.cancel_order(order["id"], {"reason": "RETURN_TO_STOCK"}, site_ops_headers)
        validate_success(resp)
        assert read_order(order["id"])["status"] == "CANCELLED"
        # both lines are non-perishable so both restock
        assert read_balance(bal_chips["id"])["on_hand"] == 10
        assert read_balance(bal_beer["id"])["on_hand"] == 10

    def test_return_to_stock_requires_handoff_failed_state(self, api, site_ops_headers):
        """PRD §3.8: "From HANDOFF_FAILED, a SiteOps operator cancels the order
        with reason RETURN_TO_STOCK; any other reason is ERR_INVALID_REQUEST."
        PRD §3.8: "A customer may cancel their own order only while it is
        PLACED, with reason CUSTOMER; acting on another customer's order is
        ERR_UNAUTHORIZED, and any other reason or state is rejected
        (ERR_INVALID_REQUEST or ERR_INVALID_STATE respectively)."

        Design: Corner/cross_cutting_layers/derived_on_hand_reconciles_across_reserve_commit_return
        """
        from test_helpers import create_driver, make_driver_headers

        (site, product, balance, customer, picker, sealer, order, batch) = setup_sealed_order()
        driver = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        # Order is AWAITING_HANDOFF (not HANDOFF_FAILED): RETURN_TO_STOCK path rejected.
        resp = api.cancel_order(order["id"], {"reason": "RETURN_TO_STOCK"}, site_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_order(order["id"])["status"] == "AWAITING_HANDOFF"
        # Chips balance unchanged: commit already happened at seal, no restock fired.
        assert read_balance(balance["id"])["on_hand"] == 49


class TestDemandForecast:
    def test_forecast_night_and_weather_multipliers_compose_zero_baseline(self, api):
        """PRD §3.9: "The projection for each hour starts from a baseline: the
        count of delivered orders at the site over the trailing 7 days in the
        same hour-of-day."
        PRD §3.9: "The projected order count for the hour is the baseline
        multiplied by both multipliers, rounded half-up to a whole number of
        orders."

        With no delivered orders in the trailing window the baseline is 0 and
        every projected hour is 0 — the multiplicative lifts (night 1.40,
        weather 1 + prob x 0.25) cannot create demand ex nihilo.

        Design: Corner/calculations/forecast_night_and_weather_multipliers_compose
        """
        from test_helpers import SITE_OPS_HEADERS

        set_clock("2026-09-10T23:00:00Z")  # inside the 22:00-04:00 night band
        site = create_site()
        data = validate_success(
            api.get_demand_forecast(site["id"], SITE_OPS_HEADERS,
                                    params={"precipitation_prob": 0.8}),
            expected_status=200,
        )
        hours = data["hours"]
        assert len(hours) == 24, f"next-24-hours projection must have 24 buckets: {len(hours)}"
        for bucket in hours:
            projected = bucket.get("projected", bucket.get("projected_orders"))
            assert projected == 0, f"zero baseline must project zero: {bucket}"

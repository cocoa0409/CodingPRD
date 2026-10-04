"""Calculation corners: FEFO order, freshness/stale boundaries, service-level
measurement, performance threshold, promo rebate posting."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_promo_agreement_payload,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    create_stale_credit,
    deliver_line,
    deliver_order,
    list_lots,
    load_route_day,
    lot_entry,
    make_admin_headers,
    make_rep_headers,
    make_store_manager_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_error,
    validate_success,
)


class TestFefoDeliveryOrder:
    def _setup_two_lots_out_of_order(self):
        """Lot L-LATE (expiry 2026-09-12) loaded BEFORE lot L-EARLY
        (expiry 2026-09-08); both freshness-eligible on 2026-09-01."""
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [
                lot_entry(product["id"], "L-LATE", "2026-09-12", 10),
                lot_entry(product["id"], "L-EARLY", "2026-09-08", 10),
            ],
            rep,
        )
        start_route_day(day["id"], rep)
        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 12)], rep
        )
        submit_order(order["id"], rep)
        return rep, product, day, order

    def test_fefo_delivery_consumes_earliest_expiry_first(self, api):
        """PRD §3.5: "For each line, the system consumes from the day's
        freshness-eligible lots of that product in ascending expiration_date
        order, breaking ties by the lot's created_at ascending — never by lot
        id — incrementing each lot's delivered_cases as it goes; if the
        freshness-eligible remaining stock across those lots is short of the
        requested quantity, the delivery fails with
        ERR_INSUFFICIENT_TRUCK_STOCK."

        Design: Corner/calculations/fefo_delivery_consumes_earliest_expiry_first
        """
        rep, product, day, order = self._setup_two_lots_out_of_order()

        resp = api.deliver_order(
            order["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 5}]},
            make_rep_headers(rep["id"]),
        )
        validate_success(resp)

        lots = list_lots({"route_day_id": day["id"], "product_id": product["id"]})
        by_code = {l["lot_code"]: l for l in lots}
        assert by_code["L-EARLY"]["delivered_cases"] == 5
        assert by_code["L-EARLY"]["remaining_cases"] == 5
        assert by_code["L-LATE"]["delivered_cases"] == 0
        assert by_code["L-LATE"]["remaining_cases"] == 10

    def test_fefo_order_independent_of_load_order(self, api):
        """PRD §3.5: "Consumption follows first-expired-first-out against the
        day's OPEN lots."

        Design: Corner/calculations/fefo_delivery_consumes_earliest_expiry_first
        """
        rep, product, day, order = self._setup_two_lots_out_of_order()

        # Deliver 12: all 10 of L-EARLY then 2 of L-LATE.
        resp = api.deliver_order(
            order["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 12}]},
            make_rep_headers(rep["id"]),
        )
        validate_success(resp)
        lots = list_lots({"route_day_id": day["id"], "product_id": product["id"]})
        by_code = {l["lot_code"]: l for l in lots}
        # L-EARLY drained first even though it was loaded second.
        assert by_code["L-EARLY"]["delivered_cases"] == 10
        assert by_code["L-LATE"]["delivered_cases"] == 2


class TestFreshnessBoundary:
    def test_freshness_boundary_six_days_deliverable_five_days_not(self, api):
        """PRD §3.5: "a delivery may only consume lots whose days-to-expiry is
        strictly greater than 5 — a lot at exactly 5 days is undeliverable, and
        attempting delivery when fulfilling the order would require such a lot
        fails with ERR_FRESHNESS_GUARANTEE_VIOLATION."
        PRD §3.5: "A lot's days-to-expiry is its expiration_date minus the route
        day's service_date, in whole days."

        Design: Corner/calculations/freshness_boundary_six_days_deliverable_five_days_not
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"], service_weekdays=["TUE", "WED"])

        # D1 (2026-09-01) with lot expiring 2026-09-07: days_to_expiry 6.
        day1 = create_route_day(route["id"], service_date="2026-09-01")
        load_route_day(
            day1["id"], [lot_entry(product["id"], "L-1", "2026-09-07", 10)], rep
        )
        start_route_day(day1["id"], rep)
        order1 = create_order(
            day1["id"], store["id"], [order_line(product["id"], 5)], rep
        )
        submit_order(order1["id"], rep)

        # D2 (2026-09-02) with lot expiring 2026-09-07: days_to_expiry 5.
        day2 = create_route_day(route["id"], service_date="2026-09-02")
        load_route_day(
            day2["id"], [lot_entry(product["id"], "L-2", "2026-09-07", 10)], rep
        )
        start_route_day(day2["id"], rep)
        order2 = create_order(
            day2["id"], store["id"], [order_line(product["id"], 5)], rep
        )
        submit_order(order2["id"], rep)

        resp = api.deliver_order(
            order1["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 5}]},
            make_rep_headers(rep["id"]),
        )
        delivered = validate_success(resp)
        assert delivered["status"] == "DELIVERED"

        resp = api.deliver_order(
            order2["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 5}]},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FRESHNESS_GUARANTEE_VIOLATION)
        order2_after = validate_success(
            api.get_order(order2["id"], make_supervisor_headers())
        )
        assert order2_after["status"] == "SUBMITTED"


class TestServiceGradeBoundary:
    def test_service_grade_boundary_oos_exactly_002_is_silver(self, api):
        """PRD §3.10: "The service_grade tiers on the out-of-stock rate: GOLD
        when the rate is strictly below 0.02, SILVER when strictly below 0.05,
        otherwise BRONZE — so a rate of exactly 0.02 earns SILVER, not GOLD,
        and exactly 0.05 earns BRONZE."
        PRD §3.10: "The fill_rate is the sum of qty_delivered_cases divided by
        the sum of qty_ordered_cases over those orders, rounded half up to 4
        decimal places; the oos_rate is one minus the fill rate, also at 4
        decimal places."

        Design: Corner/calculations/service_grade_boundary_oos_exactly_002_is_silver
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 100)], rep
        )
        start_route_day(day["id"], rep)
        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 100)], rep
        )
        submit_order(order["id"], rep)
        deliver_order(order["id"], [deliver_line(product["id"], 98)], rep)

        resp = api.create_service_level_snapshot(
            route["id"],
            {"period_start": "2026-09-01", "period_end": "2026-09-02"},
            make_supervisor_headers(),
        )
        snap = validate_success(resp, expected_status=201)
        assert snap["orders_count"] == 1
        assert snap["fill_rate"] == 0.98
        assert snap["oos_rate"] == 0.02
        assert snap["service_grade"] == "SILVER"


class TestSnapshotWindowFiltering:
    def test_snapshot_window_excludes_out_of_period_and_non_delivered_orders(self, api):
        """PRD §3.10: "requesting a service-level snapshot with a half-open
        measurement window from period_start (inclusive) to period_end
        (exclusive, strictly after the start)."
        PRD §3.10: "The measurement aggregates only DELIVERED orders on those
        in-window route days — DRAFT, SUBMITTED, and CANCELLED orders are
        excluded."

        Design: Corner/calculations/snapshot_window_excludes_out_of_period_and_non_delivered_orders
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])

        # D1 (2026-09-01): one 10/10 delivered order, one cancelled order.
        day1 = create_route_day(route["id"], service_date="2026-09-01")
        load_route_day(
            day1["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 30)], rep
        )
        start_route_day(day1["id"], rep)
        order1 = create_order(
            day1["id"], store["id"], [order_line(product["id"], 10)], rep
        )
        submit_order(order1["id"], rep)
        deliver_order(order1["id"], [deliver_line(product["id"], 10)], rep)
        order_cancel = create_order(
            day1["id"], store["id"], [order_line(product["id"], 4)], rep
        )
        resp = api.cancel_order(order_cancel["id"], make_rep_headers(rep["id"]))
        validate_success(resp)

        # D2 (2026-09-08): one 50-case order delivered only 40 — sits exactly on
        # period_end and must be excluded (half-open window).
        day2 = create_route_day(route["id"], service_date="2026-09-08")
        load_route_day(
            day2["id"], [lot_entry(product["id"], "L-2", "2026-09-30", 60)], rep
        )
        start_route_day(day2["id"], rep)
        order2 = create_order(
            day2["id"], store["id"], [order_line(product["id"], 50)], rep
        )
        submit_order(order2["id"], rep)
        deliver_order(order2["id"], [deliver_line(product["id"], 40)], rep)

        resp = api.create_service_level_snapshot(
            route["id"],
            {"period_start": "2026-09-01", "period_end": "2026-09-08"},
            make_supervisor_headers(),
        )
        snap = validate_success(resp, expected_status=201)
        assert snap["orders_count"] == 1
        assert snap["fill_rate"] == 1.0
        assert snap["oos_rate"] == 0.0
        assert snap["service_grade"] == "GOLD"


class TestStaleRatioThreshold:
    def test_stale_ratio_exactly_at_threshold_stays_clear(self, api):
        """PRD §3.10: "The performance_flag_result is PERFORMANCE_WATCH when the
        ratio is strictly greater than 0.08 and CLEAR otherwise — a ratio of
        exactly 0.08 is CLEAR."
        PRD §3.10: "Creating the snapshot also overwrites the route's
        performance_flag with this result and increments the route's version by
        1."

        Design: Corner/calculations/stale_ratio_exactly_at_threshold_stays_clear
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"], base_capacity_cases=120)
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [
                lot_entry(product["id"], "L-A", "2026-09-20", 100),
                lot_entry(product["id"], "L-B", "2026-09-06", 10),
            ],
            rep,
        )
        start_route_day(day["id"], rep)
        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 50)], rep
        )
        submit_order(order["id"], rep)
        deliver_order(order["id"], [deliver_line(product["id"], 50)], rep)
        # gross 25000; 4-case FULL_RETAIL credit = 2000 => ratio 0.08 exactly.
        credit = create_stale_credit(
            day["id"], store["id"], product["id"], 4, make_rep_headers(rep["id"])
        )
        resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
        validate_success(resp)

        resp = api.create_service_level_snapshot(
            route["id"],
            {"period_start": "2026-09-01", "period_end": "2026-09-02"},
            make_supervisor_headers(),
        )
        snap = validate_success(resp, expected_status=201)
        assert snap["stale_ratio"] == 0.08
        assert snap["performance_flag_result"] == "CLEAR"

        route_after = validate_success(
            api.get_route(route["id"], make_supervisor_headers())
        )
        assert route_after["performance_flag"] == "CLEAR"


class TestPromoRebatePosting:
    def test_promo_rebate_posted_to_store_balance_on_verify(self, api):
        """PRD §3.8: "Verification — permitted only while the agreement remains
        ACTIVE — moves the execution to VERIFIED, completes the agreement
        (ACTIVE → COMPLETED), and posts the agreement's rebate_cents onto the
        store's promo_rebate_balance_cents."

        Design: Corner/calculations/promo_rebate_posted_to_store_balance_on_verify
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
        )
        start_route_day(day["id"], rep)

        resp = api.create_promo_agreement(
            create_promo_agreement_payload(store["id"], product["id"]),
            make_supervisor_headers(),
        )
        agreement = validate_success(resp, expected_status=201)
        resp = api.activate_promo_agreement(agreement["id"], make_supervisor_headers())
        active = validate_success(resp)

        resp = api.create_promo_execution(
            {
                "agreement_id": agreement["id"],
                "route_day_id": day["id"],
                "photo_url": "https://photos/x.jpg",
                "expected_promo_agreement_version": active["version"],
            },
            make_rep_headers(rep["id"]),
        )
        execution = validate_success(resp, expected_status=201)

        resp = api.verify_promo_execution(
            execution["id"], make_store_manager_headers(store["id"])
        )
        verified = validate_success(resp)
        assert verified["status"] == "VERIFIED"

        agreement_after = validate_success(
            api.get_promo_agreement(agreement["id"], make_supervisor_headers())
        )
        assert agreement_after["status"] == "COMPLETED"

        store_after = validate_success(
            api.get_store(store["id"], make_supervisor_headers())
        )
        assert store_after["promo_rebate_balance_cents"] == 5000

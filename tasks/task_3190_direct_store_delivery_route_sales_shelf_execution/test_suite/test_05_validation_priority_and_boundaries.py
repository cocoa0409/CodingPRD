"""Validation-priority pairs and boundary precision on money and cases."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_settlement,
    create_store,
    deliver_line,
    deliver_order,
    get_route_day,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _orders_for_day(day_id):
    return validate_paginated(
        api_client.list_orders(make_supervisor_headers(), params={"route_day_id": day_id})
    )


class TestStoreStateBeatsCreditCap:
    def _setup_suspended_low_cap_store(self):
        set_clock()
        rep = create_rep()
        store = create_store(store_credit_cap_cents=100)
        product = create_product(case_price_cents=250)
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 40)], rep
        )
        start_route_day(day["id"], rep)
        resp = api_client.suspend_store(store["id"], make_supervisor_headers())
        validate_success(resp)
        return rep, store, product, day

    def test_state_error_wins_over_fiscal_error(self, api):
        """PRD §2.5: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failure
        wins."
        PRD §3.1: "Suspending a store (ACTIVE → SUSPENDED) blocks order
        creation and submission, stale-credit creation, shelf-execution
        creation, and promo-agreement creation against that store with
        ERR_STORE_NOT_ACTIVE, until the store is reactivated."
        PRD §2.5: "and finally (11) the per-store stale-credit cap."

        Design: Difficulty/priority_pair_validation_conflict/store_state_failure_beats_credit_cap_fiscal_failure
        """
        rep, store, product, day = self._setup_suspended_low_cap_store()

        resp = api.create_stale_credit(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "product_id": product["id"],
                "qty_cases": 10,
            },
            make_rep_headers(rep["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        # Even though 10 * 250 == 2500 exceeds the 100-cent cap, the
        # state error wins.
        assert err["error_id"] != ApiErrorId.ERR_STORE_CREDIT_CAP_EXCEEDED

        credits, meta = validate_paginated(
            api.list_stale_credits(
                make_supervisor_headers(), params={"store_id": store["id"]}
            )
        )
        assert len(credits) == 0
        assert meta["total_count"] == 0

    def test_suspended_store_blocks_credit_creation_regardless_of_cap(self, api):
        """PRD §3.1: "Suspending a store (ACTIVE → SUSPENDED) blocks order
        creation and submission, stale-credit creation, shelf-execution
        creation, and promo-agreement creation against that store with
        ERR_STORE_NOT_ACTIVE, until the store is reactivated."

        Design: Difficulty/priority_pair_validation_conflict/store_state_failure_beats_credit_cap_fiscal_failure
        """
        rep, store, product, day = self._setup_suspended_low_cap_store()

        # Even a 1-case credit (250 cents, also over the 100 cap) hits the
        # state check first.
        resp = api.create_stale_credit(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "product_id": product["id"],
                "qty_cases": 1,
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        store_after = validate_success(
            api.get_store(store["id"], make_supervisor_headers())
        )
        assert store_after["status"] == "SUSPENDED"


class TestFreshnessBeatsLineNotOnOrder:
    def _setup(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        prod_a = create_product(sku="P-A")
        prod_b = create_product(
            sku="P-B", name="Dips", case_price_cents=300, shelf_life_days=45
        )
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [
                lot_entry(prod_a["id"], "L-A", "2026-09-20", 50),
                lot_entry(prod_b["id"], "L-B", "2026-09-06", 10),
            ],
            rep,
        )
        start_route_day(day["id"], rep)
        order = create_order(
            day["id"], store["id"], [order_line(prod_a["id"], 5)], rep
        )
        submit_order(order["id"], rep)
        return rep, prod_b, order

    def test_freshness_error_wins_over_referential_error(self, api):
        """PRD §2.5: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failure
        wins."
        PRD §2.5: "(7) the freshness guarantee on delivery; (8) temporal window
        checks — the delivery window, promo-window overlap, assignment weekday
        conflicts, scheduled-stop coverage, agreement activation windows; (9)
        referential allocation checks — the product is on the truck that day,
        deliver lines reference products actually on the order."

        Design: Difficulty/priority_pair_validation_conflict/freshness_safety_failure_beats_line_not_on_order_referential_failure
        """
        rep, prod_b, order = self._setup()

        resp = api.deliver_order(
            order["id"],
            {"lines": [{"product_id": prod_b["id"], "qty_delivered_cases": 1}]},
            make_rep_headers(rep["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_FRESHNESS_GUARANTEE_VIOLATION)
        assert err["error_id"] != ApiErrorId.ERR_DELIVERY_LINE_NOT_ON_ORDER

        order_after = validate_success(
            api.get_order(order["id"], make_supervisor_headers())
        )
        assert order_after["status"] == "SUBMITTED"

    def test_delivery_rejected_and_order_unchanged(self, api):
        """PRD §3.5: "The freshness guarantee is absolute: a delivery may only
        consume lots whose days-to-expiry is strictly greater than 5 — a lot at
        exactly 5 days is undeliverable, and attempting delivery when fulfilling
        the order would require such a lot fails with
        ERR_FRESHNESS_GUARANTEE_VIOLATION."

        Design: Difficulty/priority_pair_validation_conflict/freshness_safety_failure_beats_line_not_on_order_referential_failure
        """
        rep, prod_b, order = self._setup()

        resp = api.deliver_order(
            order["id"],
            {"lines": [{"product_id": prod_b["id"], "qty_delivered_cases": 1}]},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FRESHNESS_GUARANTEE_VIOLATION)

        order_after = validate_success(
            api.get_order(order["id"], make_supervisor_headers())
        )
        assert order_after["status"] == "SUBMITTED"
        assert order_after["delivered_at"] is None


class TestSettlementVarianceToleranceBoundary:
    def _setup_settlement_for_10000(self, service_date):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"], service_weekdays=["TUE", "WED"])
        day = create_route_day(route["id"], service_date=service_date)
        load_route_day(
            day["id"],
            [lot_entry(product["id"], f"L-{service_date}", "2026-09-20", 100)],
            rep,
        )
        start_route_day(day["id"], rep)
        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 20)], rep
        )
        submit_order(order["id"], rep)
        deliver_order(order["id"], [deliver_line(product["id"], 20)], rep)
        settlement = create_settlement(day["id"])
        assert settlement["chronological_expected_cents"] == 10000
        return settlement

    def test_variance_exactly_200_balances(self, api):
        """PRD §3.9: "The supervisor records cash_collected_cents; the
        settlement moves OPEN → BALANCED exactly when the absolute value of
        variance_cents is at most 200 cents — an absolute variance of precisely
        200 balances, while 201 does not — and when the variance exceeds the
        tolerance the request still returns 200 with the settlement left OPEN,
        carrying the recorded cash and recomputed variance."

        Design: Difficulty/boundary_precision_check/settlement_variance_tolerance_at_exactly_200_vs_201
        """
        settlement = self._setup_settlement_for_10000("2026-09-01")

        resp = api.balance_settlement(
            settlement["id"], {"cash_collected_cents": 9800}, make_supervisor_headers()
        )
        balanced = validate_success(resp)
        assert balanced["variance_cents"] == -200
        assert balanced["status"] == "BALANCED"

    def test_variance_201_stays_open_with_200_response(self, api):
        """PRD §3.9: "when the variance exceeds the tolerance the request still
        returns 200 with the settlement left OPEN, carrying the recorded cash
        and recomputed variance."

        Design: Difficulty/boundary_precision_check/settlement_variance_tolerance_at_exactly_200_vs_201
        """
        settlement = self._setup_settlement_for_10000("2026-09-01")

        resp = api.balance_settlement(
            settlement["id"], {"cash_collected_cents": 9799}, make_supervisor_headers()
        )
        assert resp.status_code == 200
        open_settlement = validate_success(resp)
        assert open_settlement["variance_cents"] == -201
        assert open_settlement["status"] == "OPEN"
        assert open_settlement["cash_collected_cents"] == 9799


class TestRouteDayLoadCapacityBoundary:
    def _setup_planned_day(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        return rep, product, day

    def test_one_case_over_capacity_rejected(self, api):
        """PRD §3.3: "The summed loaded_cases across the payload may not exceed
        the day's capacity_cases — ERR_CAPACITY_EXCEEDED when it does."

        Design: Difficulty/boundary_precision_check/route_day_load_at_exact_capacity_vs_one_case_over
        """
        rep, product, day = self._setup_planned_day()

        resp = api.load_route_day(
            day["id"],
            {
                "lots": [
                    lot_entry(product["id"], "L-A", "2026-09-20", 100),
                    lot_entry(product["id"], "L-B", "2026-09-20", 1),
                ]
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

        day_after = get_route_day(day["id"])
        assert day_after["status"] == "PLANNED"
        assert day_after["loaded_cases"] == 0

    def test_exact_capacity_load_succeeds_after_rejection(self, api):
        """PRD §3.2: "the surge is event_surge_cases on an event day and zero on
        a standard day regardless of any payload value (a positive
        event_surge_cases on a non-event day is ERR_VALIDATION) — capped at the
        route's truck_cap_cases; equality with the cap is permitted."
        PRD §3.3: "Loading creates one truck-inventory lot per payload entry in
        SEALED status, recomputes the route day's loaded_cases, transitions the
        day PLANNED → LOADED, and increments the route day's version."

        Design: Difficulty/boundary_precision_check/route_day_load_at_exact_capacity_vs_one_case_over
        """
        rep, product, day = self._setup_planned_day()

        # 101 > 100: rejected; the day stays PLANNED so the corrected load works.
        resp = api.load_route_day(
            day["id"],
            {
                "lots": [
                    lot_entry(product["id"], "L-A", "2026-09-20", 100),
                    lot_entry(product["id"], "L-B", "2026-09-20", 1),
                ]
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

        resp = api.load_route_day(
            day["id"],
            {
                "lots": [
                    lot_entry(product["id"], "L-A", "2026-09-20", 60),
                    lot_entry(product["id"], "L-B", "2026-09-20", 40),
                ]
            },
            make_rep_headers(rep["id"]),
        )
        loaded = validate_success(resp)
        assert loaded["status"] == "LOADED"
        assert loaded["loaded_cases"] == 100
        assert loaded["capacity_cases"] == 100

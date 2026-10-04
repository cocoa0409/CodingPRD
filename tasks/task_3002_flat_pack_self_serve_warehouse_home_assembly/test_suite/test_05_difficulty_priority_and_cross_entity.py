"""Difficulty rules: priority_pair_validation_conflict and
cross_entity_state_dependency."""
from test_helpers import (
    ApiErrorId,
    OPS,
    add_line,
    checkout,
    create_assembly_job,
    create_order,
    cust_headers,
    get_success_data,
    pickup_complete,
    setup_article_with_stock,
    setup_store_and_customer,
    validate_error,
    validate_success,
)


class TestCheckoutStateErrorBeatsPointsFiscal:
    """Instance: checkout_state_error_beats_points_fiscal."""

    def test_cancelled_order_checkout_reports_invalid_state_not_points(self, api):
        """PRD §2.9: "Sixth, state-machine legality — wrong from-state, an
        unreturnable order, an expired reservation, a duplicate booking, or
        ungraded return lines — yielding `ERR_INVALID_STATE`,
        `ERR_ORDER_NOT_RETURNABLE`, `ERR_RESERVATION_EXPIRED`,
        `ERR_DUPLICATE_BOOKING`, or `ERR_UNGRADED_LINES` (HTTP 409). Seventh,
        temporal rules: ... Eighth, business constraints: ... Ninth and last,
        fiscal limits: points balance and spare-part claim caps (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_error_beats_points_fiscal
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=1000)
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)
        cancelled = validate_success(api.cancel_order(order["id"], cust_headers(customer)))
        assert cancelled["status"] == "CANCELLED"

        resp = api.checkout_order(order["id"], {"redeem_points": 999999},
                                  cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert after["status"] == "CANCELLED"

    def test_state_category_precedes_fiscal_category_in_pinned_order(self, api):
        """PRD §2.9: "When a request violates several rules at once, the error
        the caller sees is determined by a fixed priority order, evaluated
        from first to last."
        PRD §3.3: "A `redeem_points` request exceeding the customer's
        `points_balance` is rejected with `ERR_INSUFFICIENT_POINTS`."

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_error_beats_points_fiscal
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=1000)
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)

        # Same redeem_points overage on a legal (DRAFT) order surfaces the
        # fiscal error, proving the previous test's 409 was about state.
        resp = api.checkout_order(order["id"], {"redeem_points": 999999},
                                  cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS)
        assert resp.status_code == 422


class TestAssemblyWindowTemporalBeatsMissingStandard:
    """Instance: assembly_window_temporal_beats_missing_standard."""

    def test_past_window_reported_even_when_standard_missing(self, api):
        """PRD §2.9: "Seventh, temporal rules: an assembly window in the past
        or a delivery slot whose service date has passed, yielding
        `ERR_WINDOW_IN_PAST` or `ERR_SLOT_IN_PAST` (HTTP 422). Eighth,
        business constraints: stock sufficiency, multi-carton completeness,
        duplicate bin-stock rows, slot capacity, building-access feasibility,
        crew-window conflicts, missing assembly standards, receipt
        requirements, and return-quantity limits (HTTP 422)."
        PRD §3.6: "a `window_start` before the current logical time, or a
        `window_end` that is not strictly after the start, is rejected with
        `ERR_WINDOW_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/assembly_window_temporal_beats_missing_standard
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True,  # NOTE: no assembly standard registered
        )
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)
        checkout(customer, order["id"])
        pickup_complete(order["id"])

        resp = api.create_assembly_job(
            order["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-08-01T10:00:00Z",
             "window_end": "2026-08-01T12:00:00Z"},
            cust_headers(customer),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)
        assert resp.status_code == 422

        after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert after["assembly_status"] == "NONE"

    def test_missing_standard_reported_when_window_is_legal(self, api):
        """PRD §3.6: "if any such line has no registered standard, the request
        is rejected with `ERR_STANDARD_MISSING`."
        PRD §2.9: "the error the caller sees is determined by a fixed priority
        order, evaluated from first to last."

        Design: Difficulty/priority_pair_validation_conflict/assembly_window_temporal_beats_missing_standard
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True,
        )
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)
        checkout(customer, order["id"])
        pickup_complete(order["id"])

        resp = api.create_assembly_job(
            order["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-09-10T10:00:00Z",
             "window_end": "2026-09-10T12:00:00Z"},
            cust_headers(customer),
        )
        validate_error(resp, ApiErrorId.ERR_STANDARD_MISSING)
        assert resp.status_code == 422


class TestCheckoutGatedByBinStockAvailability:
    """Instance: checkout_gated_by_binstock_availability."""

    def test_checkout_rejected_then_succeeds_after_stock_adjustment(self, api):
        """PRD §3.3: "The stock check runs per line against the order's store:
        for every line, the article's `available_units` — the smallest
        per-carton `available`, per the signal rule — must cover the requested
        `qty`"
        PRD §3.3: "When every carton of an article falls short — or the
        article simply has no cartons or no stock rows — the checkout is
        rejected with `ERR_INSUFFICIENT_STOCK`"

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_binstock_availability
        """
        store, customer = setup_store_and_customer()
        article, _, stocks = setup_article_with_stock(store, on_hand=2, price_cents=1000)
        stock = stocks[0]
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=3)

        resp = api.checkout_order(order["id"], {}, cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        assert resp.status_code == 422
        draft = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert draft["status"] == "DRAFT"

        adjusted = validate_success(api.adjust_bin_stock(
            stock["id"],
            {"delta_on_hand": 2, "expected_stock_version": stock["version"]},
            OPS,
        ))
        assert adjusted["on_hand"] == 4

        paid = validate_success(api.checkout_order(order["id"], {}, cust_headers(customer)))
        assert paid["status"] == "PAID"
        stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert stock_after["on_hand"] == 1

    def test_checkout_uses_min_available_across_cartons(self, api):
        """PRD §3.1: "Otherwise `available_units` is the smallest per-carton
        `available` across all of the article's cartons — the number of
        complete multi-box sets the shelf can yield."
        PRD §3.3: "for every line, the article's `available_units` — the
        smallest per-carton `available`, per the signal rule — must cover the
        requested `qty`"

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_binstock_availability
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, price_cents=1000, cartons=[(10, 0.1, 3), (8, 0.08, 2)])
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=3)

        # min(3, 2) = 2 < 3: the same order flips to success only after the
        # short carton's row is topped up.
        resp = api.checkout_order(order["id"], {}, cust_headers(customer))
        assert resp.status_code == 422

        stock_rows = get_success_data(
            api.list_bin_stock(OPS, params={"store_id": store["id"]}))
        short = next(r for r in stock_rows if r["on_hand"] == 2)
        validate_success(api.adjust_bin_stock(
            short["id"],
            {"delta_on_hand": 1, "expected_stock_version": short["version"]},
            OPS,
        ))
        paid = validate_success(api.checkout_order(order["id"], {}, cust_headers(customer)))
        assert paid["status"] == "PAID"


class TestAssemblyJobGatedByOrderFulfillment:
    """Instance: assembly_job_gated_by_order_fulfillment."""

    def test_job_rejected_while_paid_accepted_once_fulfilled(self, api):
        """PRD §3.6: "When a customer whose order has reached `FULFILLED` or
        `DELIVERED` — and whose `assembly_status` is still `NONE` — requests
        assembly, the request names the `provider_id` of the third-party crew
        and a service window from `window_start` to `window_end`, both
        inclusive."
        PRD §2.9: "state-machine legality — wrong from-state ... yielding
        `ERR_INVALID_STATE` ... (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/assembly_job_gated_by_order_fulfillment
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=30,
        )
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)
        checkout(customer, order["id"])

        window = {"provider_id": "CREW-A",
                  "window_start": "2026-09-10T10:00:00Z",
                  "window_end": "2026-09-10T11:00:00Z"}
        resp = api.create_assembly_job(order["id"], window, cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        pickup_complete(order["id"])
        job = validate_success(
            api.create_assembly_job(order["id"], window, cust_headers(customer)),
            expected_status=201,
        )
        assert job["status"] == "REQUESTED"
        assert job["estimated_minutes"] == 30

        after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert after["assembly_status"] == "SCHEDULED"

    def test_job_creation_moves_assembly_status_to_scheduled(self, api):
        """PRD §3.6: "A clean request creates the job in `REQUESTED` and moves
        the order's `assembly_status` to `SCHEDULED`."
        PRD §3.6: "When a customer whose order has reached `FULFILLED` or
        `DELIVERED` — and whose `assembly_status` is still `NONE` — requests
        assembly"

        Design: Difficulty/cross_entity_state_dependency/assembly_job_gated_by_order_fulfillment
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=30,
        )
        order = create_order(customer, store["id"])
        add_line(customer, order["id"], article["id"], qty=1)
        checkout(customer, order["id"])
        pickup_complete(order["id"])

        job = create_assembly_job(customer, order["id"], provider_id="CREW-A",
                                  window_start="2026-09-10T10:00:00Z",
                                  window_end="2026-09-10T11:00:00Z")
        assert job["status"] == "REQUESTED"
        order_after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert order_after["assembly_status"] == "SCHEDULED"

        # A second job request while assembly_status is SCHEDULED is a state
        # violation, not a new job.
        resp = api.create_assembly_job(
            order["id"],
            {"provider_id": "CREW-Z",
             "window_start": "2026-09-11T10:00:00Z",
             "window_end": "2026-09-11T11:00:00Z"},
            cust_headers(customer),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

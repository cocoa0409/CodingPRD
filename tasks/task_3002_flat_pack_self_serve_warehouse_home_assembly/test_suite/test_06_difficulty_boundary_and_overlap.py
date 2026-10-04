"""Difficulty rules: boundary_precision_check and resource_temporal_overlap."""
from test_helpers import (
    ApiErrorId,
    OPS,
    add_line,
    checkout,
    create_assembly_job,
    create_booking,
    create_delivery_slot,
    create_order,
    cust_headers,
    current_slot_version,
    get_success_data,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_fulfilled_order,
    setup_store_and_customer,
    validate_error,
    validate_success,
)


class TestDeliveryWeightTierAt50Vs51:
    """Instance: delivery_weight_tier_at_50_vs_51."""

    def _scenario(self, api, store, customer, weight_kg):
        article, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(weight_kg, 0.1, 2)],
        )
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=200, capacity_volume_m3=5)
        order, _ = setup_delivery_paid_order(customer, store, article, qty=1)
        booking = create_booking(customer, order["id"], slot["id"],
                                 expected_slot_version=slot["version"])
        return booking

    def test_exactly_50kg_stays_in_tier_one(self, api):
        """PRD §3.5: "A weight surcharge follows: nothing while the booking
        weighs at most 50 kilograms; a flat 2500 cents once it exceeds 50
        kilograms up to and including 150"
        PRD §3.5: "The gross fee starts from a zone base of 4900 cents for
        `ZONE_A`, 7900 cents for `ZONE_B`, or 12900 cents for `ZONE_C`."

        Design: Difficulty/boundary_precision_check/delivery_weight_tier_at_50_vs_51
        """
        store, customer = setup_store_and_customer()
        booking = self._scenario(api, store, customer, 50)
        assert booking["status"] == "CONFIRMED"
        assert booking["fee_cents"] == 4900, (
            f"50 kg exactly pays only the ZONE_A base 4900, got {booking['fee_cents']}"
        )

    def test_51kg_crosses_into_tier_two(self, api):
        """PRD §3.5: "A weight surcharge follows: nothing while the booking
        weighs at most 50 kilograms; a flat 2500 cents once it exceeds 50
        kilograms up to and including 150"

        Design: Difficulty/boundary_precision_check/delivery_weight_tier_at_50_vs_51
        """
        store, customer = setup_store_and_customer()
        booking = self._scenario(api, store, customer, 51)
        assert booking["status"] == "CONFIRMED"
        assert booking["fee_cents"] == 7400, (
            f"51 kg pays 4900 + 2500 tier-2 flat = 7400, got {booking['fee_cents']}"
        )


class TestCheckoutAvailabilityHitsExactlyZero:
    """Instance: checkout_availability_hits_exactly_zero."""

    def test_buying_exact_available_succeeds_then_next_unit_fails(self, api):
        """PRD §3.1: "`OUT_OF_STOCK` when no complete units are available"
        PRD §3.3: "When every carton of an article falls short — or the
        article simply has no cartons or no stock rows — the checkout is
        rejected with `ERR_INSUFFICIENT_STOCK`"

        Design: Difficulty/boundary_precision_check/checkout_availability_hits_exactly_zero
        """
        store, customer = setup_store_and_customer()
        article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
        stock = stocks[0]

        o1 = create_order(customer, store["id"])
        add_line(customer, o1["id"], article["id"], qty=5)
        paid = checkout(customer, o1["id"])
        assert paid["status"] == "PAID"
        assert paid["total_cents"] == 2500

        stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert stock_after["on_hand"] == 0
        assert stock_after["available"] == 0

        signal = get_success_data(
            api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
        assert signal["signal"] == "OUT_OF_STOCK"
        assert signal["available_units"] == 0

        o2 = create_order(customer, store["id"])
        add_line(customer, o2["id"], article["id"], qty=1)
        resp = api.checkout_order(o2["id"], {}, cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        assert resp.status_code == 422
        o2_after = get_success_data(api.get_order(o2["id"], cust_headers(customer)))
        assert o2_after["status"] == "DRAFT"

    def test_signal_starts_in_stock_at_threshold_and_available_equals_stock(self, api):
        """PRD §3.1: "`IN_STOCK` once availability reaches the threshold"
        PRD §3.1: "On a `CARRYOUT` order, every `SELF_PICK` line decrements
        `on_hand` by the line quantity on every carton of its article"

        Design: Difficulty/boundary_precision_check/checkout_availability_hits_exactly_zero
        """
        store, customer = setup_store_and_customer()
        article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)

        signal = get_success_data(
            api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
        assert signal["signal"] == "IN_STOCK"
        assert signal["available_units"] == 5

        o1 = create_order(customer, store["id"])
        add_line(customer, o1["id"], article["id"], qty=5)
        checkout(customer, o1["id"])

        # The zero-remaining edge: one more checkout of a single unit fails.
        o2 = create_order(customer, store["id"])
        add_line(customer, o2["id"], article["id"], qty=1)
        resp = api.checkout_order(o2["id"], {}, cust_headers(customer))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        signal_after = get_success_data(
            api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
        assert signal_after["available_units"] == 0
        assert signal_after["signal"] == "OUT_OF_STOCK"


class TestCrewWindowThirtyMinuteBuffer:
    """Instance: crew_window_thirty_minute_buffer."""

    def _three_fulfilled_orders(self, customer, store, article):
        return [setup_fulfilled_order(customer, store, [(article, 1)])[0]
                for _ in range(3)]

    def test_exactly_thirty_minute_gap_allowed_one_minute_inside_rejected(self, api):
        """PRD §3.6: "a conflict exists when the new window's start falls
        before the end of an existing window plus its buffer while the start
        of that existing window minus its buffer falls before the new
        window's end; the comparison is strict on both sides, so a gap of
        exactly 30 minutes between windows is allowed, and anything tighter is
        rejected with `ERR_CREW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_window_thirty_minute_buffer
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=10, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=30,
        )
        o1, o2, o3 = self._three_fulfilled_orders(customer, store, article)

        create_assembly_job(customer, o1["id"], provider_id="CREW-A",
                            window_start="2026-09-10T10:00:00Z",
                            window_end="2026-09-10T11:00:00Z")

        # Exactly 30 minutes after the existing window ends: allowed.
        ok = validate_success(api.create_assembly_job(
            o2["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-09-10T11:30:00Z",
             "window_end": "2026-09-10T12:00:00Z"},
            cust_headers(customer),
        ), expected_status=201)
        assert ok["status"] == "REQUESTED"

        # 29 minutes after: inside the buffer, rejected.
        resp = api.create_assembly_job(
            o3["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-09-10T11:29:00Z",
             "window_end": "2026-09-10T12:00:00Z"},
            cust_headers(customer),
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)
        assert resp.status_code == 422
        o3_after = get_success_data(api.get_order(o3["id"], cust_headers(customer)))
        assert o3_after["assembly_status"] == "NONE"

    def test_buffer_applies_on_both_sides_of_existing_window(self, api):
        """PRD §3.6: "the request is also checked against every non-terminal
        job — `REQUESTED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` — already
        held by the same `provider_id`, with a 30-minute buffer applied on
        both sides of every existing window."

        Design: Difficulty/resource_temporal_overlap/crew_window_thirty_minute_buffer
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=10, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=30,
        )
        o1, o2, o3 = self._three_fulfilled_orders(customer, store, article)

        create_assembly_job(customer, o1["id"], provider_id="CREW-A",
                            window_start="2026-09-10T10:00:00Z",
                            window_end="2026-09-10T11:00:00Z")

        # Ending exactly 30 minutes before the existing window starts: allowed.
        ok = validate_success(api.create_assembly_job(
            o2["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-09-10T08:30:00Z",
             "window_end": "2026-09-10T09:30:00Z"},
            cust_headers(customer),
        ), expected_status=201)
        assert ok["status"] == "REQUESTED"

        # Ending one minute inside the leading buffer: rejected.
        resp = api.create_assembly_job(
            o3["id"],
            {"provider_id": "CREW-A",
             "window_start": "2026-09-10T08:30:00Z",
             "window_end": "2026-09-10T09:31:00Z"},
            cust_headers(customer),
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)


class TestSlotTwoDimensionalCapacityOccupation:
    """Instance: slot_two_dimensional_capacity_occupation."""

    def test_exact_fill_confirms_and_volume_bound_booking_waitlists(self, api):
        """PRD §3.5: "the fit test is inclusive — the booking fits when the
        slot's used weight plus the booking's weight stays at or under
        `capacity_weight_kg` and the same holds for volume, so a booking that
        exactly fills both dimensions still fits."
        PRD §3.5: "the slot's `posture` reads `OPEN` while free capacity
        remains in both dimensions and `FULL` the moment free weight or free
        volume reaches zero."

        Design: Difficulty/resource_temporal_overlap/slot_two_dimensional_capacity_occupation
        """
        store, customer = setup_store_and_customer()
        v60, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(60, 1.5, 2)])
        v10, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(10, 0.6, 2)])
        v40, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(40, 0.5, 2)])
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=100, capacity_volume_m3=2.0)

        o1, _ = setup_delivery_paid_order(customer, store, v60, qty=1)
        b1 = create_booking(customer, o1["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b1["status"] == "CONFIRMED"

        # Volume-bound despite 40 kg of weight headroom: 1.5 + 0.6 > 2.0.
        o2, _ = setup_delivery_paid_order(customer, store, v10, qty=1)
        b2 = create_booking(customer, o2["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b2["status"] == "WAITLISTED"

        # Exactly fills both dimensions: 60 + 40 = 100 <= 100; 1.5 + 0.5 = 2.0.
        o3, _ = setup_delivery_paid_order(customer, store, v40, qty=1)
        b3 = create_booking(customer, o3["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b3["status"] == "CONFIRMED"

        slot_after = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
        assert slot_after["used_weight_kg"] == 100
        assert slot_after["used_volume_m3"] == 2.0
        assert slot_after["posture"] == "FULL"

    def test_volume_dimension_binds_independently_of_weight(self, api):
        """PRD §3.5: "`used_weight_kg` and `used_volume_m3` are the sums over
        the slot's bookings that are `CONFIRMED` or `OUT_FOR_DELIVERY`"
        PRD §3.5: "the fit test is inclusive — the booking fits when the
        slot's used weight plus the booking's weight stays at or under
        `capacity_weight_kg` and the same holds for volume"

        Design: Difficulty/resource_temporal_overlap/slot_two_dimensional_capacity_occupation
        """
        store, customer = setup_store_and_customer()
        light_but_bulky, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(10, 1.5, 2)])
        filler, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(10, 0.6, 2)])
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=500, capacity_volume_m3=2.0)

        o1, _ = setup_delivery_paid_order(customer, store, light_but_bulky, qty=1)
        b1 = create_booking(customer, o1["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b1["status"] == "CONFIRMED"

        # 10 kg fits trivially on weight (500 kg capacity) but 1.5 + 0.6 > 2.0.
        o2, _ = setup_delivery_paid_order(customer, store, filler, qty=1)
        b2 = create_booking(customer, o2["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b2["status"] == "WAITLISTED"
        slot_after = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
        assert slot_after["used_weight_kg"] == 10
        assert slot_after["used_volume_m3"] == 1.5
        assert slot_after["posture"] == "OPEN"

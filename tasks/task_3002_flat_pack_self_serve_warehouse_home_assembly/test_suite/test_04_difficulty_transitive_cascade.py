"""Difficulty rule: transitive_cascade — booking cancel -> waitlist promotion
-> order/stock, and assembly completion -> auto-close -> points accrual."""
from test_helpers import (
    COORD,
    OPS,
    PROVIDER,
    create_assembly_job,
    create_booking,
    create_delivery_slot,
    cust_headers,
    current_slot_version,
    get_success_data,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_store_and_customer,
    validate_success,
)


class TestBookingCancelPromotesWaitlistToOrder:
    """Instance: booking_cancel_promotes_waitlist_to_order."""

    def _three_order_scenario(self, api, customer, store):
        """B1 (60 kg) CONFIRMED, B2 (40 kg) CONFIRMED filling a 100 kg slot,
        B3 (30 kg) WAITLISTED. Returns dict of everything the tests need."""
        a60, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(60, 1.0, 2)])
        a40, _, _ = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(40, 0.8, 2)])
        a30, _, s30 = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(30, 0.1, 2)])
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=100, capacity_volume_m3=2.0)

        o1, _ = setup_delivery_paid_order(customer, store, a60, qty=1)
        b1 = create_booking(customer, o1["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b1["status"] == "CONFIRMED"

        o2, _ = setup_delivery_paid_order(customer, store, a40, qty=1)
        b2 = create_booking(customer, o2["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b2["status"] == "CONFIRMED"  # 60 + 40 = 100 kg exactly fits

        o3, _ = setup_delivery_paid_order(customer, store, a30, qty=1)
        b3 = create_booking(customer, o3["id"], slot["id"],
                            expected_slot_version=current_slot_version(slot["id"]))
        assert b3["status"] == "WAITLISTED"

        return {"slot": slot, "o1": o1, "b1": b1, "o2": o2, "b2": b2,
                "o3": o3, "b3": b3, "stock30": s30[0]}

    def test_cancel_cascades_capacity_promotion_order_and_stock(self, api):
        """PRD §3.5: "cancelling a `CONFIRMED` booking releases its capacity
        from the slot's used figures, bumps the slot's `version` by 1, releases
        the `reserved` stock per carton per line, returns the order's
        `delivery_status` to `NONE`, and triggers a waitlist-promotion scan of
        the slot"
        PRD §3.5: "a candidate that fits the remaining capacity is promoted to
        `CONFIRMED` — consuming slot capacity, bumping the slot's `version`,
        reserving its stock per carton per line, and moving its order's
        `delivery_status` to `SCHEDULED`"

        Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_to_order
        """
        store, customer = setup_store_and_customer()
        s = self._three_order_scenario(api, customer, store)

        cancelled = validate_success(
            api.cancel_delivery_booking(s["b1"]["id"], cust_headers(customer)))
        assert cancelled["status"] == "CANCELLED"

        slot = get_success_data(api.get_delivery_slot(s["slot"]["id"], COORD))
        # hop 1: 100 - 60 freed; hop 2: +30 weight / +0.1 volume re-consumed.
        assert slot["used_weight_kg"] == 70
        assert slot["used_volume_m3"] == 0.9

        b3 = get_success_data(api.get_delivery_booking(s["b3"]["id"], cust_headers(customer)))
        assert b3["status"] == "CONFIRMED", (
            "the oldest fitting waitlisted booking is promoted by the cancel"
        )
        o3 = get_success_data(api.get_order(s["o3"]["id"], cust_headers(customer)))
        assert o3["delivery_status"] == "SCHEDULED"
        stock30 = get_success_data(api.get_bin_stock(s["stock30"]["id"], OPS))
        assert stock30["reserved"] == 1, "promotion reserves the stock per carton"

    def test_promotion_consumes_capacity_and_later_waitlist_still_waits(self, api):
        """PRD §3.5: "The scan walks that order greedily: a candidate that
        fits the remaining capacity is promoted to `CONFIRMED` — consuming
        slot capacity, bumping the slot's `version`, reserving its stock per
        carton per line, and moving its order's `delivery_status` to
        `SCHEDULED` — while a candidate that does not fit is skipped so
        smaller candidates behind it still get their chance."

        Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_to_order
        """
        store, customer = setup_store_and_customer()
        s = self._three_order_scenario(api, customer, store)
        # A fourth booking of the same 60 kg article (stock on_hand 2, only one
        # reserved by B1 so far) is waitlisted behind B3.
        b1_lines = get_success_data(api.list_order_lines(s["o1"]["id"], cust_headers(customer)))
        a60_id = b1_lines[0]["article_id"]
        o4, _ = setup_delivery_paid_order(customer, store, {"id": a60_id}, qty=1)
        b4 = create_booking(customer, o4["id"], s["slot"]["id"],
                            expected_slot_version=current_slot_version(s["slot"]["id"]))
        assert b4["status"] == "WAITLISTED"

        validate_success(api.cancel_delivery_booking(s["b1"]["id"], cust_headers(customer)))

        b3 = get_success_data(api.get_delivery_booking(s["b3"]["id"], cust_headers(customer)))
        b4_after = get_success_data(api.get_delivery_booking(b4["id"], cust_headers(customer)))
        assert b3["status"] == "CONFIRMED"
        # 40 (B2) + 30 (B3 promoted) = 70; 70 + 60 > 100 so B4 stays waiting.
        assert b4_after["status"] == "WAITLISTED", (
            "the 60 kg candidate does not fit after promotion consumes 30 kg"
        )
        o4_after = get_success_data(api.get_order(o4["id"], cust_headers(customer)))
        assert o4_after["delivery_status"] == "WAITLISTED"


class TestAssemblyCompleteClosesOrderCreditsPoints:
    """Instance: assembly_complete_closes_order_credits_points."""

    def _delivered_order_with_started_job(self, api, member, store):
        article, _, stock = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(10, 0.1, 2)],
            requires_assembly=True, register_standard_minutes=30,
        )
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=100, capacity_volume_m3=2.0)
        order, _ = setup_delivery_paid_order(member, store, article, qty=1)
        booking = create_booking(member, order["id"], slot["id"],
                                 expected_slot_version=slot["version"])
        assert booking["status"] == "CONFIRMED"
        validate_success(api.start_delivery_booking(booking["id"], COORD))
        validate_success(api.complete_delivery_booking(booking["id"], COORD))
        job = create_assembly_job(member, order["id"], provider_id="CREW-B",
                                  window_start="2026-09-12T09:00:00Z",
                                  window_end="2026-09-12T11:00:00Z")
        validate_success(api.dispatch_assembly_job(job["id"], PROVIDER))
        job = validate_success(api.start_assembly_job(job["id"], PROVIDER))
        return order, booking, job

    def test_completion_cascades_job_order_close_and_points(self, api):
        """PRD §3.6: "Completion moves the order's `assembly_status` to
        `COMPLETED` and immediately triggers the auto-close evaluation: an
        order sitting in `FULFILLED` or `DELIVERED` closes on the spot,
        crediting `points_earned` to an `ACTIVE` member's balance as in §3.3."
        PRD §3.3: "if the customer is an `ACTIVE` member the server computes
        `points_earned` as the whole-dollar floor of `total_cents` divided by
        100 and adds those points to the customer's `points_balance`"

        Design: Difficulty/transitive_cascade/assembly_complete_closes_order_credits_points
        """
        store, member = setup_store_and_customer(member=True)
        order, booking, job = self._delivered_order_with_started_job(api, member, store)
        assert job["estimated_minutes"] == 30

        completed = validate_success(
            api.complete_assembly_job(job["id"], {"actual_minutes": 20}, PROVIDER))
        # hop 1: job completes; billed = min(20, ceil(30 x 1.5) = 45) = 20.
        assert completed["status"] == "COMPLETED"
        assert completed["billed_minutes"] == 20

        order_after = get_success_data(api.get_order(order["id"], cust_headers(member)))
        # hop 2 + 3: assembly completed -> order auto-closed.
        assert order_after["assembly_status"] == "COMPLETED"
        assert order_after["status"] == "CLOSED"
        # hop 4: points credited, floor(1000/100) = 10.
        assert order_after["points_earned"] == 10
        customer_after = get_success_data(api.get_customer(member["id"], OPS))
        assert customer_after["points_balance"] == 10

    def test_delivery_completion_does_not_close_order_while_assembly_pending(self, api):
        """PRD §3.5: "the auto-close evaluation runs — if the order's assembly
        has already completed, the order closes on the spot with the usual
        points accrual."
        PRD §3.3: "the order's `assembly_status` must be `NONE` or `COMPLETED`"

        Design: Difficulty/transitive_cascade/assembly_complete_closes_order_credits_points
        """
        store, member = setup_store_and_customer(member=True)
        order, booking, job = self._delivered_order_with_started_job(api, member, store)

        # After booking completion the order is DELIVERED but NOT closed,
        # because assembly_status is IN_PROGRESS at that point.
        after_delivery = get_success_data(api.get_order(order["id"], cust_headers(member)))
        assert after_delivery["status"] == "DELIVERED"
        assert after_delivery["assembly_status"] == "IN_PROGRESS"
        customer_mid = get_success_data(api.get_customer(member["id"], OPS))
        assert customer_mid["points_balance"] == 0, (
            "no points are credited before the order closes"
        )

        # Assembly completion at exactly the cap still closes and credits.
        validate_success(api.complete_assembly_job(job["id"], {"actual_minutes": 45}, PROVIDER))
        job_after = get_success_data(api.get_assembly_job(job["id"], PROVIDER))
        assert job_after["billed_minutes"] == 45  # min(45, ceil(30 x 1.5) = 45)
        after = get_success_data(api.get_order(order["id"], cust_headers(member)))
        assert after["status"] == "CLOSED"
        assert after["points_earned"] == 10

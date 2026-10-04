"""Difficulty rule: compensating_invariant — inventory and slot capacity
conservation across action/compensation pairs."""
from test_helpers import (
    OPS,
    add_return_line,
    create_booking,
    create_delivery_slot,
    create_return,
    cust_headers,
    get_success_data,
    grade_line,
    settle_return,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_fulfilled_order,
    setup_store_and_customer,
    submit_return,
    validate_success,
)


class TestCheckoutAndLikeNewReturnConserveOnHand:
    """Instance: checkout_and_likenew_return_conserve_on_hand."""

    def test_checkout_then_likenew_return_restores_on_hand(self, api):
        """PRD §3.8: "a receipted line graded `LIKE_NEW` goes back on the
        shelf — `on_hand` increases by the quantity on every carton of the
        article, the line's `restocked_units` records how many, and the order
        line's `returned_qty` grows by the quantity."
        PRD §3.3: "On a `CARRYOUT` order, every `SELF_PICK` line decrements
        `on_hand` by the line quantity on every carton of its article"

        Design: Difficulty/compensating_invariant/checkout_and_likenew_return_conserve_on_hand
        """
        store, customer = setup_store_and_customer()
        article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
        stock = stocks[0]

        order, order_lines = setup_fulfilled_order(customer, store, [(article, 2)])
        mid = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert mid["on_hand"] == 3, "forward checkout decremented on_hand by 2"

        ret = create_return(customer, order_id=order["id"])
        ret_line = add_return_line(customer, ret["id"], article["id"], qty=2,
                                   order_line_id=order_lines[0]["id"])
        submit_return(customer, ret["id"])
        grade_line(ret["id"], ret_line["id"], "LIKE_NEW")
        settled = settle_return(ret["id"])

        after = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert after["on_hand"] == 5, (
            f"compensating LIKE_NEW return restores the initial on_hand 5, got {after['on_hand']}"
        )
        assert after["reserved"] == 0
        assert settled["refund_total_cents"] == 1000
        assert settled["writeoff_total_cents"] == 0
        line_after = get_success_data(
            api.get_order_line(order_lines[0]["id"], cust_headers(customer)))
        assert line_after["returned_qty"] == 2

    def test_round_trip_conserves_on_hand_with_reserved_zero_throughout(self, api):
        """PRD §3.8: "a receipted line graded `LIKE_NEW` goes back on the
        shelf — `on_hand` increases by the quantity on every carton of the
        article"
        PRD §3.1: "`reserved` counts units promised to active reservations or
        confirmed delivery bookings and must stay between 0 and `on_hand`
        inclusive"

        Design: Difficulty/compensating_invariant/checkout_and_likenew_return_conserve_on_hand
        """
        store, customer = setup_store_and_customer()
        article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
        stock = stocks[0]

        order, order_lines = setup_fulfilled_order(customer, store, [(article, 2)])
        mid = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert mid["reserved"] == 0, "CARRYOUT self-pick never reserves"

        ret = create_return(customer, order_id=order["id"])
        ret_line = add_return_line(customer, ret["id"], article["id"], qty=2,
                                   order_line_id=order_lines[0]["id"])
        submit_return(customer, ret["id"])
        grade_line(ret["id"], ret_line["id"], "LIKE_NEW")
        settle_return(ret["id"])

        after = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert after["on_hand"] == 5
        assert after["reserved"] == 0
        assert after["available"] == 5


class TestBookingAndCancelConserveSlotCapacity:
    """Instance: booking_and_cancel_conserve_slot_capacity."""

    def _confirmed_booking(self, api, customer, store):
        article, _, stocks = setup_article_with_stock(
            store, on_hand=2, price_cents=1000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(60, 1.0, 2)],
        )
        slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                    capacity_weight_kg=100, capacity_volume_m3=2.0)
        order, _ = setup_delivery_paid_order(customer, store, article, qty=1)
        booking = create_booking(customer, order["id"], slot["id"],
                                 expected_slot_version=slot["version"])
        assert booking["status"] == "CONFIRMED"
        return order, booking, slot, stocks[0]

    def test_booking_then_cancel_restores_capacity_and_releases_stock(self, api):
        """PRD §3.5: "cancelling a `CONFIRMED` booking releases its capacity
        from the slot's used figures, bumps the slot's `version` by 1,
        releases the `reserved` stock per carton per line, returns the order's
        `delivery_status` to `NONE`, and triggers a waitlist-promotion scan of
        the slot"
        PRD §3.5: "On a `DELIVERY` order, checkout moves no stock at all;
        reservation happens later, when a delivery booking is confirmed."
        (movement symmetry: DELIVERY checkout is at §3.3)

        Design: Difficulty/compensating_invariant/booking_and_cancel_conserve_slot_capacity
        """
        store, customer = setup_store_and_customer()
        order, booking, slot, stock = self._confirmed_booking(api, customer, store)

        # Mid-state sanity: capacity consumed, stock reserved but not sold.
        mid_slot = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
        assert mid_slot["used_weight_kg"] == 60
        mid_stock = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert mid_stock["reserved"] == 1
        assert mid_stock["on_hand"] == 2

        cancelled = validate_success(
            api.cancel_delivery_booking(booking["id"], cust_headers(customer)))
        assert cancelled["status"] == "CANCELLED"

        slot_after = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
        assert slot_after["used_weight_kg"] == 0
        assert slot_after["used_volume_m3"] == 0
        assert slot_after["capacity_weight_kg"] == 100, "capacity itself never changes"
        stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert stock_after["reserved"] == 0
        assert stock_after["on_hand"] == 2
        order_after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert order_after["delivery_status"] == "NONE"

    def test_cancel_bumps_slot_version_and_order_is_rebookable(self, api):
        """PRD §3.5: "cancelling a `CONFIRMED` booking releases its capacity
        from the slot's used figures, bumps the slot's `version` by 1,
        releases the `reserved` stock per carton per line, returns the order's
        `delivery_status` to `NONE`, and triggers a waitlist-promotion scan of
        the slot"
        PRD §2.4: "`version` is an integer that starts at 1 when the resource
        is created and increments by exactly 1 on every mutation, including
        mutations caused by cascades from other resources"

        Design: Difficulty/compensating_invariant/booking_and_cancel_conserve_slot_capacity
        """
        store, customer = setup_store_and_customer()
        order, booking, slot, stock = self._confirmed_booking(api, customer, store)
        v_before_cancel = get_success_data(
            api.get_delivery_slot(slot["id"], cust_headers(customer)))["version"]

        validate_success(api.cancel_delivery_booking(booking["id"], cust_headers(customer)))

        slot_after = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
        assert slot_after["version"] == v_before_cancel + 1
        assert slot_after["used_weight_kg"] == 0

        # delivery_status NONE again: the same order can be re-booked.
        rebooked = create_booking(customer, order["id"], slot["id"],
                                  expected_slot_version=slot_after["version"])
        assert rebooked["status"] == "CONFIRMED"
        stock_final = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert stock_final["reserved"] == 1

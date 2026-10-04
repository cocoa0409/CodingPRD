"""Compensating invariants: the plan money invariant across refunds and the
inventory conservation invariant across receive/lock/ship/reship
(PRD §3.9, §3.11, §2.10)."""
from test_helpers import (
    ADMIN,
    SUPPORT,
    api_client,
    assert_inventory_conservation,
    get_placement,
    get_plan,
    get_success_data,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    ship_plan,
    setup_delivered_plan,
    setup_reported_claim,
    validate_success,
)


class TestMoneyInvariant:
    def _setup(self):
        return setup_reported_claim(num_subscriptions=3, price_cents=1000,
                                    units=50)

    def test_damage_refund_preserves_gross_line_total_invariant(self):
        """PRD §3.11: "A refund approval completes the claim immediately:
        `claim_refund_cents` is set to the sum of the damaged lines'
        `line_charged_cents`, every damaged line moves to `REFUNDED`, and the
        plan's `refunded_total_cents` increases by the same amount."
        PRD §3.9: "For every plan that has been locked,
        `gross_line_total_cents` always equals the sum of
        `line_charged_cents` over lines in `SHIPPED` or `RESHIPPED` status,
        plus `refunded_total_cents`, plus the sum of `line_charged_cents`
        over lines still `SCHEDULED`."

        Design: Difficulty/compensating_invariant/damage_refund_preserves_gross_line_total_invariant
        """
        customer, product, placement, subs, plan, line, claim = self._setup()
        reviewed = validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"}, SUPPORT))
        assert reviewed["claim_status"] == "COMPLETED"
        assert reviewed["claim_refund_cents"] == 950
        line_after = get_success_data(api_client.get_plan_line(
            line["id"], make_customer_headers(customer["id"])))
        assert line_after["line_status"] == "REFUNDED"
        plan_after = get_plan(plan["id"], as_customer=customer)
        assert plan_after["refunded_total_cents"] == 950
        assert plan_after["gross_line_total_cents"] == 2850

    def test_money_invariant_holds_exactly_after_refund(self):
        """PRD §3.9: "Refunds and reshipments redistribute value across these
        buckets; they never create or destroy it."

        Design: Difficulty/compensating_invariant/damage_refund_preserves_gross_line_total_invariant
        """
        customer, product, placement, subs, plan, line, claim = self._setup()
        validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"}, SUPPORT))
        plan_after = get_plan(plan["id"], as_customer=customer)
        lines = list_plan_lines(plan, as_customer=customer)
        shipped_sum = sum(ln["line_charged_cents"] for ln in lines
                          if ln["line_status"] in ("SHIPPED", "RESHIPPED"))
        scheduled_sum = sum(ln["line_charged_cents"] for ln in lines
                            if ln["line_status"] == "SCHEDULED")
        assert (shipped_sum + plan_after["refunded_total_cents"] + scheduled_sum
                == plan_after["gross_line_total_cents"] == 2850)


class TestInventoryConservation:
    def _setup_to_approved_reship(self):
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(quantity=4, units=10, price_cents=1000))
        validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT))
        reshipments = get_success_data(
            api_client.list_claim_reshipments(claim["id"], SUPPORT))
        return customer, product, placement, plan, line, claim, reshipments[0]

    def test_conservation_holds_at_lock_ship_and_dispatch_stages(self):
        """PRD §2.10: "Every InventoryPlacement ledger-conserves its units. At
        all times, `received_total_units` equals the sum of `on_hand_units`,
        `reserved_units`, and `shipped_units`."

        Design: Difficulty/compensating_invariant/inventory_conservation_across_receive_lock_ship_reship
        """
        (customer, product, placement, plan, line, claim,
         reshipment) = self._setup_to_approved_reship()
        placement_now = get_placement(placement["id"])
        # After ship the reservation has been released into shipped.
        assert placement_now["on_hand_units"] == 6
        assert placement_now["reserved_units"] == 0
        assert placement_now["shipped_units"] == 4
        assert_inventory_conservation(placement_now)
        dispatched = validate_success(
            api_client.dispatch_reshipment(reshipment["id"], ADMIN))
        assert dispatched["reshipment_status"] == "DISPATCHED"
        placement_after = get_placement(placement["id"])
        assert placement_after["on_hand_units"] == 2
        assert placement_after["reserved_units"] == 0
        assert placement_after["shipped_units"] == 8
        assert_inventory_conservation(placement_after)
        assert placement_after["received_total_units"] == 10

    def test_conservation_holds_immediately_after_lock_and_ship(self):
        """PRD §2.10: "Receiving stock adds to `received_total_units` and
        `on_hand_units`; locking a plan moves quantity from `on_hand_units`
        into `reserved_units`; shipping a plan moves it from `reserved_units`
        into `shipped_units`; dispatching a reshipment moves it directly from
        `on_hand_units` into `shipped_units`."

        Design: Difficulty/compensating_invariant/inventory_conservation_across_receive_lock_ship_reship
        """
        customer, product, placement, subs, plan = setup_delivered_plan(
            quantity=4, units=10, price_cents=1000)
        placement_after = get_placement(placement["id"])
        assert placement_after["on_hand_units"] == 6
        assert placement_after["reserved_units"] == 0
        assert placement_after["shipped_units"] == 4
        assert_inventory_conservation(placement_after)

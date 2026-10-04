"""Transitive cascades: delivery and credit-approval ripple through lot, day,
and settlement."""
from test_helpers import (
    api_client,
    balance_settlement,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_settlement,
    create_store,
    create_stale_credit,
    deliver_line,
    deliver_order,
    get_lot_by_code,
    get_route_day,
    get_settlement,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_success,
)


class TestDeliveryCascadesThroughLotDayAndSettlement:
    def _setup(self):
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

        order1 = create_order(
            day["id"], store["id"], [order_line(product["id"], 30)], rep
        )
        submit_order(order1["id"], rep)
        deliver_order(order1["id"], [deliver_line(product["id"], 30)], rep)
        settlement = create_settlement(day["id"])

        order2 = create_order(
            day["id"], store["id"], [order_line(product["id"], 20)], rep
        )
        submit_order(order2["id"], rep)
        return rep, product, day, settlement, order2

    def test_delivery_recomputes_lot_day_and_open_settlement(self, api):
        """PRD §3.5: "A successful delivery stamps delivered_at with the logical
        clock, moves the order to DELIVERED, increments its version, and
        triggers two recomputes: the route day's delivered_cases refreshes from
        the lots, and if a settlement already exists for the day in OPEN
        status, its gross_delivered_cents, forward_expected_cents, and
        chronological_expected_cents are recomputed as well — a settlement in
        BALANCED auto-reopens to OPEN on the same trigger (see §3.9)."

        Design: Difficulty/transitive_cascade/delivery_cascades_through_lot_day_and_settlement
        """
        rep, product, day, settlement, order2 = self._setup()

        resp = api.deliver_order(
            order2["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 20}]},
            make_rep_headers(rep["id"]),
        )
        validate_success(resp)

        lot = get_lot_by_code(day["id"], "L-1")
        assert lot["delivered_cases"] == 50

        day_after = get_route_day(day["id"])
        assert day_after["delivered_cases"] == 50

        s = get_settlement(settlement["id"])
        assert s["gross_delivered_cents"] == 25000
        assert s["chronological_expected_cents"] == 25000
        assert s["forward_expected_cents"] == 25000

    def test_each_hop_caused_by_previous_hop(self, api):
        """PRD §2.4: "Whenever a truck lot is mutated (cases delivered, stales
        approved, returns posted), the parent route day's loaded_cases,
        delivered_cases, and stale_pulled_cases totals are recomputed from the
        lots, and the route day's own updated_at and version advance
        accordingly."

        Design: Difficulty/transitive_cascade/delivery_cascades_through_lot_day_and_settlement
        """
        rep, product, day, settlement, order2 = self._setup()

        # Before the second delivery the lot and day already show the first 30.
        lot = get_lot_by_code(day["id"], "L-1")
        assert lot["delivered_cases"] == 30
        assert get_route_day(day["id"])["delivered_cases"] == 30
        s_before = get_settlement(settlement["id"])
        assert s_before["gross_delivered_cents"] == 15000

        resp = api.deliver_order(
            order2["id"],
            {"lines": [{"product_id": product["id"], "qty_delivered_cases": 20}]},
            make_rep_headers(rep["id"]),
        )
        validate_success(resp)

        # All three levels moved by exactly the 20-case delta.
        lot = get_lot_by_code(day["id"], "L-1")
        assert lot["delivered_cases"] == 50
        assert get_route_day(day["id"])["delivered_cases"] == 50
        s_after = get_settlement(settlement["id"])
        assert (
            s_after["gross_delivered_cents"]
            == s_before["gross_delivered_cents"] + 10000
        )


class TestCreditApprovalReopensBalancedSettlement:
    def _setup(self):
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

        settlement = create_settlement(day["id"])
        settlement = balance_settlement(settlement["id"], 25000)
        assert settlement["status"] == "BALANCED"

        credit = create_stale_credit(
            day["id"], store["id"], product["id"], 5, make_rep_headers(rep["id"])
        )
        return rep, product, day, settlement, credit

    def test_approval_recomputes_credits_and_auto_reopens(self, api):
        """PRD §3.7: "Approval stamps decided_by_user_id, moves the credit to
        APPROVED (terminal), and only now mutates inventory: the pinned lot's
        stale_pulled_cases increases by qty_cases, the route day's stale totals
        recompute from the lots, and if a settlement exists for the day its
        credits_cents and both expected variants recompute — with a BALANCED
        settlement auto-reopening to OPEN."

        Design: Difficulty/transitive_cascade/credit_approval_reopens_balanced_settlement_via_lot_and_day
        """
        rep, product, day, settlement, credit = self._setup()

        resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"

        assert get_route_day(day["id"])["stale_pulled_cases"] == 5

        s = get_settlement(settlement["id"])
        assert s["credits_cents"] == 2500
        assert s["status"] == "OPEN"
        assert s["chronological_expected_cents"] == 22500

        # A fresh balance at the moved expectation balances again.
        s2 = balance_settlement(settlement["id"], 22500)
        assert s2["status"] == "BALANCED"

    def test_balanced_settlement_stale_when_ledger_moves(self, api):
        """PRD §3.9: "A BALANCED settlement is stale the moment the underlying
        ledger moves: any subsequent delivery or stale-credit approval for the
        day auto-reopens it to OPEN, retaining cash_collected_cents for the
        next balance."

        Design: Difficulty/transitive_cascade/credit_approval_reopens_balanced_settlement_via_lot_and_day
        """
        rep, product, day, settlement, credit = self._setup()

        resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
        validate_success(resp)

        s = get_settlement(settlement["id"])
        assert s["status"] == "OPEN"
        # cash_collected_cents retained across the auto-reopen.
        assert s["cash_collected_cents"] == 25000
        # Both expected variants recomputed after the approval.
        assert s["chronological_expected_cents"] == 22500
        # Forward: lot A (100 - 0 - 50) * 500 + lot B (10 - 5 - 5) * 500 - 2500.
        assert s["forward_expected_cents"] == 22500

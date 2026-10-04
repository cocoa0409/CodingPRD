"""Compensating invariants: truck-case conservation and money conservation."""
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


class TestTruckCaseConservation:
    def _setup(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"], base_capacity_cases=120)
        create_assignment(route["id"], store["id"], service_weekdays=["TUE", "WED"])

        # Day D1: 100 fresh + 10 stale; 50 delivered; 5-case credit approved;
        # settlement opened and balanced at the moved expectation.
        day1 = create_route_day(route["id"], service_date="2026-09-01")
        load_route_day(
            day1["id"],
            [
                lot_entry(product["id"], "L-A", "2026-09-20", 100),
                lot_entry(product["id"], "L-B", "2026-09-06", 10),
            ],
            rep,
        )
        start_route_day(day1["id"], rep)
        order = create_order(
            day1["id"], store["id"], [order_line(product["id"], 50)], rep
        )
        submit_order(order["id"], rep)
        deliver_order(order["id"], [deliver_line(product["id"], 50)], rep)
        credit = create_stale_credit(
            day1["id"], store["id"], product["id"], 5, make_rep_headers(rep["id"])
        )
        resp = api_client.approve_stale_credit(credit["id"], make_supervisor_headers())
        validate_success(resp)
        settlement = create_settlement(day1["id"])
        settlement = balance_settlement(settlement["id"], 22500)
        assert settlement["status"] == "BALANCED"

        # Day D2: loaded with 60 cases, never started.
        day2 = create_route_day(route["id"], service_date="2026-09-02")
        load_route_day(
            day2["id"], [lot_entry(product["id"], "L-C", "2026-09-20", 60)], rep
        )
        return rep, product, day1, day2, settlement

    def test_settle_and_cancel_both_restore_conservation(self, api):
        """PRD §2.4: "A strict conservation invariant governs every truck lot at
        all times: a lot's remaining_cases is always its loaded_cases minus its
        delivered_cases minus its stale_pulled_cases minus its returned_cases."

        Design: Difficulty/compensating_invariant/truck_case_conservation_through_settle_and_cancel
        """
        rep, product, day1, day2, settlement = self._setup()

        # Settle D1.
        resp = api_client.post_settlement(settlement["id"], make_supervisor_headers())
        validate_success(resp)
        # Cancel D2 from LOADED.
        resp = api_client.cancel_route_day(day2["id"], make_supervisor_headers())
        validate_success(resp)

        lot_a = get_lot_by_code(day1["id"], "L-A")
        assert lot_a["loaded_cases"] == 100
        assert lot_a["delivered_cases"] == 50
        assert lot_a["stale_pulled_cases"] == 0
        assert lot_a["returned_cases"] == 50
        assert lot_a["remaining_cases"] == 0
        assert lot_a["status"] == "CLOSED"

        lot_b = get_lot_by_code(day1["id"], "L-B")
        assert lot_b["loaded_cases"] == 10
        assert lot_b["delivered_cases"] == 0
        assert lot_b["stale_pulled_cases"] == 5
        assert lot_b["returned_cases"] == 5
        assert lot_b["remaining_cases"] == 0
        assert lot_b["status"] == "CLOSED"

        lot_c = get_lot_by_code(day2["id"], "L-C")
        assert lot_c["loaded_cases"] == 60
        assert lot_c["delivered_cases"] == 0
        assert lot_c["stale_pulled_cases"] == 0
        assert lot_c["returned_cases"] == 60
        assert lot_c["remaining_cases"] == 0

    def test_post_settles_day_cancel_compensates_full_load(self, api):
        """PRD §3.9: "posting stamps posted_at with the logical clock, moves the
        settlement to POSTED (terminal), settles the route day itself
        (IN_PROGRESS → SETTLED), and closes the truck: every OPEN lot's
        returned_cases is set to its remaining_cases and its status to CLOSED,
        so all unsold, un-staled cases return to depot."
        PRD §3.3: "canceling a LOADED day sets every lot's returned_cases to
        its loaded_cases minus delivered minus stale-pulled — which equals the
        full loaded quantity because no movement is possible before start —
        closes every lot to CLOSED, recomputes the day's totals so the
        conservation invariant is restored with all cases returned, and moves
        the day to CANCELLED."

        Design: Difficulty/compensating_invariant/truck_case_conservation_through_settle_and_cancel
        """
        rep, product, day1, day2, settlement = self._setup()

        resp = api_client.post_settlement(settlement["id"], make_supervisor_headers())
        posted = validate_success(resp)
        assert posted["status"] == "POSTED"
        assert posted["posted_at"] is not None

        resp = api_client.cancel_route_day(day2["id"], make_supervisor_headers())
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        assert get_route_day(day1["id"])["status"] == "SETTLED"
        assert get_route_day(day2["id"])["status"] == "CANCELLED"


class TestMoneyConservationThroughRejectCompensation:
    def _setup(self):
        """90 fresh + 10 stale; orders 30 (15000) and 20 at 10% (9000)
        delivered; 5-case credit approved (2500); settlement opened; second
        2-case credit pending."""
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
                lot_entry(product["id"], "L-A", "2026-09-20", 90),
                lot_entry(product["id"], "L-B", "2026-09-06", 10),
            ],
            rep,
        )
        start_route_day(day["id"], rep)

        order1 = create_order(
            day["id"], store["id"], [order_line(product["id"], 30)], rep
        )
        submit_order(order1["id"], rep)
        deliver_order(order1["id"], [deliver_line(product["id"], 30)], rep)
        order2 = create_order(
            day["id"],
            store["id"],
            [order_line(product["id"], 20, line_discount_pct=0.10)],
            rep,
        )
        submit_order(order2["id"], rep)
        deliver_order(order2["id"], [deliver_line(product["id"], 20)], rep)

        credit1 = create_stale_credit(
            day["id"], store["id"], product["id"], 5, make_rep_headers(rep["id"])
        )
        resp = api_client.approve_stale_credit(credit1["id"], make_supervisor_headers())
        validate_success(resp)

        settlement = create_settlement(day["id"])

        credit2 = create_stale_credit(
            day["id"], store["id"], product["id"], 2, make_rep_headers(rep["id"])
        )
        return rep, product, day, settlement, credit2

    def test_reject_leaves_credits_unchanged(self, api):
        """PRD §3.7: "Rejection requires a reject_reason (ERR_VALIDATION when
        omitted), stamps decided_by_user_id, and leaves lots and settlement
        untouched."
        PRD §3.9: "credits_cents is the sum of credit_cents over the day's
        APPROVED stale credits."

        Design: Difficulty/compensating_invariant/money_conservation_gross_equals_net_plus_credits_through_reject_compensation
        """
        rep, product, day, settlement, credit2 = self._setup()

        resp = api_client.reject_stale_credit(
            credit2["id"], {"reject_reason": "insufficient evidence"},
            make_supervisor_headers(),
        )
        rejected = validate_success(resp)
        assert rejected["status"] == "REJECTED"

        s = get_settlement(settlement["id"])
        # The PENDING credit never entered credits_cents, and the rejection
        # leaves the ledger untouched.
        assert s["credits_cents"] == 2500
        assert s["gross_delivered_cents"] == 24000
        assert s["status"] == "OPEN"

    def test_gross_equals_net_plus_credits_exactly(self, api):
        """PRD §3.9: "gross_delivered_cents is the sum of line_total_cents over
        the day's DELIVERED orders (per-line priced, discounts included);
        credits_cents is the sum of credit_cents over the day's APPROVED stale
        credits; and chronological_expected_cents is the gross minus the
        credits."

        Design: Difficulty/compensating_invariant/money_conservation_gross_equals_net_plus_credits_through_reject_compensation
        """
        rep, product, day, settlement, credit2 = self._setup()

        resp = api_client.reject_stale_credit(
            credit2["id"], {"reject_reason": "insufficient evidence"},
            make_supervisor_headers(),
        )
        validate_success(resp)

        s = get_settlement(settlement["id"])
        assert s["chronological_expected_cents"] == 21500
        assert s["chronological_expected_cents"] + s["credits_cents"] == 24000
        assert s["chronological_expected_cents"] + s["credits_cents"] == s["gross_delivered_cents"]

"""Compensating invariants: production capacity conserved across submit/cancel,
and DC crew units conserved across confirm/cancel (PRD §3.4, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_cycle_capacity_conserved,
    book_appointment,
    cancel_appointment,
    cancel_order,
    confirm_appointment,
    create_hd_order,
    create_licensee_order,
    get_cycle,
    get_order,
    pick_order,
    run_cycle,
    setup_hd_context,
    setup_open_cycle,
    submit_order,
    validate_error,
)

WS = "2026-09-10T09:00:00Z"
WE = "2026-09-10T12:00:00Z"


class TestCycleCapacityConserved:
    """Difficulty instance: cycle_capacity_conserved_across_submit_and_cancel.
    Cycle capacity 100; the invariant
    capacity_units == licensee_reserved + wholesale_reserved + available
    must hold before, during, and after a submit paired with its cancel."""

    def test_submit_reserves_and_conserves_capacity(self, api, production_planner_headers):
        """PRD §3.4: "Each cycle tracks three counters: `licensee_reserved_units`, the
        total quantity of the cycle's orders placed by licensee buyers that currently
        hold capacity (allocation state `RESERVED` or `ALLOCATED`);
        `wholesale_reserved_units`, the same total for retail-account buyers; and
        `available_units`, defined as `capacity_units` minus those two reserved counters
        and never negative."

        Design: Difficulty/compensating_invariant/cycle_capacity_conserved_across_submit_and_cancel
        """
        ctx = setup_open_cycle()
        cycle = get_cycle(ctx["cycle"]["id"])
        assert (cycle["licensee_reserved_units"], cycle["wholesale_reserved_units"],
                cycle["available_units"]) == (0, 0, 100)
        assert_cycle_capacity_conserved(cycle)

        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=5
        )
        submit_order(order)
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["licensee_reserved_units"] == 5
        assert cycle["available_units"] == 95
        assert_cycle_capacity_conserved(cycle)

    def test_cancel_releases_capacity_exactly(self, api, production_planner_headers):
        """PRD §3.5: "Cancellation flips the order to `DROPPED` and its fulfillment to
        `CANCELLED` in the same mutation, releases any held capacity with the cycle
        counters recomputed, recomputes the retail buyer's credit where applicable, and
        runs the promotion sweep on the affected cycle (§3.4)."

        Design: Difficulty/compensating_invariant/cycle_capacity_conserved_across_submit_and_cancel
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=5
        )
        submit_order(order)
        cancel_order(get_order(order["id"]), reason="duplicate")
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["licensee_reserved_units"] == 0, (
            "cancelled reservation must be fully released"
        )
        assert cycle["available_units"] == 100
        assert_cycle_capacity_conserved(cycle)
        dropped = get_order(order["id"])
        assert dropped["allocation_state"] == "DROPPED"
        assert dropped["fulfillment_state"] == "CANCELLED"


class TestCrewUnitsConserved:
    """Difficulty instance: crew_units_conserved_across_confirm_and_cancel.
    DC crew 6; AP1 (crew 3) and AP2 (crew 4) share the window 09:00-12:00."""

    def _setup_two_appointments(self):
        ctx = setup_hd_context()
        o1 = create_hd_order(ctx, quantity=1)
        o2 = create_hd_order(ctx, quantity=1)
        submit_order(o1)
        submit_order(o2)
        run_cycle(ctx["cycle"]["id"])
        pick_order(o1["id"])
        pick_order(o2["id"])
        # REQUESTED appointments hold no capacity, so both bookings succeed.
        ap1 = book_appointment(o1, ctx, WS, WE, crew_units=3)
        ap2 = book_appointment(o2, ctx, WS, WE, crew_units=4)
        return ctx, o1, o2, ap1, ap2

    def test_confirm_rechecks_capacity_and_rejects_overflow(self, api, logistics_coordinator_headers):
        """PRD §3.6: "Crew capacity is an aggregate overlap check, enforced both at
        booking and again at confirmation, and only `CONFIRMED` appointments hold
        capacity — `REQUESTED` appointments hold none."
        PRD §3.6: "The booking or confirmation is rejected with
        `ERR_DELIVERY_CAPACITY_EXCEEDED` if there exists any instant within the
        candidate window at which the sum of `crew_units` over the DC's `CONFIRMED`
        appointments covering that instant, plus the candidate's own `crew_units`, would
        exceed the DC's `daily_crew_units`."

        Design: Difficulty/compensating_invariant/crew_units_conserved_across_confirm_and_cancel
        """
        _, _o1, _o2, ap1, ap2 = self._setup_two_appointments()
        confirm_appointment(ap1["id"])  # 3 crew held
        resp = api.transition_delivery_appointment(
            ap2["id"], {"to_state": "CONFIRMED"}, logistics_coordinator_headers
        )
        # 3 held + 4 requested == 7 > 6.
        validate_error(resp, ApiErrorId.ERR_DELIVERY_CAPACITY_EXCEEDED.value)

    def test_cancel_releases_crew_and_reverts_order(self, api, logistics_coordinator_headers):
        """PRD §3.6: "Cancelling a `CONFIRMED` appointment (`CONFIRMED → CANCELLED`,
        same two actors, or the system during a territory revocation of §3.2) reverts
        the order `SHIPPED → PICKED`, making it eligible for a fresh booking."
        PRD §3.6: "on success the appointment's order moves `PICKED → SHIPPED` — the
        furniture is out for delivery."

        Design: Difficulty/compensating_invariant/crew_units_conserved_across_confirm_and_cancel
        """
        ctx, o1, _o2, ap1, ap2 = self._setup_two_appointments()
        confirm_appointment(ap1["id"])
        assert get_order(o1["id"])["fulfillment_state"] == "SHIPPED"
        # Owner cancels the CONFIRMED appointment: crew pool restored to 6.
        cancel_appointment(ap1["id"], as_licensee_id=ctx["licensee"]["id"])
        assert get_order(o1["id"])["fulfillment_state"] == "PICKED", (
            "cancelling a CONFIRMED appointment must revert its order SHIPPED -> PICKED"
        )
        confirmed = confirm_appointment(ap2["id"])
        assert confirmed["status"] == "CONFIRMED"

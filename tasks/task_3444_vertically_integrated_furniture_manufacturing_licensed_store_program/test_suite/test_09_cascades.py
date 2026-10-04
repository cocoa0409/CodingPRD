"""Transitive cascades: licensee termination (territory -> appointment -> order
-> capacity) and product-line retirement (order drop -> credit release)
(PRD §3.1, §3.2, §3.4)."""
from test_helpers import (
    WEEK_1_START,
    advance_product_line,
    assert_cycle_capacity_conserved,
    book_appointment,
    confirm_appointment,
    create_active_licensee,
    create_cycle,
    create_factory,
    create_hd_order,
    create_licensee_order,
    create_retail_account,
    create_retail_order,
    get_cycle,
    get_order,
    get_retail_account,
    get_territory,
    pick_order,
    run_cycle,
    setup_catalog,
    setup_hd_context,
    setup_open_cycle,
    submit_order,
    transition_licensee,
    validate_success,
)


def _setup_termination_scenario():
    """Factory cap 10; Summit (ACTIVE, holds T-SEA, DC-KENT covers T-SEA) and
    Prairie (ACTIVE); cycle week 1. HD2: Summit home-delivery qty 1; LA: Summit
    freight qty 6; LB: Prairie freight qty 5 (waitlisted at submit). Run
    allocates HD2 and LA; HD2 is picked and its appointment CONFIRMED
    (SHIPPED). Returns the context dict."""
    ctx = setup_hd_context(
        factory_over={
            "code": "FAC-T3",
            "region": "DOMESTIC",
            "component_lines": ["FOAM", "FRAMES"],
            "weekly_capacity_units": 10,
        }
    )
    prairie = create_active_licensee(business_name="Prairie Furniture Co")
    o_hd = create_hd_order(ctx, quantity=1)
    submit_order(o_hd)
    o_la = create_licensee_order(ctx["licensee"], ctx["cycle"], ctx["line"], quantity=6)
    submit_order(o_la)
    o_lb = create_licensee_order(prairie, ctx["cycle"], ctx["line"], quantity=5)
    o_lb = submit_order(o_lb)
    assert o_lb["allocation_state"] == "WAITLISTED"  # 1 + 6 + 5 > 10
    run_cycle(ctx["cycle"]["id"])
    # licensee_cap == 10 - floor(10*0.25) == 8: HD2 (1) and LA (6) allocate;
    # LB (5) does not fit the remaining 1.
    assert get_order(o_hd["id"])["allocation_state"] == "ALLOCATED"
    assert get_order(o_la["id"])["allocation_state"] == "ALLOCATED"
    assert get_order(o_lb["id"])["allocation_state"] == "WAITLISTED"
    pick_order(o_hd["id"])
    appt = book_appointment(
        get_order(o_hd["id"]),
        ctx,
        "2026-09-10T09:00:00Z",
        "2026-09-10T11:00:00Z",
        crew_units=1,
    )
    confirm_appointment(appt["id"])
    assert get_order(o_hd["id"])["fulfillment_state"] == "SHIPPED"
    ctx.update(prairie=prairie, o_hd=o_hd, o_la=o_la, o_lb=o_lb, appt=appt)
    return ctx


class TestLicenseeTerminationCascade:
    """Difficulty instance:
    licensee_termination_cascades_territory_appointment_order_capacity."""

    def test_termination_revokes_territory_and_cancels_appointment(self, api, platform_admin_headers):
        """PRD §3.2: "Terminating a licensee — from `ACTIVE`, `PROBATION`, or
        `SUSPENDED` alike — fires the program's largest cascade, and its snapshot
        semantics are deliberate. First, every territory assigned to the licensee
        executes the revocation transition above."
        PRD §3.2: "every delivery appointment of the former assignee whose `region_code`
        equals the territory's `region_code` and whose status is `REQUESTED` or
        `CONFIRMED` flips to `CANCELLED`, and cancelling a `CONFIRMED` appointment
        reverts its order from `SHIPPED` back to `PICKED`"

        Design: Difficulty/transitive_cascade/licensee_termination_cascades_territory_appointment_order_capacity
        """
        ctx = _setup_termination_scenario()
        transition_licensee(ctx["licensee"]["id"], "TERMINATED")

        territory = get_territory(ctx["territory"]["id"])
        assert territory["status"] == "OPEN"
        assert territory["assigned_licensee_id"] is None
        assert territory["revoked_at"] is not None

        appt = validate_success(
            api.get_delivery_appointment(ctx["appt"]["id"], platform_admin_headers)
        )
        assert appt["status"] == "CANCELLED", (
            "territory revocation must cancel the CONFIRMED appointment in the region"
        )
        hd = get_order(ctx["o_hd"]["id"])
        assert hd["fulfillment_state"] == "PICKED", (
            "the cancelled CONFIRMED appointment reverts its order SHIPPED -> PICKED"
        )

    def test_shipped_order_survives_drop_set_and_waitlist_promotes(self, api, platform_admin_headers):
        """PRD §3.2: "every supply order of this licensee whose allocation state is
        `RESERVED`, `ALLOCATED`, or `WAITLISTED` and whose fulfillment state is
        `PENDING` or `PICKED` flips to `DROPPED`, with its fulfillment set to
        `CANCELLED` in the same mutation. Orders that are `SHIPPED` at terminate time
        are in transit and are not dropped — even when a subsequent appointment
        cancellation from the territory revocations reverts such an order to `PICKED`,
        it stays `ALLOCATED`/`PICKED`, awaiting redelivery."
        PRD §3.4: "or in `ALLOCATED` once the cycle is `ALLOCATED`, locking
        `final_total_cents` at promotion with the line's current lifecycle"

        Design: Difficulty/transitive_cascade/licensee_termination_cascades_territory_appointment_order_capacity
        """
        ctx = _setup_termination_scenario()
        transition_licensee(ctx["licensee"]["id"], "TERMINATED")

        # SHIPPED at terminate time: NOT dropped; stays ALLOCATED after the
        # appointment-cancellation revert to PICKED.
        hd = get_order(ctx["o_hd"]["id"])
        assert hd["allocation_state"] == "ALLOCATED"
        assert hd["fulfillment_state"] == "PICKED"

        # ALLOCATED + PENDING at terminate time: dropped.
        la = get_order(ctx["o_la"]["id"])
        assert la["allocation_state"] == "DROPPED"
        assert la["fulfillment_state"] == "CANCELLED"

        # The released 6 units promote Prairie's waitlisted order on the ALLOCATED
        # cycle, locking final_total_cents == 5 * 62930.
        lb = get_order(ctx["o_lb"]["id"])
        assert lb["allocation_state"] == "ALLOCATED"
        assert lb["final_total_cents"] == 314650

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["licensee_reserved_units"] == 6  # HD2 (1) + LB (5)
        assert cycle["available_units"] == 4
        assert_cycle_capacity_conserved(cycle)


class TestProductLineRetirementCascade:
    """Difficulty instance: product_line_retirement_cascades_order_drop_credit_release.
    NOTE on the asserted fulfillment state: PRD §3.1 states the retirement drop
    leaves fulfillment "deliberately left unchanged" (PENDING) — "retirement does
    not mark them CANCELLED" — so these tests assert PENDING, not CANCELLED."""

    def _setup(self):
        ctx = setup_open_cycle()
        account = create_retail_account(
            business_name="Metro Discount Furniture", credit_limit_cents=1_000_000
        )
        o_w = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=2)
        submit_order(o_w)  # unit 89900 (tier 0) -> credit_used 179800
        o_l = create_licensee_order(ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3)
        submit_order(o_l)
        ctx.update(account=account, o_w=o_w, o_l=o_l)
        return ctx

    def test_clearance_advance_fires_no_cascade(self, api, platform_admin_headers):
        """PRD §3.1: "Entering `CLEARANCE` needs no recomputation —
        `clearance_price_cents` already reflects the 75-percent keep — but from that
        moment on, orders created or submitted price off the clearance base."
        PRD §3.1: "Entering `RETIRED` fires a three-hop cascade."

        Design: Difficulty/transitive_cascade/product_line_retirement_cascades_order_drop_credit_release
        """
        ctx = self._setup()
        assert get_retail_account(ctx["account"]["id"])["credit_used_cents"] == 179800
        line = advance_product_line(ctx["line"]["id"])
        assert line["lifecycle"] == "CLEARANCE"
        # No cascade fires mid-lifecycle: exposure and reservations are unchanged.
        assert get_retail_account(ctx["account"]["id"])["credit_used_cents"] == 179800
        assert get_order(ctx["o_w"]["id"])["allocation_state"] == "RESERVED"
        assert get_order(ctx["o_l"]["id"])["allocation_state"] == "RESERVED"

    def test_retirement_drops_orders_and_releases_credit(self, api, platform_admin_headers):
        """PRD §3.1: "Hop 1: every supply order on this line whose allocation state is
        `RESERVED` or `WAITLISTED` flips to `DROPPED`, while its fulfillment state is
        deliberately left unchanged — such orders are still `PENDING` by construction,
        and retirement does not mark them `CANCELLED` (contrast the cancel path in
        §3.5, which does)."
        PRD §3.1: "Hop 2: each dropped order's allocation cycle recomputes
        `licensee_reserved_units`, `wholesale_reserved_units`, and `available_units`,
        releasing the dropped quantity, and each affected retail account recomputes
        `credit_used_cents`, since dropped orders leave the exposure set."

        Design: Difficulty/transitive_cascade/product_line_retirement_cascades_order_drop_credit_release
        """
        ctx = self._setup()
        advance_product_line(ctx["line"]["id"])  # ACTIVE -> CLEARANCE
        advance_product_line(ctx["line"]["id"])  # CLEARANCE -> RETIRED

        w = get_order(ctx["o_w"]["id"])
        l = get_order(ctx["o_l"]["id"])
        assert w["allocation_state"] == "DROPPED"
        assert l["allocation_state"] == "DROPPED"
        # PRD §3.1: retirement leaves fulfillment "deliberately unchanged" — PENDING,
        # NOT CANCELLED.
        assert w["fulfillment_state"] == "PENDING"
        assert l["fulfillment_state"] == "PENDING"

        # Dropped orders leave the exposure set and release capacity in full.
        assert get_retail_account(ctx["account"]["id"])["credit_used_cents"] == 0
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["licensee_reserved_units"] == 0
        assert cycle["wholesale_reserved_units"] == 0
        assert cycle["available_units"] == 100
        assert_cycle_capacity_conserved(cycle)

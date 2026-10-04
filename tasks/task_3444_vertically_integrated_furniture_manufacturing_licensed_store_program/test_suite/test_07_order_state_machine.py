"""Order dual-axis state machine: invalid and guarded transitions, waitlist
promotion across the parallel axes, and cross-entity creation gates
(PRD §2.8, §3.4, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    advance_product_line,
    cancel_order,
    create_active_licensee,
    create_factory,
    create_hd_order,
    create_licensee_order,
    get_cycle,
    get_order,
    make_licensee_manager_headers,
    pick_order,
    run_cycle,
    setup_catalog,
    setup_hd_context,
    setup_open_cycle,
    submit_order,
    transition_licensee,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInvalidOrderTransitions:
    def test_order_deliver_from_pending_returns_409(self, api, logistics_coordinator_headers):
        """PRD §3.5: "The fulfillment axis runs `PENDING → PICKED → SHIPPED →
        DELIVERED`, with `CANCELLED` as its second terminal state; orders are born
        `PENDING`."
        PRD §2.8: "Transition validity (`ERR_INVALID_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/order_deliver_from_pending_returns_409
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3
        )
        resp = api.transition_order(
            order["id"], {"action": "DELIVER"}, logistics_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
        fetched = get_order(order["id"])
        assert fetched["allocation_state"] == "UNALLOCATED"
        assert fetched["fulfillment_state"] == "PENDING"

    def test_order_double_submit_returns_409(self, api, production_planner_headers):
        """PRD §3.5: "When the cycle's `available_units` cover the order's `quantity`,
        the order becomes `RESERVED`" — submit is wired only from `UNALLOCATED`.
        PRD §2.8: "Transition validity (`ERR_INVALID_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/order_double_submit_returns_409
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=5
        )
        submit_order(order)
        resp = api.transition_order(
            order["id"],
            {"action": "SUBMIT"},
            make_licensee_manager_headers(ctx["licensee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
        # No double reservation.
        assert get_cycle(ctx["cycle"]["id"])["licensee_reserved_units"] == 5

    def test_suspended_licensee_submit_rejected(self, api, platform_admin_headers):
        """PRD §3.5: "the buyer orderable — a licensee in `ACTIVE` or `PROBATION`
        status, otherwise `ERR_LICENSEE_NOT_ORDERABLE`"

        Design: Corner/errors/suspended_licensee_submit_rejected
        """
        ctx = setup_open_cycle()
        transition_licensee(ctx["licensee"]["id"], "SUSPENDED")
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=1
        )
        resp = api.transition_order(
            order["id"],
            {"action": "SUBMIT"},
            make_licensee_manager_headers(ctx["licensee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSEE_NOT_ORDERABLE.value)
        assert get_order(order["id"])["allocation_state"] == "UNALLOCATED"


class TestHomeDeliveryShipGuard:
    def test_home_delivery_order_direct_ship_returns_409(self, api, logistics_coordinator_headers):
        """PRD §3.5: "Home-delivery orders may only reach `SHIPPED` and `DELIVERED`
        through the appointment flow of §3.6: a direct `SHIP` or `DELIVER` on a
        `HOME_DELIVERY` order is rejected with `ERR_USE_APPOINTMENT_FLOW`."

        Design: Corner/state_machines/home_delivery_order_direct_ship_returns_409
        """
        ctx = setup_hd_context()
        order = create_hd_order(ctx, quantity=1)
        submit_order(order)
        run_cycle(ctx["cycle"]["id"])
        pick_order(order["id"])
        resp = api.transition_order(
            order["id"], {"action": "SHIP"}, logistics_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_USE_APPOINTMENT_FLOW.value)
        assert get_order(order["id"])["fulfillment_state"] == "PICKED"


class TestWaitlistPromotionParallelAxes:
    """Difficulty instance: supply_order_waitlist_promotion_leaves_fulfillment_untouched.
    Factory capacity 10: Summit's qty-10 order fills the cycle; Prairie's qty-5
    order waitlists at submit; cancelling Summit's order promotes Prairie's."""

    def _setup(self):
        factory = create_factory(
            code="FAC-S1",
            region="DOMESTIC",
            component_lines=["FRAMES"],
            weekly_capacity_units=10,
        )
        ctx = setup_catalog()
        ctx["factory"] = factory
        from test_helpers import create_cycle, WEEK_1_START

        ctx["cycle"] = create_cycle(factory["id"], week_start=WEEK_1_START)
        prairie = create_active_licensee(business_name="Prairie Furniture Co")
        o_a = create_licensee_order(ctx["licensee"], ctx["cycle"], ctx["line"], quantity=10)
        o_a = submit_order(o_a)
        o_b = create_licensee_order(prairie, ctx["cycle"], ctx["line"], quantity=5)
        o_b = submit_order(o_b)
        return ctx, prairie, o_a, o_b

    def test_waitlisted_at_submit_then_promoted_on_capacity_release(self, api, platform_admin_headers):
        """PRD §3.5: "When capacity falls short, the order becomes `WAITLISTED` instead:
        `submitted_at` is stamped, but a waitlisted order holds no capacity and counts
        toward no credit."
        PRD §3.4: "Capacity release triggers the promotion sweep. Any event that
        releases capacity on an `OPEN` or `ALLOCATED` cycle — an order cancellation or
        a cascade-driven drop — recomputes `available_units` and then scans the cycle's
        `WAITLISTED` orders once, in the same rank order, promoting each order whose
        `quantity` fits within the remaining availability"
        PRD §3.4: "Promotion lands the order in `RESERVED` while the cycle is still
        `OPEN`"

        Design: Difficulty/non_linear_state_machine/supply_order_waitlist_promotion_leaves_fulfillment_untouched
        """
        _ctx, _prairie, o_a, o_b = self._setup()
        assert o_a["allocation_state"] == "RESERVED"
        assert o_b["allocation_state"] == "WAITLISTED"  # 10 + 5 > 10
        assert o_b["fulfillment_state"] == "PENDING"
        cancel_order(o_a, reason="buyer remorse")
        promoted = get_order(o_b["id"])
        assert promoted["allocation_state"] == "RESERVED", (
            f"released 10 units must promote the waitlisted order, got {promoted['allocation_state']}"
        )

    def test_allocation_axis_moves_while_fulfillment_axis_holds(self, api, platform_admin_headers):
        """PRD §3.5: "Every supply order carries two parallel state axes that evolve
        independently except where a transition's preconditions name the other axis."
        PRD §3.5: "Cancellation flips the order to `DROPPED` and its fulfillment to
        `CANCELLED` in the same mutation"

        Design: Difficulty/non_linear_state_machine/supply_order_waitlist_promotion_leaves_fulfillment_untouched
        """
        _ctx, _prairie, o_a, o_b = self._setup()
        cancel_order(o_a, reason="buyer remorse")
        promoted = get_order(o_b["id"])
        # The allocation axis moved WAITLISTED -> RESERVED; the fulfillment axis
        # never left PENDING.
        assert promoted["allocation_state"] == "RESERVED"
        assert promoted["fulfillment_state"] == "PENDING", (
            "fulfillment axis must be untouched by allocation-axis promotion"
        )
        cancelled = get_order(o_a["id"])
        assert cancelled["allocation_state"] == "DROPPED"
        assert cancelled["fulfillment_state"] == "CANCELLED"


class TestOrderCreateBlockedByConceptLine:
    """Difficulty instance: order_create_blocked_by_concept_line_state."""

    def test_concept_line_rejects_order_create(self, api, platform_admin_headers):
        """PRD §3.5: "a `product_line_id` whose line must be orderable — lifecycle
        `ACTIVE` or `CLEARANCE`, at create and at submit — otherwise
        `ERR_LINE_NOT_ORDERABLE`"

        Design: Difficulty/cross_entity_state_dependency/order_create_blocked_by_concept_line_state
        """
        ctx = setup_open_cycle(line_state="CONCEPT")
        assert ctx["line"]["lifecycle"] == "CONCEPT"
        payload = {
            "buyer_type": "LICENSEE",
            "licensee_id": ctx["licensee"]["id"],
            "retail_account_id": None,
            "allocation_cycle_id": ctx["cycle"]["id"],
            "product_line_id": ctx["line"]["id"],
            "quantity": 1,
            "delivery_mode": "FREIGHT_TO_STORE",
        }
        resp = api.create_order(
            payload, make_licensee_manager_headers(ctx["licensee"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_ORDERABLE.value)
        orders, meta = validate_paginated(
            api.list_orders(
                platform_admin_headers,
                params={"licensee_id": ctx["licensee"]["id"]},
            )
        )
        assert orders == [] and meta["total_count"] == 0, (
            "no order may be persisted against a CONCEPT line"
        )

    def test_same_create_succeeds_once_line_is_active(self, api, platform_admin_headers):
        """PRD §3.5: "a `product_line_id` whose line must be orderable — lifecycle
        `ACTIVE` or `CLEARANCE`, at create and at submit — otherwise
        `ERR_LINE_NOT_ORDERABLE`"
        PRD §3.1: "Lifecycle advancement is one step per call by a `PlatformAdmin`:
        `CONCEPT → ACTIVE`, `ACTIVE → CLEARANCE`, and `CLEARANCE → RETIRED`"

        Design: Difficulty/cross_entity_state_dependency/order_create_blocked_by_concept_line_state
        """
        ctx = setup_open_cycle(line_state="CONCEPT")
        line = advance_product_line(ctx["line"]["id"])
        assert line["lifecycle"] == "ACTIVE"
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], line, quantity=1
        )
        assert order["allocation_state"] == "UNALLOCATED"
        assert order["fulfillment_state"] == "PENDING"


class TestAppointmentBlockedByOrderNotPicked:
    """Difficulty instance: appointment_create_blocked_by_order_not_picked."""

    def _setup_allocated_not_picked(self):
        ctx = setup_hd_context()
        order = create_hd_order(ctx, quantity=1)
        submit_order(order)
        run_cycle(ctx["cycle"]["id"])
        return ctx, get_order(order["id"])

    def test_appointment_create_requires_picked_order(self, api, platform_admin_headers):
        """PRD §3.6: "The order — named by `supply_order_id` — must be a
        `HOME_DELIVERY` licensee order currently in fulfillment state `PICKED`: booking
        against an order in any other fulfillment state is `ERR_ORDER_NOT_PICKED`"

        Design: Difficulty/cross_entity_state_dependency/appointment_create_blocked_by_order_not_picked
        """
        ctx, order = self._setup_allocated_not_picked()
        assert order["allocation_state"] == "ALLOCATED"
        assert order["fulfillment_state"] == "PENDING"  # run happened, pick never did
        from test_helpers import book_appointment_response

        resp = book_appointment_response(
            order, ctx, "2026-09-10T09:00:00Z", "2026-09-10T12:00:00Z", crew_units=1
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PICKED.value)

    def test_no_appointment_persisted_and_pick_unblocks_booking(self, api, platform_admin_headers):
        """PRD §3.6: "booking against an order in any other fulfillment state is
        `ERR_ORDER_NOT_PICKED`"
        PRD §3.5: "Picking (action `PICK`, `PENDING → PICKED`) requires the allocation
        state to be `ALLOCATED` — capacity must be confirmed before picking"

        Design: Difficulty/cross_entity_state_dependency/appointment_create_blocked_by_order_not_picked
        """
        ctx, order = self._setup_allocated_not_picked()
        from test_helpers import book_appointment, book_appointment_response

        resp = book_appointment_response(
            order, ctx, "2026-09-10T09:00:00Z", "2026-09-10T12:00:00Z", crew_units=1
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PICKED.value)
        appointments, meta = validate_paginated(
            api.list_delivery_appointments(
                platform_admin_headers, params={"supply_order_id": order["id"]}
            )
        )
        assert appointments == [] and meta["total_count"] == 0
        # Once picked, the same booking succeeds — the fulfillment state was the gate.
        pick_order(order["id"])
        booked = book_appointment(
            get_order(order["id"]),
            ctx,
            "2026-09-10T09:00:00Z",
            "2026-09-10T12:00:00Z",
            crew_units=1,
        )
        assert booked["status"] == "REQUESTED"

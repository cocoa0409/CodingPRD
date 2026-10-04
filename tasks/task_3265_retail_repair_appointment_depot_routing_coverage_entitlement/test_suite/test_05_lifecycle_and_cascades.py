"""Repair lifecycle: completion cascades, depot routing, escalation, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_part_inventory_invariants,
    book_appointment,
    create_and_verify_security,
    create_coverage_plan,
    create_entitlement,
    create_inventory,
    create_location,
    create_part,
    create_quality_follow_up_payload,
    create_repair_order_payload,
    get_coverage_plan,
    get_device,
    get_repair_order,
    make_customer_headers,
    make_customer_service_headers,
    make_depot_agent_headers,
    make_technician_headers,
    open_repair_order,
    resolve_entitlement,
    set_clock,
    setup_completed_order,
    setup_completed_order_with_follow_up,
    setup_customer_and_device,
    setup_mail_in_order_in_quality_check,
    setup_network,
    setup_ready_for_pickup_order,
    setup_repair_order,
    setup_customer_device_and_network,
    validate_error,
    validate_paginated,
    validate_success,
    walk_to_ready_for_pickup,
)


class TestCompletionCascade:
    def test_repair_completion_cascades_to_part_consumption_and_incident_count(self, api):
        """PRD §3.7: "Completion fires the full cascade of §2.9: every allocation
        flips from `RESERVED` to `CONSUMED`; each inventory row's
        `on_hand_quantity` and `reserved_quantity` drop by the consumed quantity;
        and if the entitlement stands at `ENTITLED`, the damage is accidental,
        and `incident_counted` is still false, the plan's
        `accidental_damage_incidents_used` increments by one and
        `incident_counted` becomes true — exactly one incident per repair, never
        double-counted."

        Design: Difficulty/transitive_cascade/repair_completion_cascades_to_part_consumption_and_incident_count
        """
        set_clock()
        ctx = setup_ready_for_pickup_order(
            issue_category="SCREEN_DAMAGE", is_accidental_damage=True,
            with_part=True, on_hand_quantity=5,
            with_plan=True,
            plan_overrides={"plan_type": "APPLECARE_PLUS",
                            "accidental_damage_incident_limit": 2,
                            "service_fee_cents": 2900},
        )
        resp = api.complete_pickup(
            ctx["repair_order"]["id"], make_customer_headers(ctx["customer"]["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "COMPLETED"

        allocs, _ = validate_paginated(api.list_part_allocations(
            make_customer_service_headers(),
            params={"repair_order_id": ctx["repair_order"]["id"]}))
        assert len(allocs) >= 1
        for alloc in allocs:
            assert alloc["allocation_status"] == "CONSUMED"

        inv = validate_success(api.get_part_inventory(
            ctx["inventory"]["id"], make_technician_headers(ctx["technician"]["id"])), 200)
        assert inv["on_hand_quantity"] == 4
        assert inv["reserved_quantity"] == 0
        assert_part_inventory_invariants(inv)

        plan = get_coverage_plan(ctx["plan"]["id"])
        assert plan["accidental_damage_incidents_used"] == 1

        ent = validate_success(api.get_coverage_entitlement(
            ctx["entitlement"]["id"], make_customer_service_headers()), 200)
        assert ent["incident_counted"] is True

    def test_repair_order_complete_pickup_consumes_parts_and_increments_incidents(self, api):
        """PRD §2.9: "Completing a repair flips each of its part allocations from
        `RESERVED` to `CONSUMED`, decrements inventory counters, and — when the
        entitlement resolved to `ENTITLED` on an accidental-damage claim whose
        incident has not yet been counted — increments the plan's
        `accidental_damage_incidents_used` and marks the entitlement's
        `incident_counted` flag."

        Design: Corner/endpoints/repair_order_complete_pickup_consumes_parts_and_increments_incidents
        """
        set_clock()
        ctx = setup_ready_for_pickup_order(
            issue_category="SCREEN_DAMAGE", is_accidental_damage=True,
            with_part=True, on_hand_quantity=3,
            with_plan=True,
            plan_overrides={"plan_type": "APPLECARE_PLUS",
                            "accidental_damage_incident_limit": 2,
                            "service_fee_cents": 2900},
        )
        resp = api.complete_pickup(
            ctx["repair_order"]["id"], make_customer_headers(ctx["customer"]["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "COMPLETED"

        inv = validate_success(api.get_part_inventory(
            ctx["inventory"]["id"], make_technician_headers(ctx["technician"]["id"])), 200)
        assert inv["on_hand_quantity"] == 2
        assert inv["reserved_quantity"] == 0

        plan = get_coverage_plan(ctx["plan"]["id"])
        assert plan["accidental_damage_incidents_used"] == 1

    def test_coverage_incident_count_conservation_on_waive(self, api):
        """PRD §3.7: "if the entitlement stands at `ENTITLED`, the damage is
        accidental, and `incident_counted` is still false, the plan's
        `accidental_damage_incidents_used` increments by one and
        `incident_counted` becomes true — exactly one incident per repair, never
        double-counted."
        PRD §3.6: "Separately, a `CustomerService` agent — and only
        `CustomerService`; any other role receives `ERR_UNAUTHORIZED` — may waive
        the entitlement, moving it to `WAIVED` and setting both the
        entitlement's and the repair order's `quoted_price_cents` to zero as a
        courtesy."

        Design: Difficulty/compensating_invariant/coverage_incident_count_conservation_on_waive
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True, seed_parts=True)
        )
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        resp = api.waive_entitlement(
            entitlement["id"], make_customer_service_headers())
        waived = validate_success(resp, expected_status=200)
        assert waived["entitlement_status"] == "WAIVED"

        walk_to_ready_for_pickup(repair_order, device, technician)
        resp = api.complete_pickup(
            repair_order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "COMPLETED"

        # A WAIVED entitlement is not ENTITLED, so completion consumes nothing.
        plan_now = get_coverage_plan(plan["id"])
        assert plan_now["accidental_damage_incidents_used"] == 0


class TestDepotRouting:
    def test_depot_routing_entitled_vs_not_entitled_shipping(self, api):
        """PRD §3.6: "That amount is added to the repair order's
        `quoted_price_cents` only when the entitlement stands at `NOT_ENTITLED`
        or `PARTIALLY_ENTITLED`; for an `ENTITLED` claim the plan absorbs
        shipping and the customer price is untouched."

        Design: Difficulty/dual_variant_calc/depot_routing_entitled_vs_not_entitled_shipping
        """
        set_clock()
        ctx = setup_mail_in_order_in_quality_check()
        ro = ctx["repair_order"]
        price_before = ro["quoted_price_cents"]

        entitlement = create_entitlement(ro, ctx["technician"])
        resp = api.resolve_entitlement(
            entitlement["id"], {"expected_coverage_plan_version": 1},
            make_technician_headers(ctx["technician"]["id"]),
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["entitlement_status"] == "NOT_ENTITLED"
        price_after_resolve = get_repair_order(ro["id"])["quoted_price_cents"]

        resp = api.ship_to_depot(ro["id"],
                                 make_technician_headers(ctx["technician"]["id"]))
        shipped = validate_success(resp, expected_status=200)
        assert shipped["repair_status"] == "SHIPPED_TO_DEPOT"

        price_after_ship = get_repair_order(ro["id"])["quoted_price_cents"]
        increase = price_after_ship - price_after_resolve
        # Shipping is added for a NOT_ENTITLED claim; the PRD fixes the lane
        # cost at 1500 * zone multiplier, so the increase must be a positive
        # amount consistent with the 1500-cent base.
        assert increase > 0, (
            "shipping must be added to the customer price when the entitlement "
            "stands at NOT_ENTITLED"
        )
        assert increase >= 1500
        assert (increase * 2) % 1500 * 2 == 0  # increase is a 1.0/1.5/2.0 multiple of 1500

    def test_ship_to_depot_cascades_to_shipment_and_location_update(self, api):
        """PRD §3.7: "A `MAIL_IN_DEPOT` order instead ships to the depot: the
        order moves to `SHIPPED_TO_DEPOT` and a `RepairShipment` is created with
        `shipment_type` of `STORE_TO_DEPOT` in `LABEL_CREATED`, carrying the
        `repair_order_id`, `from_location_id`, `to_location_id`, and a
        system-issued `tracking_number`."

        Design: Difficulty/transitive_cascade/ship_to_depot_cascades_to_shipment_and_location_update
        """
        set_clock()
        ctx = setup_mail_in_order_in_quality_check()
        ro = ctx["repair_order"]

        resp = api.ship_to_depot(ro["id"],
                                 make_technician_headers(ctx["technician"]["id"]))
        shipped = validate_success(resp, expected_status=200)
        assert shipped["repair_status"] == "SHIPPED_TO_DEPOT"

        shipments, _ = validate_paginated(api.list_repair_shipments(
            make_customer_service_headers(), params={"repair_order_id": ro["id"]}))
        assert len(shipments) == 1
        shipment = shipments[0]
        assert shipment["shipment_type"] == "STORE_TO_DEPOT"
        assert shipment["shipment_status"] == "LABEL_CREATED"
        assert shipment["from_location_id"] == ctx["store"]["id"]
        assert shipment["to_location_id"] == ctx["depot"]["id"]
        assert isinstance(shipment["tracking_number"], str)
        assert len(shipment["tracking_number"]) > 0

        # Depot receives the device; the order's current location is rewritten.
        resp = api.receive_at_depot(ro["id"], make_depot_agent_headers())
        in_transit = validate_success(resp, expected_status=200)
        assert in_transit["repair_status"] == "IN_TRANSIT_BACK"
        assert in_transit["current_location_id"] == ctx["depot"]["id"]

    def test_ship_to_depot_terminal_guard_blocks_pickup_before_return(self, api):
        """PRD §3.7: "A `MAIL_IN_DEPOT` order instead ships to the depot: the
        order moves to `SHIPPED_TO_DEPOT` and a `RepairShipment` is created with
        `shipment_type` of `STORE_TO_DEPOT` in `LABEL_CREATED`, carrying the
        `repair_order_id`, `from_location_id`, `to_location_id`, and a
        system-issued `tracking_number`."
        PRD §2.6: "fourth state validity for the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/transitive_cascade/ship_to_depot_cascades_to_shipment_and_location_update
        """
        set_clock()
        ctx = setup_mail_in_order_in_quality_check()
        ro = ctx["repair_order"]

        resp = api.ship_to_depot(ro["id"],
                                 make_technician_headers(ctx["technician"]["id"]))
        shipped = validate_success(resp, expected_status=200)
        assert shipped["repair_status"] == "SHIPPED_TO_DEPOT"

        # Pickup is only reachable from READY_FOR_PICKUP; while shipped to the
        # depot the transition is state-invalid.
        resp = api.complete_pickup(
            ro["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)
        assert get_repair_order(ro["id"])["repair_status"] == "SHIPPED_TO_DEPOT"

    def test_entitled_mail_in_order_ships_without_price_increase(self, api):
        """PRD §3.6: "That amount is added to the repair order's
        `quoted_price_cents` only when the entitlement stands at `NOT_ENTITLED`
        or `PARTIALLY_ENTITLED`; for an `ENTITLED` claim the plan absorbs
        shipping and the customer price is untouched."

        Design: Difficulty/dual_variant_calc/depot_routing_entitled_vs_not_entitled_shipping
        """
        set_clock()
        ctx = setup_mail_in_order_in_quality_check(is_accidental_damage=True)
        ro = ctx["repair_order"]

        plan = create_coverage_plan(
            ctx["device"], plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(ro, ctx["technician"], plan["id"])
        resolved = resolve_entitlement(entitlement, plan, ctx["technician"])
        assert resolved["entitlement_status"] == "ENTITLED"
        price_after_resolve = get_repair_order(ro["id"])["quoted_price_cents"]
        assert price_after_resolve == 2900

        validate_success(api.ship_to_depot(
            ro["id"], make_technician_headers(ctx["technician"]["id"])), 200)
        # For an ENTITLED claim the plan absorbs shipping.
        assert get_repair_order(ro["id"])["quoted_price_cents"] == 2900


class TestRepeatEscalation:
    def test_repair_order_cyclic_repeat_escalation(self, api):
        """PRD §3.8: "A granted escalation moves the order to
        `ESCALATED_REPEAT`, increments its `repeat_repair_count`, and flips any
        open follow-up to `ESCALATED`. From `ESCALATED_REPEAT`, a technician
        re-triages the order, returning it to `TRIAGED` so it re-enters the
        normal allocation-and-repair pipeline."

        Design: Difficulty/non_linear_state_machine/repair_order_cyclic_repeat_escalation
        """
        set_clock()
        ctx = setup_completed_order_with_follow_up(issue_category="BATTERY")
        ro_id = ctx["repair_order"]["id"]

        resp = api.escalate_repeat(ro_id, make_customer_service_headers())
        escalated = validate_success(resp, expected_status=200)
        assert escalated["repair_status"] == "ESCALATED_REPEAT"
        assert escalated["repeat_repair_count"] == 1

        follow_up = validate_success(api.get_quality_follow_up(
            ctx["follow_up"]["id"], make_customer_service_headers()), 200)
        assert follow_up["follow_up_status"] == "ESCALATED"

        resp = api.re_triage(ro_id, make_technician_headers(ctx["technician"]["id"]))
        triaged = validate_success(resp, expected_status=200)
        assert triaged["repair_status"] == "TRIAGED"
        assert triaged["repeat_repair_count"] == 1

    def test_repeat_cycle_can_complete_a_second_time(self, api):
        """PRD §3.8: "From `ESCALATED_REPEAT`, a technician re-triages the order,
        returning it to `TRIAGED` so it re-enters the normal
        allocation-and-repair pipeline."
        PRD §3.8: "A granted escalation moves the order to `ESCALATED_REPEAT`,
        increments its `repeat_repair_count`, and flips any open follow-up to
        `ESCALATED`."

        Design: Difficulty/non_linear_state_machine/repair_order_cyclic_repeat_escalation
        """
        set_clock()
        ctx = setup_completed_order_with_follow_up(issue_category="BATTERY")
        ro_id = ctx["repair_order"]["id"]

        validate_success(api.escalate_repeat(
            ro_id, make_customer_service_headers()), 200)
        validate_success(api.re_triage(
            ro_id, make_technician_headers(ctx["technician"]["id"])), 200)

        # Re-enter the pipeline: allocate, repair, quality-check, pick up.
        walk_to_ready_for_pickup(ctx["repair_order"], ctx["device"],
                                 ctx["technician"])
        validate_success(api.complete_pickup(
            ro_id, make_customer_headers(ctx["customer"]["id"])), 200)
        assert get_repair_order(ro_id)["repair_status"] == "COMPLETED"

        # A second granted escalation increments the repeat counter again.
        payload = create_quality_follow_up_payload(ro_id, ctx["customer"]["id"])
        validate_success(api.create_quality_follow_up(
            payload, make_customer_service_headers()), 201)
        resp = api.escalate_repeat(ro_id, make_customer_service_headers())
        escalated = validate_success(resp, expected_status=200)
        assert escalated["repair_status"] == "ESCALATED_REPEAT"
        assert escalated["repeat_repair_count"] == 2

    def test_repair_order_escalate_repeat_from_completed_within_90_days(self, api):
        """PRD §3.8: "A completed repair can also be escalated directly as a
        repeat by `CustomerService`, provided the request arrives within 90 days
        of completion — completion time being the order's `updated_at` at the
        moment `repair_status` became `COMPLETED`, with the elapsed time computed
        in whole days — and provided no follow-up for the same order currently
        stands at `RESOLVED_SATISFIED`."

        Design: Corner/state_machines/repair_order_escalate_repeat_from_completed_within_90_days
        """
        set_clock()
        ctx = setup_completed_order_with_follow_up(issue_category="SOFTWARE")
        ro_id = ctx["repair_order"]["id"]
        resp = api.escalate_repeat(ro_id, make_customer_service_headers())
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "ESCALATED_REPEAT"
        assert data["repeat_repair_count"] == 1

    def test_escalate_repeat_depends_on_quality_follow_up_state(self, api):
        """PRD §3.8: "A completed repair can also be escalated directly as a
        repeat by `CustomerService`, provided the request arrives within 90 days
        of completion — completion time being the order's `updated_at` at the
        moment `repair_status` became `COMPLETED`, with the elapsed time computed
        in whole days — and provided no follow-up for the same order currently
        stands at `RESOLVED_SATISFIED`."

        Design: Difficulty/cross_entity_state_dependency/escalate_repeat_depends_on_quality_follow_up_state
        """
        set_clock()
        ctx = setup_completed_order_with_follow_up(issue_category="SOFTWARE")
        ro_id = ctx["repair_order"]["id"]
        validate_success(api.resolve_follow_up_satisfied(
            ctx["follow_up"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)

        resp = api.escalate_repeat(ro_id, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        assert get_repair_order(ro_id)["repair_status"] == "COMPLETED"


class TestRepeatWindow:
    def test_escalate_repeat_after_90_days_returns_repeat_window_expired(self, api):
        """PRD §3.8: "Outside the 90-day window the escalation is rejected with
        `ERR_REPEAT_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/escalate_repeat_after_90_days_returns_repeat_window_expired
        """
        set_clock()
        ctx = setup_completed_order_with_follow_up(issue_category="SOFTWARE")
        ro_id = ctx["repair_order"]["id"]
        # Completion happened at the logical start; jump 95 days ahead.
        set_clock("2026-12-05T00:00:00Z")
        resp = api.escalate_repeat(ro_id, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_REPEAT_WINDOW_EXPIRED.value,
                       expected_status=422)


class TestClockDrivenPlanTransitions:
    def test_coverage_plan_expires_on_clock_advance(self, api):
        """PRD §3.1: "Three events end a plan: the logical clock advancing past
        `expires_on` moves it to `EXPIRED`; an entitlement resolution that finds
        `accidental_damage_incidents_used` already at or beyond
        `accidental_damage_incident_limit` moves it to `EXHAUSTED`; and an
        explicit cancellation by the customer or `CustomerService` moves an
        `ACTIVE` plan to `CANCELLED`."

        Design: Corner/state_machines/coverage_plan_expires_on_clock_advance
        """
        set_clock()
        customer, device = setup_customer_and_device()
        plan = create_coverage_plan(
            device, plan_type="LIMITED_WARRANTY",
            starts_on="2025-01-01T00:00:00Z", expires_on="2026-09-02T00:00:00Z",
            accidental_damage_incident_limit=0, service_fee_cents=0,
        )
        assert plan["coverage_status"] == "ACTIVE"

        set_clock("2026-09-03T00:00:00Z")
        resp = api.get_coverage_plan(
            plan["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["coverage_status"] == "EXPIRED"


class TestOptimisticConcurrency:
    def test_optimistic_concurrency_repair_order_create(self, api):
        """PRD §2.5: "Creating a repair order requires `expected_device_version`,
        carrying the client's last observed `version` of the target `Device`. If
        the device's current `version` differs — because another writer has since
        created a repair order against it or otherwise mutated device state — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
        client from acting on a device state it has not observed."
        PRD §2.9: "Booking an appointment and creating a repair order each
        increment the device's `version`, which is precisely what the
        optimistic-concurrency checks above observe."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_repair_order_create
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order()
        )
        fresh_device = get_device(device["id"])
        stale_version = fresh_device["version"] - 1
        payload = create_repair_order_payload(
            appointment["id"], device["id"], customer["id"], location["id"],
            stale_version,
        )
        resp = api.create_repair_order(
            payload, make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    def test_err_stale_version_on_repair_order_create(self, api):
        """PRD §2.5: "Creating a repair order requires `expected_device_version`,
        carrying the client's last observed `version` of the target `Device`. If
        the device's current `version` differs — because another writer has since
        created a repair order against it or otherwise mutated device state — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
        client from acting on a device state it has not observed."

        Design: Corner/errors/err_stale_version_on_repair_order_create
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        # Book an appointment: this bumps the device version, so the version the
        # client captured before booking is now stale.
        stale_version = device["version"]
        appt = book_appointment(customer, device, location, technician)
        payload = create_repair_order_payload(
            appt["id"], device["id"], customer["id"], location["id"],
            stale_version,
        )
        resp = api.create_repair_order(
            payload, make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

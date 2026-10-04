"""Bench work: security gate, parts allocation, inventory conservation."""
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
    create_security_verification,
    create_technician,
    get_coverage_plan,
    get_repair_order,
    make_customer_headers,
    make_customer_service_headers,
    make_technician_headers,
    open_repair_order,
    resolve_entitlement,
    set_clock,
    setup_repair_order,
    validate_error,
    validate_paginated,
    validate_success,
    walk_to_in_progress,
    walk_to_parts_allocated,
    walk_to_ready_for_pickup,
)


class TestSecurityGate:
    def test_start_repair_depends_on_security_verification_and_device_state(self, api):
        """PRD §3.5: "Either the device's `activation_lock_enabled` is false, or
        an `ACTIVATION_LOCK_REMOVAL` verification for this repair order stands at
        `VERIFIED`; either the device's `proof_of_purchase_on_file` is true, or
        an `OWNERSHIP_PROOF` verification stands at `VERIFIED`. A breach of
        either condition is rejected with `ERR_SECURITY_VERIFICATION_REQUIRED`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/start_repair_depends_on_security_verification_and_device_state
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"activation_lock_enabled": True,
                                  "proof_of_purchase_on_file": False},
            )
        )
        validate_success(api.allocate_parts(
            repair_order["id"], make_technician_headers(technician["id"])), 200)

        # Gate fully closed: neither device flag satisfied, no verifications.
        resp = api.start_repair(repair_order["id"],
                                make_technician_headers(technician["id"]))
        validate_error(
            resp, ApiErrorId.ERR_SECURITY_VERIFICATION_REQUIRED.value,
            expected_status=422)

        # Satisfy the gate via verifications, then start-repair succeeds.
        create_and_verify_security(
            repair_order, technician, "ACTIVATION_LOCK_REMOVAL")
        create_and_verify_security(repair_order, technician, "OWNERSHIP_PROOF")
        resp = api.start_repair(repair_order["id"],
                                make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "IN_PROGRESS"

    def test_device_flags_alone_satisfy_the_gate(self, api):
        """PRD §3.5: "Either the device's `activation_lock_enabled` is false, or
        an `ACTIVATION_LOCK_REMOVAL` verification for this repair order stands at
        `VERIFIED`; either the device's `proof_of_purchase_on_file` is true, or
        an `OWNERSHIP_PROOF` verification stands at `VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/start_repair_depends_on_security_verification_and_device_state
        """
        set_clock()
        # activation_lock_enabled False + proof_of_purchase_on_file True: the
        # gate is satisfied by the device flags alone, no verification needed.
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"activation_lock_enabled": False,
                                  "proof_of_purchase_on_file": True},
            )
        )
        walk_to_parts_allocated(repair_order, device, technician)
        resp = api.start_repair(repair_order["id"],
                                make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "IN_PROGRESS"


class TestSecurityVerificationLifecycle:
    def test_security_verification_expires_after_24_hours(self, api):
        """PRD §3.5: "Verification is only accepted while pending and within 24
        hours of the record's `created_at`; past that deadline the record is no
        longer verifiable, and a `PENDING` record whose 24-hour window the clock
        has passed flips to `EXPIRED`."

        Design: Corner/state_machines/security_verification_expires_after_24_hours
        """
        set_clock("2026-09-01T10:00:00Z")
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"activation_lock_enabled": True,
                                  "proof_of_purchase_on_file": False},
                issue_category="HARDWARE_OTHER",
            )
        )
        verification = create_security_verification(repair_order, technician)
        assert verification["verification_status"] == "PENDING"

        # Advance past created_at + 24 hours.
        set_clock("2026-09-02T11:00:00Z")
        resp = api.get_security_verification(
            verification["id"], make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "EXPIRED"


class TestAllocationAcrossLocations:
    def test_part_inventory_allocation_across_locations(self, api):
        """PRD §3.4: "For each required part, a per-part score is the ratio of
        `available_quantity` to the required quantity, capped at one; ..."
        PRD §3.7: "Allocation is skipped for `WHOLE_UNIT_REPLACEMENT` orders and
        requires, for every required component, `available_quantity` greater than
        zero at the `current_location_id`; otherwise the request fails with
        `ERR_INSUFFICIENT_PARTS` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/part_inventory_allocation_across_locations
        """
        set_clock()
        customer, device, location_a, technician_a, appointment, ro_a = (
            setup_repair_order(issue_category="BATTERY")
        )
        # Seed stock at the order's location AFTER creation so triage already
        # scored it MAIL_IN_DEPOT; allocation then exercises availability.
        part = create_part(model_code="IPHONE_14", part_category="BATTERY")
        inv_a = create_inventory(location_a, part, on_hand_quantity=1)

        # A second location with ample stock of the same part — this must not
        # make the order at location A allocatable.
        location_b = create_location()
        inv_b = create_inventory(location_b, part, on_hand_quantity=5)

        validate_success(api.allocate_parts(
            ro_a["id"], make_technician_headers(technician_a["id"])), 200)
        assert get_repair_order(ro_a["id"])["repair_status"] == "PARTS_ALLOCATED"

        inv_a_now = validate_success(api.get_part_inventory(
            inv_a["id"], make_technician_headers(technician_a["id"])), 200)
        assert inv_a_now["reserved_quantity"] == 1
        assert inv_a_now["available_quantity"] == 0
        assert_part_inventory_invariants(inv_a_now)

        # A second order at location A cannot allocate: its available_quantity
        # is exhausted even though location B holds five units.
        appt2 = book_appointment(
            customer, device, location_a, technician_a,
            slot_start="2026-09-02T11:00:00Z", slot_end="2026-09-02T11:30:00Z",
            issue_category="BATTERY")
        ro_a2 = open_repair_order(
            appt2, customer, location_a, issue_category="BATTERY")
        resp = api.allocate_parts(
            ro_a2["id"], make_technician_headers(technician_a["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PARTS.value,
                       expected_status=422)

        inv_b_now = validate_success(api.get_part_inventory(
            inv_b["id"], make_customer_service_headers()), 200)
        assert inv_b_now["available_quantity"] == 5
        assert inv_b_now["reserved_quantity"] == 0

    def test_second_allocation_at_same_location_fails_when_exhausted(self, api):
        """PRD §3.7: "Allocation is skipped for `WHOLE_UNIT_REPLACEMENT` orders
        and requires, for every required component, `available_quantity` greater
        than zero at the `current_location_id`; otherwise the request fails with
        `ERR_INSUFFICIENT_PARTS` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/part_inventory_allocation_across_locations
        """
        set_clock()
        customer, device, location, technician, appointment, ro1 = (
            setup_repair_order(issue_category="SCREEN_DAMAGE")
        )
        part = create_part(model_code="IPHONE_14", part_category="DISPLAY")
        create_inventory(location, part, on_hand_quantity=1)

        validate_success(api.allocate_parts(
            ro1["id"], make_technician_headers(technician["id"])), 200)

        appt2 = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T11:00:00Z", slot_end="2026-09-02T11:30:00Z",
            issue_category="SCREEN_DAMAGE")
        ro2 = open_repair_order(
            appt2, customer, location, issue_category="SCREEN_DAMAGE")
        resp = api.allocate_parts(
            ro2["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PARTS.value,
                       expected_status=422)


class TestInventoryDerivedField:
    def test_part_inventory_available_quantity_is_computed(self, api):
        """PRD §2.8: "A fourth value, `available_quantity`, is never stored: it
        is computed on read as the on-hand quantity minus the reserved quantity
        minus the express-replacement quantity."

        Design: Corner/entities/part_inventory_available_quantity_is_computed
        """
        set_clock()
        location = create_location()
        part = create_part(model_code="IPHONE_14", part_category="DISPLAY")
        inventory = create_inventory(
            location, part, on_hand_quantity=10, express_replacement_quantity=2)
        technician = create_technician(location)

        resp = api.get_part_inventory(
            inventory["id"], make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["available_quantity"] == 8
        assert data["reserved_quantity"] == 0
        assert_part_inventory_invariants(data)

    def test_derived_field_reconciliation_part_inventory(self, api):
        """PRD §2.8: "A fourth value, `available_quantity`, is never stored: it
        is computed on read as the on-hand quantity minus the reserved quantity
        minus the express-replacement quantity. Allocating parts raises
        `reserved_quantity`; ..."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_part_inventory
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="BATTERY")
        )
        part = create_part(model_code="IPHONE_14", part_category="BATTERY")
        inventory = create_inventory(
            location, part, on_hand_quantity=10, express_replacement_quantity=1)

        validate_success(api.allocate_parts(
            repair_order["id"], make_technician_headers(technician["id"])), 200)

        resp = api.get_part_inventory(
            inventory["id"], make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["on_hand_quantity"] == 10
        assert data["reserved_quantity"] == 1
        assert data["available_quantity"] == 8
        assert_part_inventory_invariants(data)


class TestCancelConservation:
    def test_part_inventory_reserved_conservation(self, api):
        """PRD §3.7: "Cancelling from `PARTS_ALLOCATED` additionally flips every
        allocation to `RELEASED` and returns each inventory row's
        `reserved_quantity` by the released amount."

        Design: Difficulty/compensating_invariant/part_inventory_reserved_conservation
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE")
        )
        part = create_part(model_code="IPHONE_14", part_category="DISPLAY")
        inventory = create_inventory(location, part, on_hand_quantity=5)

        validate_success(api.allocate_parts(
            repair_order["id"], make_technician_headers(technician["id"])), 200)
        resp = api.cancel_repair_order(
            repair_order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "CANCELLED"

        inv = validate_success(api.get_part_inventory(
            inventory["id"], make_technician_headers(technician["id"])), 200)
        assert inv["reserved_quantity"] == 0
        assert inv["on_hand_quantity"] == 5
        assert_part_inventory_invariants(inv)

        allocs, meta = validate_paginated(api.list_part_allocations(
            make_customer_service_headers(),
            params={"repair_order_id": repair_order["id"]}))
        assert len(allocs) >= 1
        for alloc in allocs:
            assert alloc["allocation_status"] == "RELEASED"

    def test_cancel_from_triaged_keeps_inventory_untouched(self, api):
        """PRD §3.7: "Cancellation is available from `TRIAGED` or
        `PARTS_ALLOCATED` to the customer or `CustomerService`. Cancelling from
        `TRIAGED` simply closes the order. Cancelling from `PARTS_ALLOCATED`
        additionally flips every allocation to `RELEASED` and returns each
        inventory row's `reserved_quantity` by the released amount."

        Design: Difficulty/compensating_invariant/part_inventory_reserved_conservation
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE")
        )
        part = create_part(model_code="IPHONE_14", part_category="DISPLAY")
        inventory = create_inventory(location, part, on_hand_quantity=5)

        resp = api.cancel_repair_order(
            repair_order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "CANCELLED"

        inv = validate_success(api.get_part_inventory(
            inventory["id"], make_technician_headers(technician["id"])), 200)
        assert inv["reserved_quantity"] == 0
        assert inv["on_hand_quantity"] == 5
        assert inv["available_quantity"] == 5


class TestInvalidTransitions:
    def test_repair_order_allocate_parts_from_in_progress_returns_invalid_state(self, api):
        """PRD §3.7: "A technician allocates parts for a `TRIAGED` order, moving
        it to `PARTS_ALLOCATED`."
        PRD §2.6: "fourth state validity for the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/repair_order_allocate_parts_from_in_progress_returns_invalid_state
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="BATTERY")
        )
        part = create_part(model_code="IPHONE_14", part_category="BATTERY")
        create_inventory(location, part, on_hand_quantity=3)

        walk_to_in_progress(repair_order, device, technician)
        resp = api.allocate_parts(
            repair_order["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestCompletionCascadeDepth:
    def test_incident_counted_flag_set_on_completion(self, api):
        """PRD §2.9: "Completing a repair flips each of its part allocations from
        `RESERVED` to `CONSUMED`, decrements inventory counters, and — when the
        entitlement resolved to `ENTITLED` on an accidental-damage claim whose
        incident has not yet been counted — increments the plan's
        `accidental_damage_incidents_used` and marks the entitlement's
        `incident_counted` flag."

        Design: Difficulty/transitive_cascade/repair_completion_cascades_to_part_consumption_and_incident_count
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
        resolve_entitlement(entitlement, plan, technician)

        # Before completion the incident has not been counted.
        before = validate_success(api.get_coverage_entitlement(
            entitlement["id"], make_customer_service_headers()), 200)
        assert before["incident_counted"] is False
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 0

        walk_to_ready_for_pickup(repair_order, device, technician)
        validate_success(api.complete_pickup(
            repair_order["id"], make_customer_headers(customer["id"])), 200)

        after = validate_success(api.get_coverage_entitlement(
            entitlement["id"], make_customer_service_headers()), 200)
        assert after["incident_counted"] is True
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 1

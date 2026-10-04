"""Route windows, cross-entity gates, and bake-entry timing/safety
(queue A cross_entity_state_dependency, resource_temporal_overlap,
priority_pair temporal-vs-safety; queue B state_machines / validations)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_facility, setup_cxl_dough_type, setup_bmt_dough_type, setup_cafe,
    set_clock, place_and_submit_order,
    create_plan_for_date, lock_plan, release_plan, setup_route, arrive_stop,
    setup_open_schedule, create_bake_entry, start_proof,
    setup_proofing_scenario, setup_single_cafe_day,
    log_pickup, get_pickup, get_cafe, get_order,
    make_cafe_manager_headers,
    create_route_payload, create_route_stop_payload,
)

PLANNER = TEST_USERS["facility_planner_headers"]
DISPATCHER = TEST_USERS["route_dispatcher_headers"]


class TestRouteCapacityHeadroom:
    def test_route_publish_rejects_stop_load_over_vehicle_capacity(self, api):
        """PRD §3.5: "Publishing a route requires that it still be `DRAFT`, that at
        least one stop exists, and that the sum of the stops' planned raw units fits
        within `vehicle_capacity_units` — otherwise the publish is rejected with
        `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/plan_release_requires_route_capacity_headroom
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        place_and_submit_order(cafe, cxl, "2026-09-10", 100)
        plan = create_plan_for_date(facility, "2026-09-10")
        lock_plan(facility, plan)

        route = get_success_data(api.create_route(
            facility["id"], create_route_payload(production_date="2026-09-10",
                                                 vehicle_capacity_units=80),
            DISPATCHER))
        get_success_data(api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=1, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T03:10:00Z",
                                      window_start_local="03:00",
                                      window_end_local="04:00",
                                      planned_units=100),
            DISPATCHER))

        resp = api.publish_route(facility["id"], route["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)
        assert get_success_data(api.get_route(route["id"], PLANNER))["status"] == "DRAFT"

    def test_route_publish_within_vehicle_capacity_succeeds(self, api):
        """PRD §3.5: "Publishing a route requires that it still be `DRAFT`, that at
        least one stop exists, and that the sum of the stops' planned raw units fits
        within `vehicle_capacity_units`".

        Design: Difficulty/cross_entity_state_dependency/plan_release_requires_route_capacity_headroom
        """
        facility = setup_facility()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        route = get_success_data(api.create_route(
            facility["id"], create_route_payload(production_date="2026-09-10",
                                                 vehicle_capacity_units=100),
            DISPATCHER))
        get_success_data(api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=1, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T03:10:00Z",
                                      window_start_local="03:00",
                                      window_end_local="04:00",
                                      planned_units=100),
            DISPATCHER))
        published = validate_success(
            api.publish_route(facility["id"], route["id"], DISPATCHER), 200)
        assert published["status"] == "PUBLISHED"


class TestDonationConfirmGate:
    def test_confirm_pickup_rejected_while_schedule_open(self, api, donation_headers):
        """PRD §3.9: "Confirming a pickup requires the pickup to be `LOGGED` and the
        referenced schedule to be `CLOSED`; confirmation moves the pickup to the
        terminal `CONFIRMED` state."

        Design: Difficulty/cross_entity_state_dependency/donation_confirm_requires_schedule_closed
        """
        facility = setup_facility()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        schedule = setup_open_schedule(cafe, business_date="2026-09-10",
                                       open_clock="2026-09-10T08:00:00Z")
        pickup = log_pickup(cafe, schedule, unsold_conventional=12, unsold_artisan=0)

        resp = api.confirm_donation_pickup(cafe["id"], pickup["id"], donation_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_pickup(pickup["id"])["status"] == "LOGGED"

    def test_confirm_pickup_succeeds_once_schedule_closed(self, api, donation_headers):
        """PRD §3.9: "Confirming a pickup requires the pickup to be `LOGGED` and the
        referenced schedule to be `CLOSED`; confirmation moves the pickup to the
        terminal `CONFIRMED` state."

        Design: Difficulty/cross_entity_state_dependency/donation_confirm_requires_schedule_closed
        """
        from test_helpers import setup_closed_schedule
        facility = setup_facility()
        setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        schedule = setup_closed_schedule(cafe, business_date="2026-09-10",
                                         open_clock="2026-09-10T08:00:00Z")
        pickup = log_pickup(cafe, schedule, unsold_conventional=12, unsold_artisan=0)
        confirmed = validate_success(
            api.confirm_donation_pickup(cafe["id"], pickup["id"], donation_headers), 200)
        assert confirmed["status"] == "CONFIRMED"


class TestRouteStopWindowOverlap:
    def test_zero_gap_windows_on_same_cafe_rejected(self, api):
        """PRD §3.5: "The same code guards a subtler case: two stops on the same cafe
        must not have overlapping windows with zero gap between them."
        PRD §3.5: "The planned arrival must fall inside the half-open window —
        strictly after the open bound and at or before the close bound; a stop
        created outside its window is rejected with `ERR_STOP_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/route_stop_window_overlap_rejected
        """
        facility = setup_facility()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        route = get_success_data(api.create_route(
            facility["id"], create_route_payload(production_date="2026-09-10",
                                                 vehicle_capacity_units=500),
            DISPATCHER))
        get_success_data(api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=1, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T03:10:00Z",
                                      window_start_local="03:00",
                                      window_end_local="04:00",
                                      planned_units=100),
            DISPATCHER))

        # [04:00, 05:00] touches [03:00, 04:00] at 04:00 — zero-gap adjacency.
        resp = api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=2, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T04:10:00Z",
                                      window_start_local="04:00",
                                      window_end_local="05:00",
                                      planned_units=50),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_VIOLATION, 422)

    def test_stops_with_a_real_gap_on_same_cafe_accepted(self, api):
        """PRD §3.5: "two stops on the same cafe must not have overlapping windows
        with zero gap between them."

        A one-minute gap between [03:00, 04:00] and [04:01, 05:00] is not a zero-gap
        overlap, so the stop is accepted.

        Design: Difficulty/resource_temporal_overlap/route_stop_window_overlap_rejected
        """
        facility = setup_facility()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        route = get_success_data(api.create_route(
            facility["id"], create_route_payload(production_date="2026-09-10",
                                                 vehicle_capacity_units=500),
            DISPATCHER))
        get_success_data(api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=1, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T03:10:00Z",
                                      window_start_local="03:00",
                                      window_end_local="04:00",
                                      planned_units=100),
            DISPATCHER))
        second = validate_success(api.create_route_stop(
            facility["id"], route["id"],
            create_route_stop_payload(seq=2, cafe_id=cafe["id"],
                                      planned_arrival="2026-09-10T04:10:00Z",
                                      window_start_local="04:01",
                                      window_end_local="05:00",
                                      planned_units=50),
            DISPATCHER), 201)
        assert second["status"] == "SCHEDULED"


class TestBakeEntryProofOverlap:
    def test_overlapping_proof_interval_rejected(self, api):
        """PRD §2.7: "then the stop-window rules (`ERR_STOP_WINDOW_VIOLATION`)".

        A second bake entry whose proof interval [05:29, 06:29) overlaps the first
        entry's [04:00, 05:30) is rejected with ERR_STOP_WINDOW_VIOLATION.

        Design: Difficulty/resource_temporal_overlap/bake_entry_proof_interval_overlap_rejected
        """
        day = setup_proofing_scenario(quantity=100, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:00:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:00:00Z")
        mgr = make_cafe_manager_headers(day["cafe"]["id"])
        resp = api.create_bake_entry(
            day["cafe"]["id"], day["schedule"]["id"],
            {"cafe_order_id": day["order"]["id"], "quantity": 20,
             "proof_start_at": "2026-09-10T05:29:00Z", "proof_minutes": 60},
            mgr)
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_VIOLATION, 422)

    def test_back_to_back_proof_interval_accepted(self, api):
        """PRD §3.7: "baking starts exactly `proof_minutes` after proofing starts."

        A 05:30 start begins exactly when the first entry's [04:00, 05:30) interval
        ends — back-to-back adjacency is legal on bake entries.

        Design: Difficulty/resource_temporal_overlap/bake_entry_proof_interval_overlap_rejected
        """
        day = setup_proofing_scenario(quantity=100, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:00:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:00:00Z")
        mgr = make_cafe_manager_headers(day["cafe"]["id"])
        second = validate_success(api.create_bake_entry(
            day["cafe"]["id"], day["schedule"]["id"],
            {"cafe_order_id": day["order"]["id"], "quantity": 20,
             "proof_start_at": "2026-09-10T05:30:00Z", "proof_minutes": 60},
            mgr), 201)
        assert second["status"] == "SCHEDULED"


class TestPriorityTemporalVsSafety:
    def test_shelf_life_fires_before_proof_timing(self, api):
        """PRD §2.7: "then the safety rules — the no-substitution guard
        (`ERR_SUBSTITUTION_FORBIDDEN`) and the shelf-life gate
        (`ERR_SHELF_LIFE_EXCEEDED`) — then the stop-window rules
        (`ERR_STOP_WINDOW_VIOLATION`), then the credit-limit check
        (`ERR_CREDIT_LIMIT_EXCEEDED`), then the capacity gates
        (`ERR_CAPACITY_EXCEEDED`), then uniqueness (`ERR_DUPLICATE`), then
        proof-timing (`ERR_TOO_EARLY`)".
        PRD §3.7: "A bake started at or after that instant is rejected with
        `ERR_SHELF_LIFE_EXCEEDED`."

        Clock parked past CXL expiry (2026-09-11T12:00Z), before the proof window's
        nominal bake instant — safety outranks timing.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_safety_on_early_bake_of_expired_dough
        """
        day = setup_proofing_scenario(quantity=100, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:30:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:30:00Z")
        set_clock("2026-09-11T12:30:00Z")
        resp = api.start_bake(day["cafe"]["id"], day["schedule"]["id"],
                              day["entry"]["id"],
                              make_cafe_manager_headers(day["cafe"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_EXCEEDED, 422)

    def test_start_bake_before_proof_elapsed_is_too_early(self, api):
        """PRD §3.7: "Starting the bake requires the entry to be `PROOFING`, the
        current time to be at or after the proof-start instant plus the proof
        duration (`ERR_TOO_EARLY` again if early)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_safety_on_early_bake_of_expired_dough
        """
        day = setup_proofing_scenario(quantity=100, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:00:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:00:00Z")
        set_clock("2026-09-10T05:29:00Z")
        resp = api.start_bake(day["cafe"]["id"], day["schedule"]["id"],
                              day["entry"]["id"],
                              make_cafe_manager_headers(day["cafe"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TOO_EARLY, 409)


class TestScheduleGates:
    def test_schedule_open_on_wrong_date_rejected(self, api):
        """PRD §3.7: "The schedule is created `PLANNED` and can only be opened on the
        day itself: opening requires that the current cafe-local date equal the
        schedule's `business_date`, at which point it becomes `OPEN`."

        Design: Corner/state_machines/schedule_open_on_wrong_date_rejected
        """
        facility = setup_facility()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        mgr = make_cafe_manager_headers(cafe["id"])
        schedule = get_success_data(
            api.create_schedule(cafe["id"], {"business_date": "2026-09-10"}, mgr))
        set_clock("2026-09-09T23:00:00Z")
        resp = api.open_schedule(cafe["id"], schedule["id"], mgr)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_schedule_close_with_live_entry_rejected(self, api):
        """PRD §3.7: "Closing the schedule requires that every entry on it be in a
        terminal state — `COMPLETED` or `DISCARDED`."

        Design: Corner/state_machines/schedule_close_with_live_entry_rejected
        """
        day = setup_proofing_scenario(quantity=40, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:00:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:00:00Z")
        resp = api.close_schedule(day["cafe"]["id"], day["schedule"]["id"],
                                  make_cafe_manager_headers(day["cafe"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestTemporalBoundaries:
    def test_order_submit_at_exact_cutoff_rejected(self, api):
        """PRD §3.2: "submission must occur strictly before the dough type's
        `order_cutoff_local` on the day before the `production_date`; at or after
        that instant the attempt is rejected with `ERR_ORDER_CUTOFF_PASSED`."

        Design: Corner/validations/order_submit_at_exact_cutoff_rejected
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        set_clock("2026-09-09T10:00:00Z")
        from test_helpers import create_order
        order = create_order(cafe, cxl, "2026-09-10", 10)
        set_clock("2026-09-09T13:00:00Z")
        resp = api.submit_cafe_order(order["id"],
                                     make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_CUTOFF_PASSED, 409)

    def test_shelf_life_bake_at_exact_expiry_rejected(self, api):
        """PRD §3.7: "the dough to still be alive: the bake must start strictly
        before the dough's expiry instant, which is midnight at the start of the
        order's `production_date` plus the dough type's `shelf_life_hours`. A bake
        started at or after that instant is rejected with `ERR_SHELF_LIFE_EXCEEDED`."

        CXL shelf life 36h from 2026-09-10T00:00Z expires at 2026-09-11T12:00Z.

        Design: Corner/validations/shelf_life_bake_at_exact_expiry_rejected
        """
        day = setup_proofing_scenario(quantity=40, entry_quantity=40,
                                      proof_start_at="2026-09-10T04:00:00Z",
                                      proof_minutes=90,
                                      proof_clock="2026-09-10T04:00:00Z")
        set_clock("2026-09-11T12:00:00Z")
        resp = api.start_bake(day["cafe"]["id"], day["schedule"]["id"],
                              day["entry"]["id"],
                              make_cafe_manager_headers(day["cafe"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_EXCEEDED, 422)

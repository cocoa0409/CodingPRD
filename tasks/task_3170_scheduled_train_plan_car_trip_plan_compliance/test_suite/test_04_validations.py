"""Corner-queue tests: validation ordering, embargo gating, pickup window,
resource positioning, trip-plan structural integrity, and auth failures."""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assign_trip_legs,
    create_active_plan,
    create_crew_pool,
    create_customer,
    create_locomotive,
    create_shipment,
    create_train_plan,
    create_yard,
    get_shipment,
    get_success_data,
    record_car_event,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

NP = TEST_USERS["network_planner_headers"]
CD = TEST_USERS["crew_dispatcher_headers"]
PP = TEST_USERS["power_planner_headers"]
TS = TEST_USERS["terminal_superintendent_headers"]
SM = TEST_USERS["service_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestExistenceBeforeOcc:
    def test_retire_missing_plan_returns_404_not_stale_version(self, api):
        """PRD §2.9: "third, referenced-resource existence, evaluated
        left-to-right; fourth, optimistic-concurrency version match" and "the
        client observes only the earliest failing check".

        Design: Corner/validations/retire_missing_plan_returns_404_not_stale_version
        """
        yA = create_yard(yard_code="EXS-A")
        yB = create_yard(yard_code="EXS-B")
        plan = create_train_plan(yA["id"], yB["id"], train_symbol="EXS-P",
                                 scheduled_departure_utc="2026-09-02T08:00:00Z",
                                 frequency_mask=["WED"])
        resp = api.retire_train_plan(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {"expected_train_plan_version": plan["version"]},
            NP,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value)


class TestPickupWindow:
    def test_pickup_window_deadline_boundary(self, api):
        """PRD §3.7: "if the logical clock has passed the shipment's
        `first_mile_pickup_by` at assignment time, the request is rejected
        with `ERR_PICKUP_WINDOW_MISSED` (HTTP 409) and the shipment's
        `compliance_status` is stamped `OFF_PLAN` at that moment".

        Design: Corner/validations/pickup_window_deadline_boundary
        """
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="PK-A")
        yB = create_yard(yard_code="PK-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="PK-P",
            scheduled_departure_utc="2026-09-01T09:00:00Z",
        )
        cu = create_customer()
        s1 = create_shipment(cu["id"], yA["id"], yB["id"], car_count=1,
                             first_mile_pickup_by="2026-09-01T08:00:00Z")
        s2 = create_shipment(cu["id"], yA["id"], yB["id"], car_count=1,
                             first_mile_pickup_by="2026-09-01T08:00:00Z")

        # At exactly the deadline the clock has NOT passed it: allowed.
        set_clock("2026-09-01T08:00:00Z")
        legs = validate_success(
            api.assign_trip_legs(
                s1["id"],
                {
                    "expected_shipment_version": s1["version"],
                    "legs": [{"train_plan_id": plan["id"], "leg_sequence": 1}],
                },
                NP,
            ),
            expected_status=201,
        )
        assert get_shipment(s1["id"])["trip_plan_status"] == "ASSIGNED"

        # One second past: rejected.
        set_clock("2026-09-01T08:00:01Z")
        resp = api.assign_trip_legs(
            s2["id"],
            {
                "expected_shipment_version": s2["version"],
                "legs": [{"train_plan_id": plan["id"], "leg_sequence": 1}],
            },
            NP,
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_MISSED.value)
        s2_now = get_shipment(s2["id"])
        assert s2_now["trip_plan_status"] == "UNASSIGNED"
        assert s2_now["compliance_status"] == "OFF_PLAN"


class TestDepartureSchedulingGates:
    def test_departure_on_non_operating_day_rejected(self, api, any_headers):
        """PRD §3.5: "the `service_date` must be an operating day under the
        plan's `frequency_mask` (otherwise `ERR_DEPARTURE_DAY_NOT_OPERATED`,
        HTTP 409)".

        Design: Corner/validations/departure_on_non_operating_day_rejected
        """
        yA = create_yard(yard_code="VD-A")
        yB = create_yard(yard_code="VD-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="VD-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["MON", "WED", "FRI"],
        )
        pool = create_crew_pool(yA["id"], service_date="2026-09-01")
        loco = create_locomotive(yA["id"], unit_number="VD-UP1")
        resp = api.create_train_departure(
            {
                "train_plan_id": plan["id"], "service_date": "2026-09-01",
                "crew_pool_id": pool["id"], "locomotive_id": loco["id"],
                "car_count_planned": 5, "crew_hours_estimated": 6,
            },
            TS,
        )
        validate_error(resp, ApiErrorId.ERR_DEPARTURE_DAY_NOT_OPERATED.value)
        loco_now = get_success_data(api.get_locomotive(loco["id"], any_headers))
        assert loco_now["status"] == "AVAILABLE"

    def test_engineer_pool_craft_mismatch_rejected(self, api, any_headers):
        """PRD §3.5: "the named pool's `craft` must be `CONDUCTOR` and its
        `home_yard_id` must equal the plan's origin yard (otherwise
        `ERR_POOL_CRAFT_MISMATCH`, HTTP 409)".

        Design: Corner/validations/engineer_pool_craft_mismatch_rejected
        """
        yA = create_yard(yard_code="VC-A")
        yB = create_yard(yard_code="VC-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="VC-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        pool = create_crew_pool(yA["id"], craft="ENGINEER")
        loco = create_locomotive(yA["id"], unit_number="VC-UP1")
        resp = api.create_train_departure(
            {
                "train_plan_id": plan["id"], "service_date": "2026-09-01",
                "crew_pool_id": pool["id"], "locomotive_id": loco["id"],
                "car_count_planned": 5, "crew_hours_estimated": 6,
            },
            TS,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_CRAFT_MISMATCH.value)
        loco_now = get_success_data(api.get_locomotive(loco["id"], any_headers))
        assert loco_now["status"] == "AVAILABLE"


class TestEmbargoGating:
    def test_embargo_blocks_shipment_create_and_assignment(self, api, any_headers):
        """PRD §2.6: "shipment creation is forbidden when the origin or
        destination yard is `EMBARGOED`, trip-plan assignment is forbidden
        when any leg endpoint yard is `EMBARGOED`, and departure finalization
        is forbidden when the origin yard is `EMBARGOED` — all three
        rejections carry `ERR_YARD_EMBARGOED` (HTTP 409)."

        Design: Corner/validations/embargo_blocks_shipment_create_and_assignment
        """
        set_clock("2026-09-01T03:00:00Z")
        yA = create_yard(yard_code="EM-A")
        yC = create_yard(yard_code="EM-C", dwell_benchmark_hours=10)
        p0 = create_active_plan(
            yA["id"], yC["id"], train_symbol="EM-P0",
            scheduled_departure_utc="2026-09-01T05:00:00Z",
            cutoff_minutes=30, route_distance_miles=100,
        )
        cu = create_customer()
        s0 = create_shipment(
            cu["id"], yA["id"], yC["id"], car_count=3,
            first_mile_pickup_by="2026-09-01T04:30:00Z",
            last_mile_delivery_by="2026-09-06T00:00:00Z",
            committed_route_miles=100,
        )
        assign_trip_legs(s0, [p0["id"]])
        pool = create_crew_pool(yA["id"])
        loco = create_locomotive(yA["id"], unit_number="EM-UP1")
        dep = get_success_data(
            api.create_train_departure(
                {
                    "train_plan_id": p0["id"], "service_date": "2026-09-01",
                    "crew_pool_id": pool["id"], "locomotive_id": loco["id"],
                    "car_count_planned": 3, "crew_hours_estimated": 4,
                },
                TS,
            )
        )
        set_clock("2026-09-01T05:00:00Z")
        validate_success(api.finalize_train_departure(dep["id"], TS))
        record_car_event(s0["id"], yA["id"], "TRAIN_DEPARTURE",
                         "2026-09-01T05:00:00Z", 3)
        set_clock("2026-09-01T06:00:00Z")
        record_car_event(s0["id"], yC["id"], "YARD_ARRIVAL",
                         "2026-09-01T06:00:00Z", 3)

        # At 2026-09-02T13:00:00Z the open session is 31h old: overage 21 > 20.
        set_clock("2026-09-02T13:00:00Z")
        yard = get_success_data(api.get_yard(yC["id"], ANY))
        assert yard["posture"] == "EMBARGOED"

        resp = api.create_shipment(
            {
                "customer_id": cu["id"], "origin_yard_id": yA["id"],
                "destination_yard_id": yC["id"], "car_count": 1,
                "first_mile_pickup_by": "2026-09-03T06:00:00Z",
                "last_mile_delivery_by": "2026-09-06T00:00:00Z",
                "committed_route_miles": 100,
            },
            SM,
        )
        validate_error(resp, ApiErrorId.ERR_YARD_EMBARGOED.value)

        # Release the dwell; the retry succeeds.
        record_car_event(s0["id"], yC["id"], "CLASSIFICATION_COMPLETE",
                         "2026-09-02T13:00:00Z", 3)
        retry = validate_success(
            api.create_shipment(
                {
                    "customer_id": cu["id"], "origin_yard_id": yA["id"],
                    "destination_yard_id": yC["id"], "car_count": 1,
                    "first_mile_pickup_by": "2026-09-03T06:00:00Z",
                    "last_mile_delivery_by": "2026-09-06T00:00:00Z",
                    "committed_route_miles": 100,
                },
                SM,
            ),
            expected_status=201,
        )
        assert retry["status"] == "OPEN"
        yard_after = get_success_data(api.get_yard(yC["id"], ANY))
        assert yard_after["posture"] == "OPEN"
        assert yard_after["current_dwell_overage_hours"] == 0


class TestAuthFailures:
    def test_unauthenticated_request_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/unauthenticated_request_returns_400
        """
        resp = api.get_yard(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ANONYMOUS_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_forbidden_role_returns_403(self, api, cd_headers):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/errors/forbidden_role_returns_403
        """
        resp = api.create_train_plan({}, cd_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_missing_required_field_returns_400(self, api, np_headers, any_headers):
        """PRD §2.10: "Bodies that are malformed, missing a required field,
        carrying an invalid enum value, or supplying a non-positive number
        where a positive value is required are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/missing_required_field_returns_400
        """
        resp = api.create_yard(
            {"yard_code": "VF-1", "dwell_benchmark_hours": 10}, np_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
        _data, meta = validate_paginated(api.list_yards(any_headers))
        assert meta["total_count"] == 0


class TestTripPlanStructuralIntegrity:
    def test_disjoint_trip_chain_rejected(self, api, any_headers):
        """PRD §3.7: "Any break in this chain — non-contiguous sequence
        numbers, a yard mismatch between consecutive legs, or endpoints that
        fail to meet the shipment's own origin and destination — is rejected
        with `ERR_TRIP_PLAN_DISJOINT` (HTTP 422)."

        Design: Corner/errors/disjoint_trip_chain_rejected
        """
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="VF-A")
        yB = create_yard(yard_code="VF-B")
        yC = create_yard(yard_code="VF-C")
        yD = create_yard(yard_code="VF-D")
        p1 = create_active_plan(
            yA["id"], yB["id"], train_symbol="VF-P1",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        p2 = create_active_plan(
            yC["id"], yD["id"], train_symbol="VF-P2",
            scheduled_departure_utc="2026-09-03T08:00:00Z",
            frequency_mask=["THU"],
        )
        cu = create_customer()
        s = create_shipment(
            cu["id"], yA["id"], yD["id"], car_count=1,
            first_mile_pickup_by="2026-09-02T06:00:00Z",
            last_mile_delivery_by="2026-09-06T00:00:00Z",
            committed_route_miles=600,
        )
        resp = api.assign_trip_legs(
            s["id"],
            {
                "expected_shipment_version": s["version"],
                "legs": [
                    {"train_plan_id": p1["id"], "leg_sequence": 1},
                    {"train_plan_id": p2["id"], "leg_sequence": 2},
                ],
            },
            NP,
        )
        validate_error(resp, ApiErrorId.ERR_TRIP_PLAN_DISJOINT.value)
        s_now = get_shipment(s["id"])
        assert s_now["trip_plan_status"] == "UNASSIGNED"
        legs, meta = validate_paginated(
            api.list_shipment_trip_legs(s["id"], any_headers)
        )
        assert meta["total_count"] == 0

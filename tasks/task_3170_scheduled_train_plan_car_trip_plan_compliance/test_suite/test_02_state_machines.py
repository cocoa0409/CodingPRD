"""Corner-queue tests: state-machine transition guards (plans, pools,
locomotives, shipments, exceptions)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_trip_legs,
    create_active_plan,
    create_crew_pool,
    create_customer,
    create_locomotive,
    create_shipment,
    create_yard,
    finalize_and_depart,
    get_pool,
    get_shipment,
    get_success_data,
    get_yard,
    list_exceptions_for_shipment,
    set_clock,
    setup_operational_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTrainPlanActivation:
    def test_plan_activate_twice_rejected(self, api, np_headers, any_headers):
        """PRD §3.1: "activating a plan not in `DRAFT` is rejected with
        `ERR_PLAN_NOT_DRAFT` (HTTP 409)".

        Design: Corner/state_machines/plan_activate_twice_rejected
        """
        yA = create_yard(yard_code="SM1-A")
        yB = create_yard(yard_code="SM1-B")
        plan = get_success_data(
            api.create_train_plan(
                {
                    "train_symbol": "SM1-P",
                    "origin_yard_id": yA["id"],
                    "destination_yard_id": yB["id"],
                    "scheduled_departure_utc": "2026-09-02T08:00:00Z",
                    "cutoff_minutes": 30,
                    "frequency_mask": ["WED"],
                    "route_distance_miles": 100,
                    "dwell_benchmark_hours": 10,
                },
                np_headers,
            )
        )
        activated = validate_success(
            api.activate_train_plan(
                plan["id"], {"expected_train_plan_version": plan["version"]}, np_headers
            )
        )
        # Second activation carries the CURRENT version (OCC passes).
        resp = api.activate_train_plan(
            plan["id"],
            {"expected_train_plan_version": activated["version"]},
            np_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT.value)
        reread = get_success_data(api.get_train_plan(plan["id"], any_headers))
        assert reread["status"] == "ACTIVE"
        assert reread["version"] == activated["version"], (
            "rejected activation must not bump version"
        )


class TestCrewPoolLifecycle:
    def test_pool_replenish_while_open_rejected(self, api, np_headers, cd_headers, any_headers):
        """PRD §3.3: "replenishment requires the pool to be `EXHAUSTED`
        (otherwise `ERR_POOL_NOT_REPLENISHABLE`, HTTP 409)".

        Design: Corner/state_machines/pool_replenish_while_open_rejected
        """
        yA = create_yard(yard_code="SM2-A")
        pool = create_crew_pool(yA["id"], crews_available=3)
        resp = api.replenish_crew_pool(pool["id"], {"additional_crews": 2}, cd_headers)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_REPLENISHABLE.value)
        reread = get_pool(pool["id"])
        assert reread["crews_available"] == 3
        assert reread["status"] == "OPEN"

    def test_pool_close_and_second_close_rejected(self, api, np_headers, cd_headers):
        """PRD §3.3: "Closing is refused with `ERR_POOL_ALREADY_CLOSED`
        (HTTP 409) when the pool is not in `OPEN` or `REOPENED`".

        Design: Corner/state_machines/pool_close_and_second_close_rejected
        """
        yA = create_yard(yard_code="SM3-A")
        pool = create_crew_pool(yA["id"], craft="ENGINEER", crews_available=2)
        first = validate_success(api.close_crew_pool(pool["id"], cd_headers))
        assert first["status"] == "CLOSED"
        second = api.close_crew_pool(pool["id"], cd_headers)
        validate_error(second, ApiErrorId.ERR_POOL_ALREADY_CLOSED.value)


class TestLocomotiveLifecycle:
    def test_locomotive_release_repair_while_available_rejected(self, api, np_headers, pp_headers, any_headers):
        """PRD §3.4: "later release it from repair back to `AVAILABLE` (a unit
        not `BAD_ORDER` is rejected with `ERR_UNIT_NOT_BAD_ORDER`, HTTP 409)".

        Design: Corner/state_machines/locomotive_release_repair_while_available_rejected
        """
        yA = create_yard(yard_code="SM4-A")
        loco = create_locomotive(yA["id"], unit_number="SM4-UP1")
        resp = api.release_repair_locomotive(loco["id"], pp_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_BAD_ORDER.value)
        reread = get_success_data(api.get_locomotive(loco["id"], any_headers))
        assert reread["status"] == "AVAILABLE"


class TestShipmentCancelGuard:
    def test_shipment_cancel_after_departure_rejected(self, api, sm_headers, any_headers):
        """PRD §3.9: "only an `OPEN` shipment is cancellable, otherwise
        `ERR_SHIPMENT_NOT_CANCELLABLE` (HTTP 409)".

        Design: Corner/state_machines/shipment_cancel_after_departure_rejected
        """
        sc = setup_operational_scenario(
            "SM5", crews_available=1, shipment_car_count=1,
            delivery_by="2026-09-04T00:00:00Z",
        )
        finalize_and_depart(sc, "2026-09-01T08:00:00Z")
        resp = api.cancel_shipment(sc["shipment"]["id"], sm_headers)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_CANCELLABLE.value)
        reread = get_shipment(sc["shipment"]["id"])
        assert reread["status"] == "IN_TRANSIT"


class TestDepartureFinalizeGuards:
    def test_departure_finalize_before_schedule_rejected(self, api, np_headers, ts_headers, any_headers):
        """PRD §3.5: "the logical clock must have reached the plan's
        `scheduled_departure_utc`; an early finalize is rejected with
        `ERR_DEPARTURE_TOO_EARLY` (HTTP 409)".

        Design: Corner/state_machines/departure_finalize_before_schedule_rejected
        """
        sc = setup_operational_scenario(
            "SM6", crews_available=1, shipment_car_count=1, assign=False,
        )
        set_clock("2026-09-01T07:59:00Z")
        resp = api.finalize_train_departure(sc["departure"]["id"], ts_headers)
        validate_error(resp, ApiErrorId.ERR_DEPARTURE_TOO_EARLY.value)
        dep = get_success_data(
            api.get_train_departure(sc["departure"]["id"], any_headers)
        )
        assert dep["status"] == "SCHEDULED"
        pool = get_pool(sc["pool"]["id"])
        assert pool["crews_booked"] == 0, "rejected finalize must not book a crew"


class TestExceptionRecoveryGate:
    def _setup_missed_connection_exception(self, api, prefix):
        """Shipment assigned to a plan whose departure is then cancelled:
        the leg misses and a MISSED_CONNECTION exception is raised."""
        sc = setup_operational_scenario(
            prefix, shipment_car_count=2, delivery_by="2026-09-04T00:00:00Z",
        )
        set_clock("2026-09-01T07:00:00Z")
        validate_success(
            api.cancel_train_departure(
                sc["departure"]["id"], TEST_USERS["terminal_superintendent_headers"]
            )
        )
        exceptions = list_exceptions_for_shipment(sc["shipment"]["id"])
        assert len(exceptions) == 1
        return sc, exceptions[0]

    def test_exception_resolve_requires_replanned_shipment(self, api, sm_headers, any_headers):
        """PRD §3.10: "a `MISSED_CONNECTION` exception cannot resolve until the
        shipment has been replanned — its `trip_plan_status` must be `ASSIGNED`
        or `REPLANNED` — otherwise the resolution is rejected with
        `ERR_EXCEPTION_NOT_RECOVERABLE` (HTTP 409)".

        Design: Corner/state_machines/exception_resolve_requires_replanned_shipment
        """
        sc, exc = self._setup_missed_connection_exception(api, "EX1")
        validate_success(
            api.triage_service_exception(
                exc["id"],
                {"triage_notes": "crew van delayed", "root_cause_code": "CREW_SHORTAGE"},
                sm_headers,
            )
        )
        resp = api.resolve_service_exception(exc["id"], sm_headers)
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_RECOVERABLE.value)
        reread = get_success_data(api.get_service_exception(exc["id"], any_headers))
        assert reread["status"] == "INVESTIGATING"

    def test_exception_full_lifecycle_after_replan(self, api, np_headers, sm_headers, any_headers):
        """PRD §3.7: "submitting a new itinerary supersedes every prior leg
        still in `PLANNED` or `MISSED` to `REPLACED`, stamps the shipment's
        `trip_plan_status` as `REPLANNED` when superseding a
        `MISSED_CONNECTION` itinerary".
        PRD §3.10: "Resolution moves an `INVESTIGATING` exception to the
        terminal `RESOLVED` state and again increments `version`".
        PRD §3.9: "a shipment is `AT_RISK` when it has exactly one missed
        connection or any open `DEPARTURE_DELAY` exception against it".

        Design: Corner/state_machines/exception_full_lifecycle_after_replan
        """
        sc, exc = self._setup_missed_connection_exception(api, "EX2")
        # A replacement plan departing later the same day.
        p2 = create_active_plan(
            sc["yA"]["id"], sc["yB"]["id"],
            train_symbol="EX2-P2",
            scheduled_departure_utc="2026-09-01T20:00:00Z",
            frequency_mask=["TUE"],
        )
        validate_success(
            api.triage_service_exception(
                exc["id"],
                {"triage_notes": "power failure at origin", "root_cause_code": "POWER_SHORTAGE"},
                sm_headers,
            )
        )
        shipment_now = get_shipment(sc["shipment"]["id"])
        new_legs = validate_success(
            api.assign_trip_legs(
                sc["shipment"]["id"],
                {
                    "expected_shipment_version": shipment_now["version"],
                    "legs": [{"train_plan_id": p2["id"], "leg_sequence": 1}],
                },
                np_headers,
            ),
            expected_status=201,
        )
        assert new_legs[0]["status"] == "PLANNED"
        all_legs, _meta = validate_paginated(
            api.list_shipment_trip_legs(sc["shipment"]["id"], any_headers)
        )
        old_leg = [l for l in all_legs if l["train_plan_id"] == sc["plan"]["id"]][0]
        assert old_leg["status"] == "REPLACED"
        shipment_after = get_shipment(sc["shipment"]["id"])
        assert shipment_after["trip_plan_status"] == "REPLANNED"

        resolved = validate_success(api.resolve_service_exception(exc["id"], sm_headers))
        assert resolved["status"] == "RESOLVED"
        final = get_shipment(sc["shipment"]["id"])
        assert final["compliance_status"] == "AT_RISK", (
            "exactly one missed connection on the tally keeps AT_RISK"
        )

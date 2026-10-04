"""Corner-queue tests: optimistic concurrency control and version/updated_at
progression across mutations."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_plan,
    create_customer,
    create_shipment,
    create_train_plan,
    create_yard,
    get_shipment,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

NP = TEST_USERS["network_planner_headers"]
ANY = TEST_USERS["any_headers"]


class TestOccOnTrainPlan:
    def test_occ_stale_version_on_plan_activate(self, api, any_headers):
        """PRD §2.7: "If another writer has advanced the plan's version since
        that read — by a successful activation or retirement — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's
        view of the plan is stale and must be re-read."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_activate
        """
        yA = create_yard(yard_code="OC-A")
        yB = create_yard(yard_code="OC-B")
        plan = create_train_plan(
            yA["id"], yB["id"], train_symbol="OC-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        first = validate_success(
            api.activate_train_plan(
                plan["id"], {"expected_train_plan_version": plan["version"]}, NP
            )
        )
        assert first["status"] == "ACTIVE"
        assert first["version"] == plan["version"] + 1
        resp = api.activate_train_plan(
            plan["id"], {"expected_train_plan_version": plan["version"]}, NP
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        reread = get_success_data(api.get_train_plan(plan["id"], any_headers))
        assert reread["version"] == plan["version"] + 1, (
            "the rejected write must not bump the version"
        )


class TestOccOnTripPlanAssignment:
    def test_occ_stale_version_on_trip_plan_assignment(self, api):
        """PRD §2.7: "Trip-plan assignment or replanning for a shipment
        requires `expected_shipment_version` matching the shipment's current
        `version`. If the shipment's version has advanced since the client
        last read it ... the assignment is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_trip_plan_assignment
        """
        set_clock("2026-09-01T07:00:00Z")
        yA = create_yard(yard_code="OC2-A")
        yB = create_yard(yard_code="OC2-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="OC2-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        cu = create_customer()
        s = create_shipment(
            cu["id"], yA["id"], yB["id"], car_count=1,
            first_mile_pickup_by="2026-09-02T06:00:00Z",
        )
        payload = {
            "expected_shipment_version": s["version"],
            "legs": [{"train_plan_id": plan["id"], "leg_sequence": 1}],
        }
        validate_success(
            api.assign_trip_legs(s["id"], payload, NP), expected_status=201
        )
        assert get_shipment(s["id"])["trip_plan_status"] == "ASSIGNED"
        # The same stale version is now rejected.
        resp = api.assign_trip_legs(s["id"], dict(payload), NP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestVersionProgression:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "`version` is a system-managed integer that increments
        by exactly one on every mutation to the resource" and "`updated_at`
        refreshes on every mutation."
        PRD §3.1: "Retirement moves an `ACTIVE` plan to its terminal state
        `RETIRED`."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="OC3-A")
        yB = create_yard(yard_code="OC3-B")
        plan = create_train_plan(
            yA["id"], yB["id"], train_symbol="OC3-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        assert plan["version"] == 1
        created_stamp = plan["updated_at"]

        set_clock("2026-09-01T07:00:00Z")
        activated = validate_success(
            api.activate_train_plan(
                plan["id"], {"expected_train_plan_version": 1}, NP
            )
        )
        assert activated["version"] == 2
        assert activated["updated_at"] > created_stamp, (
            "updated_at refreshes at each mutation"
        )

        retired = validate_success(
            api.retire_train_plan(
                plan["id"], {"expected_train_plan_version": 2}, NP
            )
        )
        assert retired["version"] == 3
        assert retired["status"] == "RETIRED"

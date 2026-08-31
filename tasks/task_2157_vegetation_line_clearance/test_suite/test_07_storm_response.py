"""Storm preemption, the remainder-child split, and demobilization."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, assert_storm_event, current_crew_version, new_active_storm,
    read_booking, read_circuit, read_crew, read_plan, read_span, read_storm,
    setup_in_progress_span, setup_storm_preempted_span, validate_error, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestStormReassignmentCascade:
    """Crew → booking → span → plan → circuit, every hop settled before the response."""

    def test_deploying_the_crew_preempts_its_booking_and_splits_the_span(self, api):
        """PRD §3.8: "Hop two takes every booking of that crew whose `status` is `SCHEDULED` or
        `ACTIVE` to `PREEMPTED` and stamps each one's `preempted_by_storm_event_id` with the
        event."
        PRD §3.8: "The child's `planned_unit_count` is the parent's `planned_unit_count` less
        the parent's `actual_units_completed` — the work that was left undone — and the
        parent's `planned_unit_count` is simultaneously reduced to its
        `actual_units_completed`."

        Design: Difficulty/transitive_cascade/storm_reassignment_cascades_crew_to_assignment_to_span_to_plan_to_circuit
        """
        world = setup_storm_preempted_span(units_trimmed=10, labor_hours=2,
                                           equipment_hours=1, disposal_tons=0)

        assert read_crew(world["crew"]["id"])["status"] == "STORM_DEPLOYED"
        booking = read_booking(world["booking"]["id"])
        assert booking["status"] == "PREEMPTED"
        assert booking["preempted_by_storm_event_id"] == world["storm"]["id"]

        parent = read_span(world["span"]["id"])
        child = read_span(world["child"]["id"])
        assert parent["execution_status"] == "STORM_PREEMPTED"
        assert parent["planned_unit_count"] == 10
        assert child["execution_status"] == "PLANNED"
        assert child["planned_unit_count"] == 190
        assert child["parent_work_order_id"] == world["span"]["id"]
        assert child["storm_event_id"] == world["storm"]["id"], \
            "storm_event_id lands on the spawned child, never on the preempted parent"

    def test_the_preempted_span_suspends_the_plan_and_puts_the_circuit_at_risk(self, api):
        """PRD §3.8: "Hop four propagates upward: a plan in `IN_PROGRESS` all of whose spans
        outside `CANCELLED` and `PLANNED` now sit at `STORM_PREEMPTED`, with at least one of
        them doing so, moves `IN_PROGRESS → SUSPENDED`, which in turn pushes the circuit's
        `trim_status` `ACTIVE_CYCLE → CYCLE_AT_RISK`."
        PRD §3.8: "Parent plus child therefore total exactly what the parent alone totalled
        before, so the plan's conserved `planned_unit_count` does not move at all."

        Design: Difficulty/transitive_cascade/storm_reassignment_cascades_crew_to_assignment_to_span_to_plan_to_circuit
        """
        world = setup_storm_preempted_span(units_trimmed=10, labor_hours=2,
                                           equipment_hours=1, disposal_tons=0)

        plan = read_plan(world["plan"]["id"])
        assert plan["status"] == "SUSPENDED"
        assert plan["planned_unit_count"] == 200
        assert plan["production_pct"] == pytest.approx(5.00, abs=0.001)
        assert read_circuit(world["circuit"]["id"])["trim_status"] == "CYCLE_AT_RISK"

        storm = read_storm(world["storm"]["id"])
        assert_storm_event(storm)
        assert storm["reassigned_crew_count"] == 1
        assert storm["preempted_assignment_count"] == 1


class TestDemobilizationRestoresEverything:

    def test_demobilization_cancels_the_child_and_restores_the_parent_units(self, api):
        """PRD §3.8: "Each such span's remainder child, still sitting in `PLANNED`, moves
        `PLANNED → CANCELLED`, and the child's `planned_unit_count` is added back onto the
        parent's, restoring the pre-storm value exactly."
        PRD §2.10: "The first is planned units: a plan's `planned_unit_count` is always the sum
        of `planned_unit_count` over its spans whose `execution_status` is anything other than
        `CANCELLED`, and the storm split that carves a remainder child out of a preempted
        parent is engineered to leave that sum unchanged."

        Design: Difficulty/compensating_invariant/storm_split_then_demobilize_conserves_plan_planned_unit_count
        """
        world = setup_storm_preempted_span(units_trimmed=10, labor_hours=2,
                                           equipment_hours=1, disposal_tons=0)
        assert read_plan(world["plan"]["id"])["planned_unit_count"] == 200

        validate_success(api.demobilize_storm_event(world["storm"]["id"], FORESTER), 200)

        assert read_span(world["child"]["id"])["execution_status"] == "CANCELLED"
        parent = read_span(world["span"]["id"])
        assert parent["planned_unit_count"] == 200
        assert parent["execution_status"] == "RELEASED"
        assert read_plan(world["plan"]["id"])["planned_unit_count"] == 200

    def test_demobilization_frees_the_crew_and_lifts_the_plan_and_circuit(self, api):
        """PRD §3.8: "Every booking carrying that event's `preempted_by_storm_event_id` moves
        `PREEMPTED → RELEASED`, and every crew in `STORM_DEPLOYED` attributed to the event
        returns to `AVAILABLE`."
        PRD §3.8: "The plan's `planned_unit_count` and `production_pct` are recomputed, and
        once no span of the plan remains in `STORM_PREEMPTED` a plan sitting in `SUSPENDED`
        moves back `SUSPENDED → IN_PROGRESS`, which returns the circuit's `trim_status`
        `CYCLE_AT_RISK → ACTIVE_CYCLE`."

        Design: Difficulty/compensating_invariant/storm_split_then_demobilize_conserves_plan_planned_unit_count
        """
        world = setup_storm_preempted_span(units_trimmed=10, labor_hours=2,
                                           equipment_hours=1, disposal_tons=0)

        storm = validate_success(
            api.demobilize_storm_event(world["storm"]["id"], FORESTER), 200)

        assert read_booking(world["booking"]["id"])["status"] == "RELEASED"
        assert read_crew(world["crew"]["id"])["status"] == "AVAILABLE"
        assert read_plan(world["plan"]["id"])["status"] == "IN_PROGRESS"
        assert read_circuit(world["circuit"]["id"])["trim_status"] == "ACTIVE_CYCLE"
        assert storm["status"] == "DEMOBILIZING"
        assert read_storm(world["storm"]["id"])["preempted_assignment_count"] == 0


class TestStormGuards:

    def test_closing_an_active_storm_before_demobilizing_is_not_declared(self, api):
        """PRD §3.8: "Closing is the last step: a forester moves an event
        `DEMOBILIZING → CLOSED`, and the transition is permitted only when no booking still
        carries that event's `preempted_by_storm_event_id` while sitting in `PREEMPTED`."
        PRD §2.9: "10. The target resource is in a state from which the requested transition is
        declared — `ERR_INVALID_STATE` (409). This applies to every transition endpoint."

        Design: Corner/state_machines/corner_storm_close_before_demobilize_returns_invalid_state
        """
        storm = new_active_storm(event_code="STM-1", severity_level=4,
                                 affected_district="NORTH")

        resp = api.close_storm_event(storm["id"], FORESTER)

        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert resp.status_code == 409
        assert read_storm(storm["id"])["status"] == "ACTIVE"

    def test_a_storm_deployed_crew_cannot_take_a_new_booking(self, api):
        """PRD §3.4: "A crew whose `status` is `STORM_DEPLOYED` cannot take new work bookings at
        all and is rejected with `ERR_CREW_UNAVAILABLE` (HTTP 409); a crew at `AVAILABLE` or
        `ASSIGNED` may be booked, since one crew legitimately holds several non-overlapping
        bookings."
        PRD §3.4: "Two guards apply, and their relative order matters: crew availability is
        checked first, then interval conflict."

        Design: Corner/validations/corner_booking_a_storm_deployed_crew_is_rejected
        """
        world = setup_storm_preempted_span(units_trimmed=0, labor_hours=0,
                                           equipment_hours=0, disposal_tons=0)

        resp = api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": world["crew"]["id"],
            "start_at": "2026-09-10T08:00:00Z", "end_at": "2026-09-10T16:00:00Z"}, PLANNER)

        error = validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE.value)
        assert resp.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT.value
        assert read_crew(world["crew"]["id"])["status"] == "STORM_DEPLOYED"
        assert read_booking(world["booking"]["id"])["status"] == "PREEMPTED"

    def test_a_stale_crew_version_blocks_the_reassignment_entirely(self, api):
        """PRD §2.8: "A `POST /vm/storm-events/{id}/reassignments` request must carry
        `expected_crew_version`, holding the client's last observed `version` of the `Crew`
        named by `crew_id` in the body. If the crew's current `version` differs, the request is
        rejected with `ERR_STALE_CREW_VERSION` (HTTP 412)."
        PRD §3.8: "The version guard is evaluated before the storm's own eligibility rules, so a
        planner working from a stale crew record is told about the stale read rather than about
        the storm."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_crew_version_on_storm_reassignment_returns_412
        """
        world = setup_in_progress_span()
        storm = new_active_storm(event_code="STM-1", severity_level=4,
                                 affected_district="NORTH")
        version = current_crew_version(world["crew"]["id"])

        resp = api.create_storm_reassignment(storm["id"], {
            "crew_id": world["crew"]["id"], "expected_crew_version": version - 1}, PLANNER)

        validate_error(resp, ApiErrorId.ERR_STALE_CREW_VERSION.value)
        assert resp.status_code == 412
        assert read_crew(world["crew"]["id"])["status"] == "ASSIGNED"
        assert read_booking(world["booking"]["id"])["status"] == "ACTIVE"
        assert read_span(world["span"]["id"])["execution_status"] == "IN_PROGRESS"
        assert read_storm(storm["id"])["reassigned_crew_count"] == 0

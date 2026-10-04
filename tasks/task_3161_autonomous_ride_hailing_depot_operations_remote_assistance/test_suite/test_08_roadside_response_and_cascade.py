"""Roadside response: team selection, capacity, the cascade and its reversal.

A case never exists unassigned; opening one both selects and assigns a team.
Dispatching a case moves the referencing vehicle onto the shoulder, and
clearing it returns the vehicle to the depot and the team to the roster.
"""

from test_helpers import constants as c
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_TEAM_CAPACITY_EXCEEDED,
    ERR_VEHICLE_ROADSIDE_BLOCKED,
)
from test_helpers.assertions import get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    create_roadside_team,
    match_ride,
    dispatch_roadside_case,
    in_service_vehicle,
    open_roadside_case,
    read_vehicle,
    ready_ride_stack,
    set_clock,
)
from test_helpers.test_users import FLEET


class TestRoadsideCascade:
    """Dispatching blocks the vehicle; clearing releases it to the depot."""

    def test_clear_returns_the_vehicle_to_the_depot_unblocked(self, api):
        """CLEARED reverses the cascade: AT_DEPOT, unblocked, AVAILABLE again.

        PRD 3.6: "Clearing reverses the cascade. Moving a dispatched case to
        `CLEARED` returns the referencing vehicle's `status` from `ROADSIDE`
        back to `AT_DEPOT`, clears its `is_roadside_blocked` flag back to false,
        recomputes its readiness, and advances its `version`."
        PRD 3.6: "Clearing also releases the assigned team: the team returns to
        `AVAILABLE` when it has no other case in `RESPONSE_DISPATCHED`."

        Design: Difficulty/transitive_cascade/if_match_roadside_clear_cascade_to_vehicle_release
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-road-1")
        territory, vehicle = stack["territory"], stack["vehicle"]
        team = create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        dispatched = dispatch_roadside_case(api, case["id"])
        assert dispatched["status"] == c.CASE_RESPONSE_DISPATCHED

        cleared = get_success_data(api.clear_roadside_case(case["id"], headers=FLEET))
        assert cleared["status"] == c.CASE_CLEARED

        after = read_vehicle(api, vehicle["id"])
        assert after["status"] == c.VEHICLE_AT_DEPOT
        assert after["is_roadside_blocked"] is False
        assert after["service_status"] == c.SERVICE_AVAILABLE
        assert get_success_data(api.get_roadside_team(team["id"], headers=FLEET))["status"] == c.TEAM_AVAILABLE

    def test_dispatch_blocks_the_vehicle_and_recomputes_its_verdict(self, api):
        """Dispatching moves the vehicle to ROADSIDE and blocks it.

        PRD 3.6: "It also fires the cascade that matters most for fleet
        operations: the referencing vehicle's `status` moves from `IN_SERVICE`
        to `ROADSIDE`, its `is_roadside_blocked` flag becomes true, its readiness
        verdict is recomputed — which reads `DISPATCHED` while the block is in
        force — and the vehicle's `version` advances."

        Design: Difficulty/transitive_cascade/if_match_roadside_clear_cascade_to_vehicle_release
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-road-2")
        territory, vehicle = stack["territory"], stack["vehicle"]
        before = read_vehicle(api, vehicle["id"])
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        dispatch_roadside_case(api, case["id"])

        after = read_vehicle(api, vehicle["id"])
        assert after["status"] == c.VEHICLE_ROADSIDE
        assert after["is_roadside_blocked"] is True
        assert after["service_status"] == c.SERVICE_DISPATCHED
        assert after["version"] > before["version"], "the cascade advances the vehicle version"

    def test_a_blocked_vehicle_cannot_complete_its_ride(self, api):
        """The roadside block refuses the completion of a collected ride.

        PRD 3.4: "Completion closes a ride that has already collected its rider.
        Moving from `PICKED_UP` to `COMPLETED` requires that the vehicle is not
        roadside-blocked; a vehicle with `is_roadside_blocked` true blocks the
        completion with `ERR_VEHICLE_ROADSIDE_BLOCKED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/if_match_roadside_clear_cascade_to_vehicle_release
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-road-3")
        territory, vehicle = stack["territory"], stack["vehicle"]
        validate_success(
            match_ride(api, territory["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], vehicle["version"])
        )
        matched = read_vehicle(api, vehicle["id"])
        validate_success(
            api.pickup_ride(
                territory["id"], stack["ride"]["id"],
                {"dropoff_location_id": stack["pickup_location"]["id"],
                 "expected_vehicle_version": matched["version"]},
                headers=FLEET,
            )
        )
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        dispatch_roadside_case(api, case["id"])

        resp = api.complete_ride(territory["id"], stack["ride"]["id"], headers=FLEET)
        validate_error(resp, ERR_VEHICLE_ROADSIDE_BLOCKED, 409)

    def test_returning_a_cleared_vehicle_to_service_succeeds(self, api):
        """Clearing returns the vehicle to the depot, not to service.

        PRD 3.6: "Note that clearing returns the vehicle to the depot, not to
        service; it must be staged and returned to service again through the flow
        in section 3.2 before it can take riders."

        Design: Difficulty/transitive_cascade/if_match_roadside_clear_cascade_to_vehicle_release
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-road-4")
        territory, vehicle = stack["territory"], stack["vehicle"]
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        dispatch_roadside_case(api, case["id"])
        get_success_data(api.clear_roadside_case(case["id"], headers=FLEET))

        back = get_success_data(api.return_vehicle_to_service(vehicle["id"], headers=FLEET))
        assert back["status"] == c.VEHICLE_IN_SERVICE
        assert back["service_status"] == c.SERVICE_DISPATCHED


class TestTeamCapacityCap:
    """A team with two dispatched cases cannot take a third."""

    def test_third_case_for_a_full_team_is_refused(self, api):
        """The third case against a two-case team crosses the cap.

        PRD 3.6: "the number of `RoadsideCase` rows assigned to the selected team
        whose status is `RESPONSE_DISPATCHED` is counted, and if that count is
        already 2 or more, the assignment is refused with
        `ERR_TEAM_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD 3.6: "Because `ON_CASE` teams remain candidates until the cap binds,
        a team already working can still be picked; the check is on load, not on
        status."

        Design: Difficulty/boundary_precision_check/if_match_roadside_team_capacity_boundary
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cap-1")
        territory, depot = stack["territory"], stack["depot"]
        first = stack["vehicle"]
        second = in_service_vehicle(api, depot["id"], territory["id"], "VIN-CAP-2")
        third = in_service_vehicle(api, depot["id"], territory["id"], "VIN-CAP-3")
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        create_roadside_team(api, territory["id"], "T-ARTERIAL-2")

        for vehicle in (first, second):
            case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
            dispatch_roadside_case(api, case["id"])

        resp = api.open_roadside_case(
            third["id"], {"road_class": c.ROUTE_ARTERIAL}, headers=FLEET
        )
        validate_error(resp, ERR_TEAM_CAPACITY_EXCEEDED, 409)

    def test_the_capped_team_is_the_one_holding_two_dispatched_cases(self, api):
        """Ranking is by team_code, so the lowest code accumulates the load.

        PRD 3.6: "Otherwise the pool is ranked by `team_code` ascending and the
        first team is selected."

        Design: Difficulty/boundary_precision_check/if_match_roadside_team_capacity_boundary
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cap-2")
        territory, depot = stack["territory"], stack["depot"]
        first = stack["vehicle"]
        second = in_service_vehicle(api, depot["id"], territory["id"], "VIN-CAP-4")
        team_one = create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        team_two = create_roadside_team(api, territory["id"], "T-ARTERIAL-2")

        for vehicle in (first, second):
            case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
            dispatch_roadside_case(api, case["id"])

        team_one_after = get_success_data(api.get_roadside_team(team_one["id"], headers=FLEET))
        team_two_after = get_success_data(api.get_roadside_team(team_two["id"], headers=FLEET))
        assert team_one_after["status"] == c.TEAM_ON_CASE
        assert team_two_after["status"] == c.TEAM_AVAILABLE

        held = get_success_data(api.list_team_roadside_cases(team_one["id"], headers=FLEET))
        dispatched = [row for row in held if row["status"] == c.CASE_RESPONSE_DISPATCHED]
        assert len(dispatched) == 2

    def test_a_second_team_below_the_cap_accepts_the_case(self, api):
        """The cap binds only on the team that already holds two cases.

        PRD 3.6: "the number of `RoadsideCase` rows assigned to the selected team
        whose status is `RESPONSE_DISPATCHED` is counted, and if that count is
        already 2 or more, the assignment is refused with
        `ERR_TEAM_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/if_match_roadside_team_capacity_boundary
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cap-3")
        territory, depot = stack["territory"], stack["depot"]
        first = stack["vehicle"]
        second = in_service_vehicle(api, depot["id"], territory["id"], "VIN-CAP-5")
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        create_roadside_team(api, territory["id"], "T-ARTERIAL-2")

        case_one = open_roadside_case(api, first["id"], c.ROUTE_ARTERIAL)
        dispatch_roadside_case(api, case_one["id"])
        # The second case goes to the second team, which is still below the cap.
        case_two = open_roadside_case(api, second["id"], c.ROUTE_ARTERIAL)
        assert case_two["status"] == c.CASE_TEAM_ASSIGNED


class TestRoadsideCaseCancellation:
    """Cancellation is available only before dispatch."""

    def test_cancel_after_dispatch_is_refused(self, api):
        """A dispatched case must be cleared, not cancelled.

        PRD 3.6: "A case that has already been dispatched cannot be cancelled; it
        must be cleared through the response path, which is what releases the
        vehicle. The terminal statuses for a case are `CLEARED` and `CANCELLED`."

        Design: Corner/state_machines/if_match_roadside_case_cancel_after_dispatch_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cancelcase-1")
        territory, vehicle = stack["territory"], stack["vehicle"]
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        dispatch_roadside_case(api, case["id"])

        resp = api.cancel_roadside_case(case["id"], headers=FLEET)
        validate_error(resp, ERR_INVALID_STATE, 409)

        after = get_success_data(api.get_roadside_case(case["id"], headers=FLEET))
        assert after["status"] == c.CASE_RESPONSE_DISPATCHED
        vehicle_after = read_vehicle(api, vehicle["id"])
        assert vehicle_after["status"] == c.VEHICLE_ROADSIDE
        assert vehicle_after["is_roadside_blocked"] is True

    def test_cancel_before_dispatch_releases_the_team(self, api):
        """An assigned-but-undispatched case can be cancelled.

        PRD 3.6: "A case in `OPEN` or `TEAM_ASSIGNED` may be cancelled to
        `CANCELLED`, and the assigned team is released back to `AVAILABLE` on the
        same condition — that it holds no other `RESPONSE_DISPATCHED` case."

        Design: Corner/state_machines/if_match_roadside_case_cancel_after_dispatch_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cancelcase-2")
        territory, vehicle = stack["territory"], stack["vehicle"]
        team = create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, vehicle["id"], c.ROUTE_ARTERIAL)
        assert case["status"] == c.CASE_TEAM_ASSIGNED

        cancelled = get_success_data(api.cancel_roadside_case(case["id"], headers=FLEET))
        assert cancelled["status"] == c.CASE_CANCELLED
        assert get_success_data(api.get_roadside_team(team["id"], headers=FLEET))["status"] == c.TEAM_AVAILABLE
        assert read_vehicle(api, vehicle["id"])["status"] == c.VEHICLE_IN_SERVICE
"""Matching a ride: the selector, its OCC guard and the safety gate cluster.

Matching is the most heavily guarded transition in the interface. Its guards
are evaluated in a fixed order, and that order is itself part of the
specification because the code a caller receives tells it which condition to
fix first.
"""

from test_helpers import constants as c
from test_helpers.api_errors import (
    ERR_CURB_ACCESS_DENIED,
    ERR_EXCLUSION_ZONE_ACTIVE,
    ERR_NO_VEHICLE_AVAILABLE,
    ERR_ROUTE_NOT_ALLOWED,
    ERR_STALE_VERSION,
)
from test_helpers.assertions import get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    active_territory_with_depot,
    create_area_rule,
    create_curb_rule,
    create_exclusion_zone,
    create_pickup_location,
    create_ride,
    create_roadside_team,
    dispatch_roadside_case,
    in_service_vehicle,
    match_ride,
    open_roadside_case,
    read_ride,
    read_territory,
    read_vehicle,
    serve_vehicle,
    set_clock,
)
from test_helpers.test_users import FLEET, MAPPING


def _match_ready_territory(api, *, allow_route_class=None, deny_route_class=None):
    """An ACTIVE territory with one IN_SERVICE car and a permitted SAFE curb."""
    stack = active_territory_with_depot(api)
    territory, depot = stack["territory"], stack["depot"]
    vehicle = in_service_vehicle(api, depot["id"], territory["id"], "VIN-MATCH-1")
    location = create_pickup_location(api, territory["id"], curb_segment_code="CURB-A1")
    create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=True)
    if allow_route_class is not None:
        create_area_rule(api, territory["id"], allow_route_class, True)
    if deny_route_class is not None:
        create_area_rule(api, territory["id"], deny_route_class, False)
    return {
        "territory": territory,
        "depot": depot,
        "vehicle": vehicle,
        "pickup_location": location,
    }


class TestSafetyClusterOutranksState:
    """Business-safety gates mask the state-transition gate on one request."""

    def test_zone_gate_masks_the_terminal_ride_state(self, api):
        """A terminal, zone-blocked ride reports the zone error, not the state one.

        PRD 3.7: "Route-class permission is evaluated before exclusion zones: a
        request whose route class is outside the approved operational design
        domain is rejected with `ERR_ROUTE_NOT_ALLOWED` (HTTP 422) rather than
        being reported as zone-blocked."
        PRD 3.7: "Exclusion zones are evaluated next, and an `ACTIVE` zone
        covering the requested class at the reference instant is rejected with
        `ERR_EXCLUSION_ZONE_ACTIVE` (HTTP 422)."
        PRD 3.7: "State-transition validity is evaluated after all of these, and
        a transition attempted from a status that does not permit it is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."
        PRD 3.7: "The following precedence is fixed and applies wherever two of
        these checks overlap on one request; a check earlier in the list masks
        every check later in it."

        Design: Difficulty/priority_pair_validation_conflict/if_match_safety_outranks_state_on_ride_match
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_FREEWAY)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-prio-1")
        get_success_data(
            api.cancel_ride(territory["id"], ride["id"], {"credit_cents": 0}, headers=FLEET)
        )
        create_exclusion_zone(
            api, territory["id"], activate=True,
            route_class=c.ROUTE_FREEWAY, kind="CONSTRUCTION",
        )

        resp = match_ride(
            api, territory["id"], ride["id"], ready["pickup_location"]["id"],
            vehicle["version"], route_class=c.ROUTE_FREEWAY,
        )
        validate_error(resp, ERR_EXCLUSION_ZONE_ACTIVE, 422)

    def test_the_blocked_match_leaves_the_ride_untouched(self, api):
        """Neither the ride's status nor its matched vehicle is written.

        PRD 3.7: "State-transition validity is evaluated after all of these, and
        a transition attempted from a status that does not permit it is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/if_match_safety_outranks_state_on_ride_match
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_FREEWAY)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-prio-1b")
        get_success_data(
            api.cancel_ride(territory["id"], ride["id"], {"credit_cents": 0}, headers=FLEET)
        )
        create_exclusion_zone(
            api, territory["id"], activate=True,
            route_class=c.ROUTE_FREEWAY, kind="CONSTRUCTION",
        )
        match_ride(
            api, territory["id"], ride["id"], ready["pickup_location"]["id"],
            vehicle["version"], route_class=c.ROUTE_FREEWAY,
        )
        after = read_ride(api, territory["id"], ride["id"])
        assert after["status"] == c.RIDE_CANCELLED
        assert after["vehicle_id"] is None


class TestCurbGateOutranksPoolExhaustion:
    """The curb gate masks the last-evaluated pool-exhaustion check."""

    def test_forbidden_curb_masks_the_empty_candidate_pool(self, api):
        """With no candidate car and a forbidden curb, the curb error surfaces.

        PRD 2.8: "A selected curb whose access class is not permitted for the
        ride's service type is rejected with `ERR_CURB_ACCESS_DENIED`, and a curb
        that is no longer valid is rejected with `ERR_LOCATION_INVALID`; both
        carry HTTP 422."
        PRD 3.7: "Pool exhaustion is evaluated last: a match that finds no
        candidate vehicle is rejected with `ERR_NO_VEHICLE_AVAILABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/if_match_curb_safety_outranks_fiscal_on_ride_match
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        territory = stack["territory"]
        safe = create_pickup_location(api, territory["id"], curb_segment_code="CURB-A1")
        create_pickup_location(
            api, territory["id"], curb_segment_code="CURB-N1", curb_access=c.CURB_NO_STOPPING
        )
        create_curb_rule(
            api, territory["id"], curb_access=c.CURB_SAFE,
            sub_service_type=c.SUB_SERVICE_STANDARD, allowed=False,
        )
        ride = create_ride(api, territory["id"], idempotency_key="idem-prio-2")

        # The pool is empty, so no version can be authoritative; the curb gate
        # is evaluated before pool exhaustion and must surface regardless.
        resp = match_ride(
            api, territory["id"], ride["id"], safe["id"],
            read_territory(api, territory["id"])["version"],
        )
        validate_error(resp, ERR_CURB_ACCESS_DENIED, 422)

    def test_the_blocked_match_leaves_the_ride_requested(self, api):
        """The ride is not advanced when the curb gate refuses the match.

        PRD 2.8: "A selected curb whose access class is not permitted for the
        ride's service type is rejected with `ERR_CURB_ACCESS_DENIED`."

        Design: Difficulty/priority_pair_validation_conflict/if_match_curb_safety_outranks_fiscal_on_ride_match
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        territory = stack["territory"]
        safe = create_pickup_location(api, territory["id"], curb_segment_code="CURB-A2")
        create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=False)
        ride = create_ride(api, territory["id"], idempotency_key="idem-prio-2b")

        match_ride(api, territory["id"], ride["id"], safe["id"],
                   read_territory(api, territory["id"])["version"])
        after = read_ride(api, territory["id"], ride["id"])
        assert after["status"] == c.RIDE_REQUESTED
        assert after["vehicle_id"] is None


class TestExclusionZoneWindowEdges:
    """An exclusion window is closed: both edges are inside it."""

    def test_reference_at_exactly_end_utc_is_still_blocked(self, api):
        """The last instant of the window still returns ERR_EXCLUSION_ZONE_ACTIVE.

        PRD 2.7: "An exclusion zone's own window is closed and inclusive at both
        edges: it runs from `start_utc` through `end_utc` with both instants
        inside the window, so a zone whose `start_utc` equals the reference
        instant is already in force."
        PRD 2.8: "An exclusion zone whose `route_class` matches the requested
        class and whose inclusive window contains the reference instant blocks
        the same three operations with `ERR_EXCLUSION_ZONE_ACTIVE` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/if_match_exclusion_zone_closed_window_boundary
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_FREEWAY)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-zone-1")
        zone = create_exclusion_zone(
            api, territory["id"], activate=True, route_class=c.ROUTE_FREEWAY,
            kind="WEATHER", start_utc="2026-06-01T00:00:00Z", duration_seconds=86400,
        )
        assert zone["end_utc"] == "2026-06-02T00:00:00Z"

        set_clock(api, "2026-06-02T00:00:00Z")
        resp = match_ride(
            api, territory["id"], ride["id"], ready["pickup_location"]["id"],
            vehicle["version"], route_class=c.ROUTE_FREEWAY,
        )
        validate_error(resp, ERR_EXCLUSION_ZONE_ACTIVE, 422)

    def test_reference_one_second_past_end_utc_is_admitted(self, api):
        """One second beyond the window the identical match succeeds.

        PRD 2.7: "An exclusion zone's own window is closed and inclusive at both
        edges: it runs from `start_utc` through `end_utc` with both instants
        inside the window."

        Design: Difficulty/resource_temporal_overlap/if_match_exclusion_zone_closed_window_boundary
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_FREEWAY)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-zone-2")
        create_exclusion_zone(
            api, territory["id"], activate=True, route_class=c.ROUTE_FREEWAY,
            kind="WEATHER", start_utc="2026-06-01T00:00:00Z", duration_seconds=86400,
        )

        set_clock(api, "2026-06-02T00:00:01Z")
        matched = validate_success(
            match_ride(
                api, territory["id"], ride["id"], ready["pickup_location"]["id"],
                vehicle["version"], route_class=c.ROUTE_FREEWAY,
            )
        )
        assert matched["status"] == c.RIDE_MATCHED
        assert matched["vehicle_id"] == vehicle["id"]

    def test_scheduled_zone_does_not_block_a_match(self, api):
        """A zone that has not been activated does not block anything.

        PRD 2.8: "Exclusion zones are created `SCHEDULED` and become blocking
        only once activated to `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/if_match_exclusion_zone_closed_window_boundary
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_FREEWAY)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-zone-3")
        create_exclusion_zone(
            api, territory["id"], activate=False, route_class=c.ROUTE_FREEWAY,
            kind="WEATHER", start_utc="2026-06-01T00:00:00Z", duration_seconds=86400,
        )
        matched = validate_success(
            match_ride(
                api, territory["id"], ride["id"], ready["pickup_location"]["id"],
                vehicle["version"], route_class=c.ROUTE_FREEWAY,
            )
        )
        assert matched["status"] == c.RIDE_MATCHED


class TestRouteClassGating:
    """Route-class permission is evaluated before exclusion zones."""

    def test_unapproved_route_class_is_refused(self, api):
        """A class outside the approved domain is refused with the route code.

        PRD 2.8: "Gating is applied at three points: matching a ride, activating a
        deployment wave, and dispatching a wave. When a requested `route_class` is
        not permitted by an approved rule for the relevant territory, the request
        is rejected with `ERR_ROUTE_NOT_ALLOWED` (HTTP 422)."

        Design: Corner/validations/if_match_route_class_not_allowed_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api, deny_route_class=c.ROUTE_FREEWAY)
        ride = create_ride(api, ready["territory"]["id"], idempotency_key="idem-odd-1")
        resp = match_ride(
            api, ready["territory"]["id"], ride["id"], ready["pickup_location"]["id"],
            ready["vehicle"]["version"], route_class=c.ROUTE_FREEWAY,
        )
        validate_error(resp, ERR_ROUTE_NOT_ALLOWED, 422)

    def test_approved_route_class_matches(self, api):
        """The same request on a permitted class succeeds.

        PRD 2.8: "Rules are created in `DRAFT` status with `rule_version` set to
        1, and only become authoritative once a `SafetyReviewer` approves them,
        at which point they move to `APPROVED` and their `rule_version` is
        incremented by 1."

        Design: Corner/validations/if_match_route_class_not_allowed_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api, allow_route_class=c.ROUTE_ARTERIAL)
        ride = create_ride(api, ready["territory"]["id"], idempotency_key="idem-odd-2")
        matched = validate_success(
            match_ride(
                api, ready["territory"]["id"], ride["id"], ready["pickup_location"]["id"],
                ready["vehicle"]["version"], route_class=c.ROUTE_ARTERIAL,
            )
        )
        assert matched["status"] == c.RIDE_MATCHED

    def test_a_retired_rule_no_longer_confers_permission(self, api):
        """Retirement withdraws the permission the rule previously granted.

        PRD 2.8: "A rule may later be retired, moving to `RETIRED`, and retired
        rules no longer confer permission."

        Design: Corner/validations/if_match_route_class_not_allowed_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api)
        territory = ready["territory"]
        rule = create_area_rule(api, territory["id"], c.ROUTE_FREEWAY, True)
        get_success_data(
            api.retire_area_rule(
                territory["id"], rule["id"], {"reason": "ODD revision"}, headers=MAPPING
            )
        )
        ride = create_ride(api, territory["id"], idempotency_key="idem-odd-3")
        resp = match_ride(
            api, territory["id"], ride["id"], ready["pickup_location"]["id"],
            ready["vehicle"]["version"], route_class=c.ROUTE_FREEWAY,
        )
        validate_error(resp, ERR_ROUTE_NOT_ALLOWED, 422)


class TestSelectorRanking:
    """The selector ranks by battery then by creation order."""

    def test_tie_on_battery_is_broken_by_creation_order(self, api):
        """The earlier-created of two equally charged cars is selected.

        PRD 3.4: "Candidates are ranked by `battery_pct` descending with
        `created_at` ascending as the tie-break, and the first-ranked candidate
        is selected."
        PRD 3.4: "The selector searches only the ride's own territory, and only
        among vehicles whose `status` is `IN_SERVICE` and whose
        `is_roadside_blocked` is false."

        Design: Corner/cross_cutting_complexity_layers/if_match_selector_picks_highest_battery_ties_broken_by_created_at
        """
        set_clock(api)
        stack = active_territory_with_depot(
            api,
            depot_overrides={"charge_positions": 8, "cleaning_positions": 4,
                             "calib_positions": 4, "software_positions": 4},
        )
        territory, depot = stack["territory"], stack["depot"]
        first_high = in_service_vehicle(api, depot["id"], territory["id"], "VIN-SEL-1",
                                        battery_pct=95)
        second_high = in_service_vehicle(api, depot["id"], territory["id"], "VIN-SEL-2",
                                         battery_pct=95)
        low = in_service_vehicle(api, depot["id"], territory["id"], "VIN-SEL-3",
                                 battery_pct=90)
        location = create_pickup_location(api, territory["id"], curb_segment_code="CURB-S1")
        create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=True)
        ride = create_ride(api, territory["id"], idempotency_key="idem-sel-1")

        matched = validate_success(
            match_ride(api, territory["id"], ride["id"], location["id"],
                       second_high["version"])
        )
        assert matched["vehicle_id"] == first_high["id"], (
            "created_at ascending breaks the battery tie"
        )
        assert matched["vehicle_id"] != second_high["id"]
        assert read_vehicle(api, low["id"])["battery_pct"] == 90

    def test_higher_battery_wins_over_an_earlier_creation(self, api):
        """Battery is the primary key; creation order only breaks ties.

        PRD 3.4: "Candidates are ranked by `battery_pct` descending with
        `created_at` ascending as the tie-break, and the first-ranked candidate
        is selected."

        Design: Corner/cross_cutting_complexity_layers/if_match_selector_picks_highest_battery_ties_broken_by_created_at
        """
        set_clock(api)
        stack = active_territory_with_depot(
            api,
            depot_overrides={"charge_positions": 8, "cleaning_positions": 4,
                             "calib_positions": 4, "software_positions": 4},
        )
        territory, depot = stack["territory"], stack["depot"]
        lower = in_service_vehicle(api, depot["id"], territory["id"], "VIN-SEL-4",
                                   battery_pct=90)
        higher = in_service_vehicle(api, depot["id"], territory["id"], "VIN-SEL-5",
                                    battery_pct=95)
        location = create_pickup_location(api, territory["id"], curb_segment_code="CURB-S2")
        create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=True)
        ride = create_ride(api, territory["id"], idempotency_key="idem-sel-2")

        matched = validate_success(
            match_ride(api, territory["id"], ride["id"], location["id"], higher["version"])
        )
        assert matched["vehicle_id"] == higher["id"]
        assert matched["vehicle_id"] != lower["id"]


class TestSelectorPoolAndOcc:
    """The selector has no staged fallback and its guard is version-strict."""

    def test_empty_in_service_pool_is_refused(self, api):
        """A staged but AVAILABLE car cannot be dispatched to a rider.

        PRD 3.4: "The selector searches only the ride's own territory, and only
        among vehicles whose `status` is `IN_SERVICE` and whose
        `is_roadside_blocked` is false. There is deliberately no fallback to
        staged vehicles: a vehicle sitting `AT_DEPOT` cannot be dispatched to a
        rider even if its readiness verdict reads `AVAILABLE`, because a staged
        vehicle has not been returned to service."
        PRD 3.4: "Finally, the selector must find a car, and if it finds none the
        match is refused with `ERR_NO_VEHICLE_AVAILABLE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/if_match_exclusion_zone_closed_window_boundary
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        territory, depot = stack["territory"], stack["depot"]
        staged = serve_vehicle(api, depot["id"], territory["id"], "VIN-STAGED-1",
                               battery_pct=95, cleanliness_score=95)
        assert staged["status"] == c.VEHICLE_AT_DEPOT
        assert staged["service_status"] == c.SERVICE_AVAILABLE

        location = create_pickup_location(api, territory["id"], curb_segment_code="CURB-S3")
        create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=True)
        ride = create_ride(api, territory["id"], idempotency_key="idem-sel-3")

        resp = match_ride(api, territory["id"], ride["id"], location["id"],
                          staged["version"])
        validate_error(resp, ERR_NO_VEHICLE_AVAILABLE, 409)

    def test_a_roadside_blocked_car_is_not_a_candidate(self, api):
        """A blocked car drops out of the pool even though it is in service.

        PRD 3.4: "The selector searches only the ride's own territory, and only
        among vehicles whose `status` is `IN_SERVICE` and whose
        `is_roadside_blocked` is false."

        Design: Difficulty/resource_temporal_overlap/if_match_exclusion_zone_closed_window_boundary
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        territory, depot = stack["territory"], stack["depot"]
        blocked = in_service_vehicle(api, depot["id"], territory["id"], "VIN-BLOCK-1")
        create_roadside_team(api, territory["id"], "T-ARTERIAL-1")
        case = open_roadside_case(api, blocked["id"])
        dispatch_roadside_case(api, case["id"])
        blocked_after = read_vehicle(api, blocked["id"])
        assert blocked_after["status"] == c.VEHICLE_ROADSIDE
        assert blocked_after["is_roadside_blocked"] is True

        location = create_pickup_location(api, territory["id"], curb_segment_code="CURB-S4")
        create_curb_rule(api, territory["id"], curb_access=c.CURB_SAFE, allowed=True)
        ride = create_ride(api, territory["id"], idempotency_key="idem-sel-4")

        resp = match_ride(api, territory["id"], ride["id"], location["id"],
                          blocked_after["version"])
        validate_error(resp, ERR_NO_VEHICLE_AVAILABLE, 409)

    def test_stale_vehicle_version_is_refused(self, api):
        """A version one below the live one is rejected with ERR_STALE_VERSION.

        PRD 2.9: "Matching a ride to a vehicle carries `expected_vehicle_version`,
        which must equal the target vehicle's current `version`. If a depot
        service cycle completion, a roadside dispatch, or any other mutation has
        advanced the vehicle's `version` since the client last read it, the match
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/if_match_match_ride_stale_vehicle_version_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api)
        ride = create_ride(api, ready["territory"]["id"], idempotency_key="idem-occ-veh")
        resp = match_ride(
            api, ready["territory"]["id"], ride["id"], ready["pickup_location"]["id"],
            ready["vehicle"]["version"] - 1,
        )
        validate_error(resp, ERR_STALE_VERSION, 412)

    def test_a_freshly_read_version_succeeds(self, api):
        """Re-reading the vehicle and matching with the live version succeeds.

        PRD 2.9: "The client's view of the vehicle is stale and it must re-read
        before matching. Note that the field is required — omitting it is not a
        way to skip the check."

        Design: Corner/errors/if_match_match_ride_stale_vehicle_version_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-occ-veh-2")
        live = read_vehicle(api, vehicle["id"])

        matched = validate_success(
            match_ride(api, territory["id"], ride["id"],
                       ready["pickup_location"]["id"], live["version"])
        )
        assert matched["status"] == c.RIDE_MATCHED
        assert matched["vehicle_id"] == vehicle["id"]

    def test_the_stale_refusal_leaves_the_ride_and_vehicle_untouched(self, api):
        """The refusal writes neither the ride nor the vehicle's verdict.

        PRD 2.9: "Matching a ride to a vehicle carries `expected_vehicle_version`,
        which must equal the target vehicle's current `version`."

        Design: Corner/errors/if_match_match_ride_stale_vehicle_version_rejected
        """
        set_clock(api)
        ready = _match_ready_territory(api)
        territory, vehicle = ready["territory"], ready["vehicle"]
        ride = create_ride(api, territory["id"], idempotency_key="idem-occ-veh-3")
        before_vehicle = read_vehicle(api, vehicle["id"])

        match_ride(api, territory["id"], ride["id"], ready["pickup_location"]["id"],
                   vehicle["version"] - 1)

        after_ride = read_ride(api, territory["id"], ride["id"])
        assert after_ride["status"] == c.RIDE_REQUESTED
        assert after_ride["vehicle_id"] is None
        after_vehicle = read_vehicle(api, vehicle["id"])
        assert after_vehicle["service_status"] == c.SERVICE_DISPATCHED
        assert after_vehicle["version"] == before_vehicle["version"]
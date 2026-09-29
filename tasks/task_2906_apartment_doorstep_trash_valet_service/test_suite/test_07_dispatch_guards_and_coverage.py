"""Dispatch: the guard precedence, the compactor block, and coverage conservation."""

from test_helpers import (
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _dispatch_world(name, unit_count=4, service_date="2026-09-01", with_contractor=True):
    world = fixtures.build_active_community(
        name=name,
        unit_count=unit_count,
        resident_units=(),
        with_contractor=with_contractor,
    )
    world["night"] = fixtures.schedule_night(world["contract"]["id"], service_date)
    return world


# --------------------------------------------------------------------------
# Eligibility (priority 11) outranks unit-range overlap (priority 20)
# --------------------------------------------------------------------------
def _unclassified_valet_against_a_live_range(name="Sable Court"):
    """Valet A holds 101-102; valet B is cleared but never classified."""
    world = _dispatch_world(name)
    world["valet_b"] = fixtures.create_cleared_contractor(legal_name="Ben Unset")
    world["route_a"] = fixtures.assign_route(
        world["night"]["id"], world["contractor"]["id"], 101, 102
    )
    world["night"] = fixtures.read_night(world["night"]["id"])
    return world


def test_unclassified_valet_is_refused_before_the_overlap_rule_is_consulted():
    """101-104 collides with a live 101-102 range, yet eligibility answers first.

    PRD 3.5: "The valet must be `CLEARED` with a `classification` other than
    `UNCLASSIFIED`, or `ERR_CONTRACTOR_NOT_ELIGIBLE`. The community must hold no
    `ESCALATED` `JAM` incident, or `ERR_COMPACTOR_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/unclassified_contractor_on_overlapping_range_returns_not_eligible_not_overlap
    """
    world = _unclassified_valet_against_a_live_range()

    response = api_client.create_route_assignment(
        world["night"]["id"],
        factories.route_payload(
            world["valet_b"]["id"], 101, 104, world["night"]["version"]
        ),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_CONTRACTOR_NOT_ELIGIBLE.value, 409)


def test_clearing_the_background_check_alone_does_not_make_a_valet_dispatchable():
    """The refused dispatch leaves the night's coverage map and version untouched.

    PRD 3.3: "a valet may only be handed a route once they are both `CLEARED` and
    carry a `classification` other than `UNCLASSIFIED`. Clearing the background
    check is not sufficient — the classification screen must have run at least
    once — and a dispatch attempt against a contractor failing either half is
    refused with `ERR_CONTRACTOR_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/unclassified_contractor_on_overlapping_range_returns_not_eligible_not_overlap
    """
    world = _unclassified_valet_against_a_live_range()
    valet_b = fixtures.read_contractor(world["valet_b"]["id"])
    assert valet_b["onboarding_status"] == "CLEARED"
    assert valet_b["classification"] == "UNCLASSIFIED"

    api_client.create_route_assignment(
        world["night"]["id"],
        factories.route_payload(
            valet_b["id"], 101, 104, world["night"]["version"]
        ),
        VALET_OPS_MANAGER,
    )

    routes = fixtures.list_routes({"service_night_id": world["night"]["id"]})
    assert len(routes) == 1
    assert routes[0]["id"] == world["route_a"]["id"]
    assert routes[0]["status"] == "ASSIGNED"
    assert routes[0]["unit_coverage_count"] == 2
    night = fixtures.read_night(world["night"]["id"])
    assert night["assigned_unit_coverage_count"] == 2
    assert night["version"] == world["night"]["version"]


# --------------------------------------------------------------------------
# An escalated jam blocks dispatch even on an ACTIVE community
# --------------------------------------------------------------------------
def _one_escalated_jam(name="Foxglove Park"):
    world = _dispatch_world(name, service_date="2026-09-02")
    incident = fixtures.report_incident(
        world["property"]["id"], "JAM", "chute jammed on tower A"
    )
    fixtures.set_clock("2026-09-01T04:00:00Z")
    fixtures.escalate_incident(incident["id"])
    world["incident"] = incident
    return world


def test_an_escalated_jam_blocks_route_creation_on_a_community_still_active():
    """One jam is short of suspension, but the jam itself stops collection dead.

    PRD 3.7: "while any `JAM` incident of a community sits in `ESCALATED`, route
    creation and scan recording on that community are refused with
    `ERR_COMPACTOR_BLOCKED` — a block that bites even when only one jam has
    escalated and the community is therefore still `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/route_creation_blocked_by_escalated_jam_until_incident_resolved
    """
    world = _one_escalated_jam()

    response = api_client.create_route_assignment(
        world["night"]["id"],
        factories.route_payload(
            world["contractor"]["id"], 101, 104, world["night"]["version"]
        ),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_COMPACTOR_BLOCKED.value, 409)
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["status"] == "ACTIVE"
    assert prop["escalation_level"] == 1
    assert fixtures.list_routes({"service_night_id": world["night"]["id"]}) == []
    assert fixtures.read_night(world["night"]["id"])["version"] == world["night"]["version"]


def test_resolving_the_jam_reopens_dispatch_for_the_very_same_occ_token():
    """The rejected write consumed nothing, so the original night version still works.

    PRD 2.8: "Creating a route assignment on a service night requires
    `expected_service_night_version` carrying the `version` of that `ServiceNight`
    as the client last observed it. If that value does not equal the night's
    current `version`, the request is rejected with
    `ERR_STALE_SERVICE_NIGHT_VERSION` at HTTP 412 and nothing is created."

    Design: Difficulty/cross_entity_state_dependency/route_creation_blocked_by_escalated_jam_until_incident_resolved
    """
    world = _one_escalated_jam()
    api_client.create_route_assignment(
        world["night"]["id"],
        factories.route_payload(
            world["contractor"]["id"], 101, 104, world["night"]["version"]
        ),
        VALET_OPS_MANAGER,
    )

    resolved = fixtures.resolve_incident(
        world["incident"]["id"], "ram cleared and reset by the vendor"
    )
    assert resolved["status"] == "RESOLVED"
    assert fixtures.read_property(world["property"]["id"])["escalation_level"] == 0

    route = validate_success(
        api_client.create_route_assignment(
            world["night"]["id"],
            factories.route_payload(
                world["contractor"]["id"], 101, 104, world["night"]["version"]
            ),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )

    assert route["status"] == "ASSIGNED"
    assert route["unit_coverage_count"] == 4
    assert fixtures.read_night(world["night"]["id"])["assigned_unit_coverage_count"] == 4


# --------------------------------------------------------------------------
# Coverage is a full re-aggregation, so abandon-and-reissue round-trips
# --------------------------------------------------------------------------
def _one_route_and_a_spare_valet(name="Ironwood Yard"):
    world = _dispatch_world(name)
    world["valet_y"] = fixtures.create_eligible_contractor(legal_name="Yuri Route")
    world["route_x"] = fixtures.assign_route(
        world["night"]["id"], world["contractor"]["id"], 101, 104
    )
    return world


def test_abandoning_the_only_route_recomputes_the_night_coverage_down_to_zero():
    """The abandoned range leaves the conserved sum rather than lingering in it.

    PRD 3.5: "The route moves to `ABANDONED`, its own `version` increments, and
    the night's `assigned_unit_coverage_count` is recomputed and the night's
    `version` increments too — the abandoned range leaves the conserved sum."

    Design: Difficulty/compensating_invariant/night_unit_coverage_conserved_across_route_abandon_and_reissue
    """
    world = _one_route_and_a_spare_valet()
    assert world["route_x"]["unit_coverage_count"] == 4
    assert fixtures.read_night(world["night"]["id"])["assigned_unit_coverage_count"] == 4

    abandoned = fixtures.abandon_route(
        world["route_x"]["id"], world["contractor"]["id"], "valet X called out sick"
    )

    assert abandoned["status"] == "ABANDONED"
    assert fixtures.read_night(world["night"]["id"])["assigned_unit_coverage_count"] == 0


def test_reissuing_the_identical_range_to_another_valet_restores_the_count():
    """The re-issue is accepted, not an overlap, and the count round-trips to four.

    PRD 2.9: "It is always recomputed as a full re-aggregation over those rows,
    never adjusted by an incremental delta. The practical test of this rule:
    abandoning a route and re-issuing the identical unit range to another valet
    must leave `assigned_unit_coverage_count` exactly as it was before the
    abandonment."

    Design: Difficulty/compensating_invariant/night_unit_coverage_conserved_across_route_abandon_and_reissue
    """
    world = _one_route_and_a_spare_valet()
    fixtures.abandon_route(
        world["route_x"]["id"], world["contractor"]["id"], "valet X called out sick"
    )

    reissued = validate_success(
        api_client.create_route_assignment(
            world["night"]["id"],
            factories.route_payload(
                world["valet_y"]["id"],
                101,
                104,
                fixtures.night_version(world["night"]["id"]),
            ),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )

    assert reissued["status"] == "ASSIGNED"
    assert reissued["unit_coverage_count"] == 4
    assert fixtures.read_night(world["night"]["id"])["assigned_unit_coverage_count"] == 4
    rows = {
        route["id"]: route["status"]
        for route in fixtures.list_routes({"service_night_id": world["night"]["id"]})
    }
    assert rows == {
        world["route_x"]["id"]: "ABANDONED",
        reissued["id"]: "ASSIGNED",
    }

"""The cross-cutting layers: optimistic concurrency and the selector policy.

The reroute endpoint is the only place in the surface that takes an expected
version, so both sides of that guard are exercised here — the stale echo that
must change nothing, and the freshly re-read echo that must be allowed to
supersede again. The third test pins the matcher's declared tie-break order by
building a tie the first key cannot resolve.
"""
from test_helpers import (
    ERR_STALE_REQUEST_VERSION,
    PLACEMENT_COORDINATOR,
    add_teacher,
    assert_agreement_ledger,
    factories as f,
    open_request,
    read_agreement,
    read_placement,
    read_request,
    read_teacher,
    route,
    setup_bench,
    setup_ready_candidate,
    validate_error,
    validate_page,
    validate_success,
)

SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
SAME_SITE_MORE_EXPERIENCE = {"years_experience": 12, "consecutive_terms_hosted": 1}
TIED_COMMUTE_MILES = 14
PROPOSED_SUPERVISOR_POINTS = 2


def _a_routed_request_with_a_spare_mentor(api):
    """Two qualified mentors at neighbouring sites and one routed request."""
    scenario = setup_bench(api)
    add_teacher(api, scenario, **SECOND_SITE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id)
    scenario.placement = route(api, scenario.request_id)
    return scenario


def _reroute(api, scenario, version, exclude_current_teacher=False):
    """Supersede the current proposal, echoing the version the caller holds."""
    return api.reroute_request(
        scenario.request_id,
        f.reroute_payload(version,
                          exclude_current_teacher=exclude_current_teacher),
        PLACEMENT_COORDINATOR)


def test_a_stale_expected_request_version_on_reroute_changes_nothing(api):
    """The version the client held was spent by its own first reroute.

    PRD §2.10: "If `expected_request_version` does not equal the request's current
    `version`, the reroute is rejected with `ERR_STALE_REQUEST_VERSION` and HTTP
    412, and nothing is mutated."  PRD §2.4: "`version` is an integer that starts
    at `1` when the row is created and increases by exactly 1 on every mutation of
    that row."

    Design: Corner/cross-cutting complexity layers/a_stale_expected_request_version_on_reroute_returns_stale_request_version
    """
    scenario = _a_routed_request_with_a_spare_mentor(api)
    first_placement_id = scenario.placement_id
    observed_version = read_request(api, scenario.request_id)["version"]
    superseding = validate_success(_reroute(api, scenario, observed_version), 201)

    validate_error(_reroute(api, scenario, observed_version),
                   ERR_STALE_REQUEST_VERSION, 412)

    request = read_request(api, scenario.request_id)
    assert request["version"] == 3, (
        "1 at creation, 2 after the route, 3 after the first reroute")
    assert request["reroute_count"] == 1
    assert request["current_placement_id"] == superseding["id"]
    assert request["status"] == "ROUTED"
    rows, meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR, {"request_id": scenario.request_id}))
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first_placement_id]["placement_status"] == "VOIDED"
    assert by_id[first_placement_id]["voided_reason"] == "REROUTED"
    assert by_id[superseding["id"]]["placement_status"] == "PROPOSED"
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)


def test_a_reroute_echoing_the_current_version_supersedes_again(api):
    """The guard protects freshness, not novelty, so the chain may continue.

    PRD §2.10: "A reroute that echoes the current version is always well founded
    and always proceeds, even if an earlier reroute has already replaced the
    placement once."  PRD §3.5: "When `exclude_current_teacher` is true the voided
    placement's `cooperating_teacher_id` is appended to
    `excluded_cooperating_teacher_ids`; when it is false or omitted, that teacher
    may win again."

    Design: Corner/cross-cutting complexity layers/a_reroute_echoing_the_current_version_succeeds_after_an_earlier_supersede
    """
    scenario = _a_routed_request_with_a_spare_mentor(api)
    first_version = read_request(api, scenario.request_id)["version"]
    second_placement = validate_success(
        _reroute(api, scenario, first_version), 201)
    second_version = read_request(api, scenario.request_id)["version"]

    third_placement = validate_success(
        _reroute(api, scenario, second_version, exclude_current_teacher=True),
        201)

    assert third_placement["placement_status"] == "PROPOSED"
    assert third_placement["stipend_status"] == "NOT_ACCRUED"
    request = read_request(api, scenario.request_id)
    assert request["version"] == 4
    assert request["reroute_count"] == 2
    assert request["routing_round"] == 1, "a supersede never advances the round"
    assert request["current_placement_id"] == third_placement["id"]
    superseded = read_placement(api, second_placement["id"])
    assert superseded["placement_status"] == "VOIDED"
    assert superseded["voided_reason"] == "REROUTED"
    assert len(request["excluded_cooperating_teacher_ids"]) == 1, (
        "exclude_current_teacher was true on the second reroute only")
    assert request["excluded_cooperating_teacher_ids"] == [
        second_placement["cooperating_teacher_id"]]
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)


def test_the_matcher_breaks_a_commute_tie_on_teacher_experience(api):
    """Identical sites tie the first key, so the second key must decide.

    PRD §3.5: "the pairs are ordered by four successive tie-breaks: commute
    distance ascending first; then the teacher's `years_experience` descending;
    then the supervisor's travel distance ascending; then the teacher's
    `created_at` ascending; and finally the supervisor's `created_at` ascending.
    The first pair in that order wins, and the resource `id` is never a decision
    input at any level."

    Design: Corner/cross-cutting complexity layers/the_matcher_breaks_a_commute_tie_on_teacher_experience
    """
    scenario = setup_bench(api)
    veteran = add_teacher(api, scenario, **SAME_SITE_MORE_EXPERIENCE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id)

    scenario.placement = route(api, scenario.request_id)

    assert scenario.placement["cooperating_teacher_id"] == veteran["id"], (
        "12 years of experience outranks 9 at the identical commute")
    assert scenario.placement["cooperating_teacher_id"] != scenario.teacher_id
    assert scenario.placement["commute_miles"] == TIED_COMMUTE_MILES
    assert scenario.placement["supervisor_id"] == scenario.supervisor_id
    assert scenario.placement["supervisor_points"] == PROPOSED_SUPERVISOR_POINTS
    assert read_teacher(api, veteran["id"])["active_placement_count"] == 1
    assert read_teacher(api, scenario.teacher_id)["active_placement_count"] == 0

"""Depot electrical capacity and install-crew aggregate gates: the pinned
evaluation order, the inclusive headroom boundary, the overlapping-window
crew ceiling, and the create/cancel conservation of headroom."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_project_to_commissioned,
    advance_project_to_permitting,
    create_charging_project,
    create_charging_project_raw,
    make_fleet_manager_headers,
    read_depot,
    setup_customer_with_depot,
    transition_payload,
    transition_project,
    validate_error,
    validate_paginated,
    validate_success,
)

_COORDINATOR = TEST_USERS["charging_coordinator_headers"]


def _setup_two_projects_filling_depot():
    """Customer + depot (500 kW) + P1 (200 kW, SURVEY) + P2 (300 kW, SURVEY):
    the depot ends exactly fully committed."""
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=200,
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z", crew_count=2,
    )
    p2 = create_charging_project(
        customer, depot, requested_capacity_kw=300,
        install_window_start="2026-11-02T00:00:00Z",
        install_window_end="2026-11-10T00:00:00Z", crew_count=1,
    )
    return customer, depot, p1, p2


def test_pinned_evaluation_order_survey_commits_immediately(api):
    """PRD section 2.10: "A depot's `committed_capacity_kw` is the sum of
    `requested_capacity_kw` over that depot's charging projects in `SURVEY`,
    `UTILITY_REVIEW`, `PERMITTING`, or `INSTALLATION`, plus the sum of
    `commissioned_capacity_kw` over that depot's projects in `COMMISSIONED`."
    and "Because `SURVEY` already commits its requested kW, creating a project
    immediately moves `committed_capacity_kw`".

    Design: Difficulty/combinatorial_formula/depot_capacity_pinned_evaluation_order
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    create_charging_project(
        customer, depot, requested_capacity_kw=200,
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z", crew_count=2,
    )
    depot_mid = read_depot(depot["id"])
    assert depot_mid["committed_capacity_kw"] == 200, (
        "SURVEY already commits the requested kW"
    )
    p2 = create_charging_project(
        customer, depot, requested_capacity_kw=300,
        install_window_start="2026-11-02T00:00:00Z",
        install_window_end="2026-11-10T00:00:00Z", crew_count=1,
    )
    assert p2["status"] == "SURVEY", "P2 at requested 300 == headroom 300 passes inclusively"
    depot_after = read_depot(depot["id"])
    assert depot_after["committed_capacity_kw"] == 500, (
        "200 kW (P1) + 300 kW (P2) fully commit the 500 kW depot"
    )


def test_pinned_evaluation_order_commission_is_net_zero_then_full(api):
    """PRD section 2.10: "commissioning a project moves its capacity from the
    in-flight sum to the commissioned sum for a net-zero change" and "At
    creation, a project is eligible when its `requested_capacity_kw` is less
    than or equal to the headroom ... anything more is rejected with
    `ERR_DEPOT_CAPACITY_EXCEEDED`." Vehicle demand never feeds back into
    steps 1-3.

    Design: Difficulty/combinatorial_formula/depot_capacity_pinned_evaluation_order
    """
    customer, depot, p1, _p2 = _setup_two_projects_filling_depot()
    advance_project_to_commissioned(p1["id"])
    depot_mid = read_depot(depot["id"])
    assert depot_mid["committed_capacity_kw"] == 500, (
        "P1 commissioning is net-zero: 300 in-flight + 200 commissioned"
    )
    fm = make_fleet_manager_headers(customer["id"])
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_mid["version"],
        headers=fm,
        requested_capacity_kw=1,
        install_window_start="2026-12-01T00:00:00Z",
        install_window_end="2026-12-05T00:00:00Z",
        crew_count=1,
    )
    validate_error(resp, ApiErrorId.ERR_DEPOT_CAPACITY_EXCEEDED)
    depot_after = read_depot(depot["id"])
    assert depot_after["version"] == depot_mid["version"], (
        "a rejected create must not advance the depot version"
    )


def test_requested_kw_equal_headroom_is_allowed(api):
    """PRD section 2.10: "At creation, a project is eligible when its
    `requested_capacity_kw` is less than or equal to the headroom — the
    comparison is inclusive, so requesting exactly the available headroom is
    allowed".

    Design: Difficulty/boundary_precision_check/requested_kw_equal_headroom_is_allowed
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=250)
    create_charging_project(
        customer, depot, requested_capacity_kw=150,
        install_window_start="2026-10-01T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z", crew_count=1,
    )
    p2 = create_charging_project(
        customer, depot, requested_capacity_kw=100,
        install_window_start="2026-10-12T00:00:00Z",
        install_window_end="2026-10-20T00:00:00Z", crew_count=1,
    )
    assert p2["status"] == "SURVEY", "100 kW == remaining headroom 100 kW must be accepted"
    depot_after = read_depot(depot["id"])
    assert depot_after["committed_capacity_kw"] == 250


def test_one_kw_over_headroom_is_rejected(api):
    """PRD section 2.10: "the comparison is inclusive, so requesting exactly
    the available headroom is allowed; anything more is rejected with
    `ERR_DEPOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/requested_kw_equal_headroom_is_allowed
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=250)
    create_charging_project(
        customer, depot, requested_capacity_kw=150,
        install_window_start="2026-10-01T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z", crew_count=1,
    )
    create_charging_project(
        customer, depot, requested_capacity_kw=100,
        install_window_start="2026-10-12T00:00:00Z",
        install_window_end="2026-10-20T00:00:00Z", crew_count=1,
    )
    depot_now = read_depot(depot["id"])
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_now["version"],
        headers=make_fleet_manager_headers(customer["id"]),
        requested_capacity_kw=1,
        install_window_start="2026-11-01T00:00:00Z",
        install_window_end="2026-11-05T00:00:00Z",
        crew_count=1,
    )
    validate_error(resp, ApiErrorId.ERR_DEPOT_CAPACITY_EXCEEDED)


def _setup_permitting_crew3_project():
    """Depot (500 kW) + P1 (50 kW, window 2026-09-10..2026-09-20, crew 3)
    advanced to PERMITTING (the crew-regulated set)."""
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=50,
        install_window_start="2026-09-10T00:00:00Z",
        install_window_end="2026-09-20T00:00:00Z", crew_count=3,
    )
    advance_project_to_permitting(p1["id"])
    return customer, depot, p1


def test_install_crew_aggregate_boundary(api):
    """PRD section 3.2: "across closed install windows at one depot, any set
    of mutually overlapping projects in `PERMITTING` or `INSTALLATION`, the
    candidate project included, must have a combined `crew_count` of at most
    4; a breach is `ERR_INSTALL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/depot_install_crew_aggregate_conflict
    """
    customer, depot, _p1 = _setup_permitting_crew3_project()
    fm = make_fleet_manager_headers(customer["id"])
    depot_now = read_depot(depot["id"], fm)
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_now["version"],
        headers=fm,
        requested_capacity_kw=50,
        install_window_start="2026-09-15T00:00:00Z",
        install_window_end="2026-09-25T00:00:00Z",
        crew_count=2,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)
    p3 = create_charging_project(
        customer, depot, requested_capacity_kw=50,
        install_window_start="2026-09-15T00:00:00Z",
        install_window_end="2026-09-25T00:00:00Z", crew_count=1,
    )
    assert p3["status"] == "SURVEY", "aggregate crew 3 + 1 = 4 sits exactly at the ceiling"


def test_install_crew_closed_windows_touching_counts_as_overlap(api):
    """PRD section 3.2: "Both window bounds are inclusive closed bounds, and
    the end must be at or after the start or the request fails with
    `ERR_WINDOW_INVALID`." and "any set of mutually overlapping projects in
    `PERMITTING` or `INSTALLATION`, the candidate project included, must have
    a combined `crew_count` of at most 4; a breach is
    `ERR_INSTALL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/depot_install_crew_aggregate_conflict
    """
    customer, depot, _p1 = _setup_permitting_crew3_project()
    create_charging_project(
        customer, depot, requested_capacity_kw=50,
        install_window_start="2026-09-15T00:00:00Z",
        install_window_end="2026-09-25T00:00:00Z", crew_count=1,
    )
    fm = make_fleet_manager_headers(customer["id"])
    depot_now = read_depot(depot["id"], fm)
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_now["version"],
        headers=fm,
        requested_capacity_kw=50,
        install_window_start="2026-09-20T00:00:00Z",
        install_window_end="2026-09-30T00:00:00Z",
        crew_count=2,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)
    # capacity was never the blocker: 500 kW total leaves ample headroom
    assert read_depot(depot["id"], fm)["committed_capacity_kw"] == 100


def test_crew_conflict_wins_over_capacity_exceeded(api):
    """PRD section 2.8: "Every request is checked against the following
    ordered rule stack, and the first failing check wins — a request that
    would fail two checks always surfaces the earlier one." — rule 12 names
    `ERR_INSTALL_WINDOW_CONFLICT` (the overlapping-window crew ceiling) ahead
    of rule 14's `ERR_DEPOT_CAPACITY_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/temporal_constraint_beats_capacity_fiscal_on_project_create
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=120)
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=100,
        install_window_start="2026-09-10T00:00:00Z",
        install_window_end="2026-09-20T00:00:00Z", crew_count=3,
    )
    advance_project_to_permitting(p1["id"])
    fm = make_fleet_manager_headers(customer["id"])
    depot_now = read_depot(depot["id"], fm)
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_now["version"],
        headers=fm,
        requested_capacity_kw=50,
        install_window_start="2026-09-15T00:00:00Z",
        install_window_end="2026-09-25T00:00:00Z",
        crew_count=2,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)
    depot_after = read_depot(depot["id"], fm)
    assert depot_after["committed_capacity_kw"] == 100, (
        "the doubly-failing create must not move committed capacity"
    )


def test_crew_conflict_leaves_no_project_persisted(api):
    """PRD section 2.8: "the first failing check wins — a request that would
    fail two checks always surfaces the earlier one" (rule 12's
    `ERR_INSTALL_WINDOW_CONFLICT` over rule 14's
    `ERR_DEPOT_CAPACITY_EXCEEDED`).

    Design: Difficulty/priority_pair_validation_conflict/temporal_constraint_beats_capacity_fiscal_on_project_create
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=120)
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=100,
        install_window_start="2026-09-10T00:00:00Z",
        install_window_end="2026-09-20T00:00:00Z", crew_count=3,
    )
    advance_project_to_permitting(p1["id"])
    fm = make_fleet_manager_headers(customer["id"])
    depot_now = read_depot(depot["id"], fm)
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot_now["version"],
        headers=fm,
        requested_capacity_kw=50,
        install_window_start="2026-09-15T00:00:00Z",
        install_window_end="2026-09-25T00:00:00Z",
        crew_count=2,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)
    rows, _meta = validate_paginated(api.list_depot_charging_projects(depot["id"], fm))
    assert [row["id"] for row in rows] == [p1["id"]], (
        "only the original project exists after the rejected create"
    )


def test_project_create_cancel_conserves_depot_headroom(api):
    """PRD section 3.2: "Cancellation is available from `SURVEY`,
    `UTILITY_REVIEW`, `REDESIGN`, or `PERMITTING` and drops the project's
    requested kW out of the committed set."; PRD section 2.10: "cancelling a
    project removes its request from the committed set", so the depot's
    committed figure returns to exactly what it was before creation.

    Design: Difficulty/compensating_invariant/project_create_cancel_conserves_depot_headroom
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    initial_version = depot["version"]
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=200,
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z", crew_count=2,
    )
    depot_mid = read_depot(depot["id"])
    assert depot_mid["committed_capacity_kw"] == 200, "create committed the requested kW"
    cancelled = transition_project(p1["id"], "CANCELLED")
    assert cancelled["status"] == "CANCELLED"
    depot_end = read_depot(depot["id"])
    assert depot_end["committed_capacity_kw"] == 0, (
        "cancel released exactly what create committed — no drift in headroom"
    )
    assert depot_end["version"] == initial_version + 2, (
        "exactly two accepted writes (create + cancel) bumped the depot version"
    )


def test_cancelled_project_is_terminal_and_headroom_stable(api):
    """PRD section 3.2: "`COMMISSIONED` and `CANCELLED` are the two terminal
    states." and PRD section 2.8 rule 6: "any transition attempted from a
    terminal state is refused as `ERR_ALREADY_TERMINAL` (409)."

    Design: Difficulty/compensating_invariant/project_create_cancel_conserves_depot_headroom
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    p1 = create_charging_project(
        customer, depot, requested_capacity_kw=200,
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z", crew_count=2,
    )
    transition_project(p1["id"], "CANCELLED")
    resp = api.transition_charging_project(
        p1["id"], transition_payload("UTILITY_REVIEW"), _COORDINATOR
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    depot_end = read_depot(depot["id"])
    assert depot_end["committed_capacity_kw"] == 0, (
        "the terminal-state rejection must not perturb committed capacity"
    )

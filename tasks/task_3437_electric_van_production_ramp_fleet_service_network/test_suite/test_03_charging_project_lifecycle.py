"""Charging project lifecycle: initial state, the utility denial loop,
terminal lockdown, and optimistic concurrency on the parent depot."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_charging_project,
    create_charging_project_raw,
    make_fleet_manager_headers,
    read_depot,
    set_logical_clock,
    setup_customer_with_depot,
    setup_depot_with_project,
    transition_payload,
    transition_project,
    validate_error,
    validate_paginated,
    validate_success,
)

_COORDINATOR = TEST_USERS["charging_coordinator_headers"]


def _get_project(api, depot_id, project_id, headers):
    rows, _meta = validate_paginated(api.list_depot_charging_projects(depot_id, headers))
    for row in rows:
        if row["id"] == project_id:
            return row
    raise AssertionError(f"project {project_id} not listed at depot {depot_id}")


def test_charging_project_starts_in_survey(api):
    """PRD section 3.2: "A created project lands in `SURVEY` with
    `utility_denial_reason` null and `commissioned_capacity_kw` null, and
    because `SURVEY` commits capacity, the depot's `committed_capacity_kw`
    and `version` move immediately."

    Design: Corner/state_machines/charging_project_starts_in_survey
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    project = create_charging_project(
        customer,
        depot,
        requested_capacity_kw=40,
        install_window_start="2026-10-01T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        crew_count=1,
    )
    assert project["status"] == "SURVEY"
    assert project["utility_denial_reason"] is None
    assert project["commissioned_capacity_kw"] is None
    depot_after = read_depot(depot["id"])
    assert depot_after["committed_capacity_kw"] == 40, "SURVEY already commits the requested kW"


def test_charging_project_redesign_cycle_records_and_clears_reason(api):
    """PRD section 3.2: "The utility then either grants capacity —
    `UTILITY_REVIEW → PERMITTING`, ... — or denies it, sending the project
    `UTILITY_REVIEW → REDESIGN`; a denial must carry a non-empty
    `utility_denial_reason` in the request or it is rejected with
    `ERR_VALIDATION`, and the reason is recorded on the project. A redesigned
    project resubmits `REDESIGN → UTILITY_REVIEW`, which clears
    `utility_denial_reason` back to null; the loop can repeat as often as
    needed."

    Design: Corner/state_machines/charging_project_redesign_cycle_records_and_clears_reason
    """
    setup = setup_depot_with_project(requested_capacity_kw=40, advance_to="UTILITY_REVIEW")
    project = setup["project"]
    denied = transition_project(
        project["id"], "REDESIGN", utility_denial_reason="Feeder capacity exhausted until Q2"
    )
    assert denied["status"] == "REDESIGN"
    assert denied["utility_denial_reason"] == "Feeder capacity exhausted until Q2"
    resubmitted = transition_project(project["id"], "UTILITY_REVIEW")
    assert resubmitted["status"] == "UTILITY_REVIEW"
    assert resubmitted["utility_denial_reason"] is None, (
        "resubmission out of REDESIGN clears the denial reason"
    )


def test_charging_project_cancel_from_commissioned_rejected(api):
    """PRD section 3.2: "A project in `INSTALLATION` offers no cancellation —
    the attempt fails with `ERR_INVALID_STATE` — and a `COMMISSIONED` project
    is terminal, so cancelling it fails with `ERR_ALREADY_TERMINAL`."; also
    "energization closes `INSTALLATION → COMMISSIONED`, at which point
    `commissioned_capacity_kw` is set equal to `requested_capacity_kw`".

    Design: Corner/state_machines/charging_project_cancel_from_commissioned_rejected
    """
    setup = setup_depot_with_project(requested_capacity_kw=40, advance_to="COMMISSIONED")
    customer, depot, project = setup["customer"], setup["depot"], setup["project"]
    resp = api.transition_charging_project(
        project["id"], transition_payload("CANCELLED"), _COORDINATOR
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    fm = make_fleet_manager_headers(customer["id"])
    current = _get_project(api, depot["id"], project["id"], fm)
    assert current["status"] == "COMMISSIONED"
    assert current["commissioned_capacity_kw"] == 40
    depot_after = read_depot(depot["id"])
    assert depot_after["committed_capacity_kw"] == 40, (
        "a rejected cancel must not disturb committed capacity"
    )


def test_stale_depot_version_rejected_on_project_create(api):
    """PRD section 2.6: "Creating a charging project requires
    `expected_depot_version` matching the target depot's current `version`.
    The client's view of `committed_capacity_kw` — hence the headroom against
    which it sized `requested_capacity_kw` — is stale when the versions
    disagree, and the create is refused."; the rejection is
    `ERR_STALE_VERSION` (HTTP 412).

    Design: Corner/validations/stale_depot_version_rejected_on_project_create
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500)
    assert depot["version"] == 1
    create_charging_project(
        customer,
        depot,
        requested_capacity_kw=40,
        install_window_start="2026-10-01T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        crew_count=1,
    )
    fm = make_fleet_manager_headers(customer["id"])
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=depot["version"],
        headers=fm,
        requested_capacity_kw=30,
        install_window_start="2026-11-01T00:00:00Z",
        install_window_end="2026-11-08T00:00:00Z",
        crew_count=1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows, _meta = validate_paginated(api.list_depot_charging_projects(depot["id"], fm))
    assert len(rows) == 1, "the stale create must not persist a second project"


def test_depot_version_increments_on_cascaded_transition_writes(api):
    """PRD section 2.5: "`version` is an integer that increments by exactly 1
    on every successful mutation, including mutations caused by a cascade
    rather than a direct write — so when a charging project's transition bumps
    its depot, the depot's `version` advances even though no client wrote to
    the depot directly."; PRD section 3.2: "Every successful transition,
    whatever the target, increments the parent depot's `version` by 1".

    Design: Corner/complexity_layers/depot_version_increments_on_cascaded_transition_writes
    """
    set_logical_clock()
    customer, depot = setup_customer_with_depot(depot_capacity_kw=500, set_clock=False)
    fm = make_fleet_manager_headers(customer["id"])
    project = create_charging_project(
        customer,
        depot,
        requested_capacity_kw=40,
        install_window_start="2026-10-01T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        crew_count=1,
    )
    depot_v2 = read_depot(depot["id"], fm)
    assert depot_v2["version"] == 2, "project create bumps the depot 1 -> 2"
    transition_project(project["id"], "UTILITY_REVIEW")
    resp = create_charging_project_raw(
        depot["id"],
        expected_depot_version=2,
        headers=fm,
        requested_capacity_kw=30,
        install_window_start="2026-11-01T00:00:00Z",
        install_window_end="2026-11-08T00:00:00Z",
        crew_count=1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    depot_now = read_depot(depot["id"], fm)
    assert depot_now["version"] == 3, (
        "the cascaded UTILITY_REVIEW transition bumped the depot 2 -> 3; "
        "the rejected create must not bump it further"
    )

"""Evaluation cycle: ladder legality, withdrawal, window conflicts, temporal gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_cycle_to,
    create_community,
    create_community_bundle,
    create_cycle,
    get_community,
    get_cycle,
    get_success_data,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]


def test_cycle_invalid_transition_scheduled_to_scoring(api):
    """PRD §3.2: "Requesting any other target, or a legal target from an
    illegal current state, is rejected with `ERR_CYCLE_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/cycle_invalid_transition_scheduled_to_scoring
    """
    bundle = create_community_bundle(api, name="Skipper")
    cycle = create_cycle(api, bundle["community"]["id"])
    resp = api.transition_evaluation_cycle(cycle["id"], {"target_state": "SCORING"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE)
    assert get_cycle(api, cycle["id"])["status"] == "SCHEDULED"


def test_cycle_withdraw_reverts_community_and_locks_terminal(api):
    """PRD §3.2: "Withdrawal reverts the community's status: a community with
    no effective classification (its `current_class_number` still null)
    returns to `REGISTERED`" and the withdrawn cycle is terminal — "A cycle
    can also be withdrawn from any non-terminal state other than
    `EFFECTIVE`".

    Design: Corner/state_machines/cycle_withdraw_reverts_community_and_locks_terminal
    """
    bundle = create_community_bundle(api, name="Withdrawn City")
    community_id = bundle["community"]["id"]
    cycle = create_cycle(api, community_id)
    advance_cycle_to(api, cycle["id"], "DATA_COLLECTION")
    resp = api.transition_evaluation_cycle(cycle["id"], {"target_state": "WITHDRAWN"}, COORD)
    withdrawn = validate_success(resp, 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_community(api, community_id)["status"] == "REGISTERED"
    resp2 = api.transition_evaluation_cycle(cycle["id"], {"target_state": "INTAKE"}, COORD)
    validate_error(resp2, ApiErrorId.ERR_CYCLE_INVALID_STATE)


def test_existence_beats_state_on_missing_cycle(api):
    """PRD §2.11: "Existence follows: identifiers are validated in
    left-to-right order along the request, and the first identifier that
    matches nothing produces that resource type's own 404" — evaluated before
    "state-machine legality (the 409 invalid-state family)".

    Design: Corner/validations/existence_beats_state_on_missing_cycle
    """
    resp = api.transition_evaluation_cycle(
        NON_EXISTENT_UUID, {"target_state": "WITHDRAWN"}, COORD
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND)


def test_cycle_create_on_under_evaluation_community_returns_community_invalid_state(api):
    """PRD §3.2: "An `EvaluationCoordinator` opens a cycle for a community
    whose status is `REGISTERED` or `CLASSIFIED` — any other status is
    rejected with `ERR_COMMUNITY_INVALID_STATE`."

    Design: Corner/validations/cycle_create_on_under_evaluation_community_returns_community_invalid_state
    """
    community = create_community(api, name="BusyTown")
    create_cycle(api, community["id"], field_analyst_id="analyst-1")
    resp = api.create_evaluation_cycle(
        {
            "community_id": community["id"], "field_analyst_id": "analyst-2",
            "scheduled_open_date": "2027-01-01", "data_freeze_date": "2027-03-01",
        },
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_INVALID_STATE)


def test_cycle_not_open_yet_returns_error(api):
    """PRD §3.2: "From `SCHEDULED`, the cycle enters `INTAKE` once the logical
    clock date has reached `scheduled_open_date` — earlier attempts are
    rejected with `ERR_CYCLE_NOT_OPEN_YET` (HTTP 422)" — the default clock
    reads 2026-09-01, a month before this cycle opens.

    Design: Corner/validations/cycle_not_open_yet_returns_error
    """
    community = create_community(api, name="Future Cycle")
    cycle = create_cycle(
        api, community["id"], scheduled_open_date="2026-10-01", data_freeze_date="2026-12-01"
    )
    resp = api.transition_evaluation_cycle(cycle["id"], {"target_state": "INTAKE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN_YET)
    assert get_cycle(api, cycle["id"])["status"] == "SCHEDULED"


def _window_communities(api):
    wa = create_community(api, name="WinA", population=1000, area_sq_miles=10,
                          rural_area_pct=50, daily_consumption_gpm=50)
    wb = create_community(api, name="WinB", population=1000, area_sq_miles=10,
                          rural_area_pct=50, daily_consumption_gpm=50)
    wc = create_community(api, name="WinC", population=1000, area_sq_miles=10,
                          rural_area_pct=50, daily_consumption_gpm=50)
    return wa, wb, wc


def test_analyst_windows_touching_at_endpoint_do_not_conflict(api):
    """PRD §3.2: "Two such windows conflict when each one's open date falls
    before the other's freeze date; windows that merely touch at an endpoint
    do not overlap."

    Design: Difficulty/resource_temporal_overlap/analyst_cycle_windows_half_open_overlap
    """
    wa, wb, _ = _window_communities(api)
    w1 = create_cycle(
        api, wa["id"], field_analyst_id="analyst-9",
        scheduled_open_date="2026-09-01", data_freeze_date="2026-12-01",
    )
    resp = api.create_evaluation_cycle(
        {
            "community_id": wb["id"], "field_analyst_id": "analyst-9",
            "scheduled_open_date": "2026-12-01", "data_freeze_date": "2027-03-01",
        },
        COORD,
    )
    w2 = validate_success(resp, 201)
    assert w2["status"] == "SCHEDULED", "open == prior freeze is adjacency, not overlap"
    w1_after = get_cycle(api, w1["id"])
    assert w1_after["community_id"] == wa["id"]
    assert w1_after["status"] == "SCHEDULED"


def test_analyst_windows_interior_overlap_conflicts(api):
    """PRD §3.2: "A conflicting assignment is rejected with
    `ERR_CYCLE_WINDOW_CONFLICT` (HTTP 409)." — a cycle opening 2026-11-15
    lands inside the analyst's existing [2026-09-01, 2026-12-01) window.

    Design: Difficulty/resource_temporal_overlap/analyst_cycle_windows_half_open_overlap
    """
    wa, wb, wc = _window_communities(api)
    create_cycle(
        api, wa["id"], field_analyst_id="analyst-9",
        scheduled_open_date="2026-09-01", data_freeze_date="2026-12-01",
    )
    create_cycle(
        api, wb["id"], field_analyst_id="analyst-9",
        scheduled_open_date="2026-12-01", data_freeze_date="2027-03-01",
    )
    resp = api.create_evaluation_cycle(
        {
            "community_id": wc["id"], "field_analyst_id": "analyst-9",
            "scheduled_open_date": "2026-11-15", "data_freeze_date": "2027-02-01",
        },
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_CONFLICT)
    cycles = get_success_data(
        api.list_evaluation_cycles(COORD, params={"community_id": wc["id"]})
    )
    assert cycles == [], "the conflicting cycle must not be created"

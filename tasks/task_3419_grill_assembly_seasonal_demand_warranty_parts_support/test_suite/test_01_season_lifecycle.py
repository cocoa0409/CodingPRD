"""Season lifecycle: creation contract, milestone ordering, the posture ladder,
closed-interval disjointness, and the transition cascade into models and lots.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_season,
    create_season,
    create_season_payload,
    setup_closed_season,
    setup_transitioned_season,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]


def test_season_create_returns_planning_with_echoed_fields(api):
    """PRD 3.1: "A season is born in `PLANNING` posture and walks a one-directional
    ladder: `PLANNING → BUILD → ALLOCATION → IN_SEASON → CLEARANCE → TRANSITIONED → CLOSED`."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/entities/season_create_returns_initial_state_and_echoed_fields
    """
    payload = create_season_payload()
    resp = api.create_season(payload, headers=PLANNER)
    data = validate_success(resp, 201)
    assert_season(data)
    assert data["status"] == "PLANNING", f"new season must be PLANNING, got {data['status']}"
    assert data["name"] == "Grilling Season 2026"
    assert data["year"] == 2026
    assert data["demand_forecast_units"] == 1000
    for field in ("build_start", "allocation_open", "in_season_start", "clearance_start", "season_end"):
        assert data[field] == payload[field], f"Season.{field} must echo the input, got {data[field]}"


def test_season_create_rejected_when_dates_out_of_order(api):
    """PRD 3.1: "The five milestones must be strictly ascending: `build_start` before
    `allocation_open` before `in_season_start` before `clearance_start` before
    `season_end`; any other ordering is `ERR_VALIDATION`."

    Design: Corner/entities/season_create_rejected_when_dates_out_of_order
    """
    payload = create_season_payload(
        name="Broken Season",
        clearance_start="2026-02-15T00:00:00Z",  # before in_season_start 2026-03-01
    )
    resp = api.create_season(payload, headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_season_advance_rejected_when_skipping_a_state(api):
    """PRD 3.1: "A `PlannerAdmin` advances it one step at a time by naming the desired
    `target_status`, which must be exactly the next rung — asking to skip from `BUILD`
    straight to `IN_SEASON`, or to advance a `CLOSED` season, is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/season_advance_rejected_when_skipping_a_state
    """
    season = create_season()
    resp = api.advance_season(season["id"], {"target_status": "ALLOCATION"}, headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_season(season["id"], headers=PLANNER), 200)
    assert after["status"] == "PLANNING", f"rejected advance must not move the season, got {after['status']}"


def test_season_closed_terminal_lockdown_rejected(api):
    """PRD 3.1: "asking to skip from `BUILD` straight to `IN_SEASON`, or to advance a
    `CLOSED` season, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/season_closed_terminal_lockdown_rejected
    """
    bundle = setup_closed_season(units_built=5)
    season = bundle["season"]
    assert season["status"] == "CLOSED", f"full ladder walk must land CLOSED, got {season['status']}"
    resp = api.advance_season(season["id"], {"target_status": "BUILD"}, headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_season_in_season_touching_intervals_rejected(api):
    """PRD 3.1: "the closed interval from `in_season_start` through `season_end` — both
    endpoints inclusive — must be strictly disjoint from the same interval of every
    other Season, and touching endpoints count as a conflict. A new season whose
    in-season interval so much as kisses a neighbor's is rejected with
    `ERR_SEASON_OVERLAP`."

    Design: Corner/validations/season_in_season_touching_intervals_rejected
    """
    create_season()  # occupies the closed interval [2026-03-01, 2026-09-30]
    touching = create_season_payload(
        name="Early Season 2027",
        year=2027,
        build_start="2026-09-01T00:00:00Z",
        allocation_open="2026-09-10T00:00:00Z",
        in_season_start="2026-09-30T00:00:00Z",  # touches the prior season_end
        clearance_start="2027-07-01T00:00:00Z",
        season_end="2027-09-29T00:00:00Z",
        demand_forecast_units=900,
    )
    resp = api.create_season(touching, headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_SEASON_OVERLAP)
    disjoint = create_season_payload(
        name="Season 2027",
        year=2027,
        build_start="2026-09-01T00:00:00Z",
        allocation_open="2026-09-10T00:00:00Z",
        in_season_start="2026-10-01T00:00:00Z",  # strictly after the prior season_end
        clearance_start="2027-07-01T00:00:00Z",
        season_end="2027-09-29T00:00:00Z",
        demand_forecast_units=900,
    )
    resp_ok = api.create_season(disjoint, headers=PLANNER)
    data = validate_success(resp_ok, 201)
    assert data["status"] == "PLANNING"


def test_season_transition_discontinues_models_and_closes_lots(api):
    """PRD 3.2: "When a season advances `CLEARANCE → TRANSITIONED`, every model with at
    least one inventory lot in that season is discontinued in the same request —
    `discontinued_at` stamped, `support_obligation_until` computed exactly as above —
    before the season's lots and allocations are swept (§3.4)."
    PRD 3.3: "When the season finally transitions out of clearance, every lot of the
    season — whether `AVAILABLE` or `DEPLETED` — is swept to the terminal `CLOSEOUT`."

    Design: Difficulty/transitive_cascade/season_transition_discontinues_models_and_closes_lots
    """
    bundle = setup_transitioned_season(units_built=40)
    model = validate_success(api.get_model(bundle["model"]["id"], headers=PLANNER), 200)
    assert model["status"] == "DISCONTINUED", f"model with a lot in the transitioned season must be DISCONTINUED, got {model['status']}"
    # The transition ran at logical clock 2026-10-01; support obligation is +7 years (default).
    assert model["discontinued_at"] == "2026-10-01T00:00:00Z", f"discontinued_at must be the logical clock at transition, got {model['discontinued_at']}"
    assert model["support_obligation_until"] == "2033-10-01T00:00:00Z", (
        f"support_obligation_until must be discontinued_at + 7 years, got {model['support_obligation_until']}"
    )
    lots, _meta = validate_paginated(api.list_season_lots(bundle["season"]["id"], headers=PLANNER))
    assert len(lots) == 1
    assert lots[0]["status"] == "CLOSEOUT", f"lot of a transitioned season must be CLOSEOUT, got {lots[0]['status']}"

"""Delivery runs: creation gates, the day bucket and stop admission rules."""
from test_helpers import (
    ApiErrorId,
    add_stop,
    api_client,
    create_distribution_run,
    create_distribution_site,
    get_run,
    setup_delivering_run,
    setup_operational_field_kitchen,
    setup_loaded_run_with_stops,
    setup_planned_run_with_sites,
    setup_runs_on_day,
    transition_distribution_run,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
COORD = TEST_USERS["field_coordinator_headers"]
SAFETY = TEST_USERS["food_safety_officer_headers"]


def test_three_runs_on_one_day_are_accepted_and_the_fourth_is_capped(api):
    """PRD §3.7: "A single field kitchen can only dispatch so much in a day: if
    it already has 3 runs whose `planned_date` falls in the same UTC calendar
    day as the new run, creation is rejected with `ERR_KITCHEN_DAILY_RUN_CAP`."

    Design: Difficulty/resource_temporal_overlap/field_kitchen_daily_run_cap_is_an_aggregate_day_bucket
    """
    incident, field_kitchen, run, sites = setup_planned_run_with_sites(
        0,
        planned_date="2026-09-02T07:00:00Z",
        window_start="2026-09-02T07:00:00Z",
        window_end="2026-09-02T19:00:00Z",
    )
    setup_runs_on_day(incident["id"], field_kitchen["id"], 3, day="2026-09-01")

    refused = api_client.create_distribution_run(
        {
            "incident_id": incident["id"],
            "field_kitchen_id": field_kitchen["id"],
            "driver_name": "Ana Ruiz",
            "driver_phone": "+15550100",
            "driver_safety_training_completed": True,
            "vehicle_type": "VAN",
            "planned_date": "2026-09-01T18:00:00Z",
            "window_start": "2026-09-01T18:00:00Z",
            "window_end": "2026-09-01T21:00:00Z",
            "fuel_cost_cents": 1000,
            "handling_cost_cents": 500,
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_KITCHEN_DAILY_RUN_CAP)


def test_a_fourth_run_on_the_next_calendar_day_is_accepted(api):
    """PRD §3.7: "A single field kitchen can only dispatch so much in a day: if
    it already has 3 runs whose `planned_date` falls in the same UTC calendar
    day as the new run, creation is rejected with `ERR_KITCHEN_DAILY_RUN_CAP`."
    PRD §2.4: "A day bucket is the half-open UTC interval running from 00:00:00Z
    to 24:00:00Z on a single date"

    Design: Difficulty/resource_temporal_overlap/field_kitchen_daily_run_cap_is_an_aggregate_day_bucket
    """
    incident, field_kitchen, run, sites = setup_planned_run_with_sites(
        0,
        planned_date="2026-09-02T07:00:00Z",
        window_start="2026-09-02T07:00:00Z",
        window_end="2026-09-02T19:00:00Z",
    )
    setup_runs_on_day(incident["id"], field_kitchen["id"], 3, day="2026-09-01")

    next_day = create_distribution_run(
        incident["id"], field_kitchen["id"],
        planned_date="2026-09-02T06:00:00Z",
        window_start="2026-09-02T06:00:00Z",
        window_end="2026-09-02T09:00:00Z",
    )
    # the PRD fixes the three-fractional-digit form only for the four
    # system-managed properties (2.4); the echo form of a client-supplied
    # instant is not stated, so only acceptance is asserted here
    assert next_day["status"] == "PLANNED"


def test_run_cannot_leave_planned_while_its_origin_kitchen_is_only_sited(api):
    """PRD §3.7: "Leaving `PLANNED` for `LOADING` requires the origin field
    kitchen to be `OPERATIONAL` — failure yields
    `ERR_ORIGIN_KITCHEN_NOT_OPERATIONAL`"

    Design: Corner/validations/origin_kitchen_not_operational_blocks_run_loading
    """
    incident, assessment, field_kitchen = setup_operational_field_kitchen()
    # a second kitchen that is still only SITED
    still_sited = validate_success(
        api_client.create_field_kitchen(
            {
                "incident_id": incident["id"],
                "assessment_id": assessment["id"],
                "site_name": "North Field",
                "latitude": 36.91,
                "longitude": -119.60,
                "power_source": "GRID",
                "water_source": "PIPED",
                "refrigeration_hours_available": 24,
                "daily_capacity_meals": 900,
            },
            COORD,
        ),
        expected_status=201,
    )
    run = create_distribution_run(incident["id"], still_sited["id"])
    refused = api_client.transition_distribution_run(
        run["id"], {"to_state": "LOADING"}, LOGISTICS
    )
    validate_error(refused, ApiErrorId.ERR_ORIGIN_KITCHEN_NOT_OPERATIONAL)
    assert get_run(run["id"])["status"] == "PLANNED"


def test_run_creation_requires_a_briefed_driver(api):
    """PRD §2.10: "A run whose `driver_safety_training_completed` is false is
    rejected at creation and again when it attempts to leave `PLANNED`, with
    `ERR_DRIVER_SAFETY_TRAINING_REQUIRED`."

    Design: Corner/validations/driver_safety_training_required_on_run_creation
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    refused = api_client.create_distribution_run(
        {
            "incident_id": incident["id"],
            "field_kitchen_id": field_kitchen["id"],
            "driver_name": "Ana Ruiz",
            "driver_phone": "+15550100",
            "driver_safety_training_completed": False,
            "vehicle_type": "VAN",
            "planned_date": "2026-09-01T07:00:00Z",
            "window_start": "2026-09-01T07:00:00Z",
            "window_end": "2026-09-01T19:00:00Z",
            "fuel_cost_cents": 6000,
            "handling_cost_cents": 4000,
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_DRIVER_SAFETY_TRAINING_REQUIRED)

    accepted = create_distribution_run(incident["id"], field_kitchen["id"])
    assert accepted["status"] == "PLANNED"


def test_stop_admission_rejects_a_duplicate_sequence(api):
    """PRD §3.7: "The `stop_sequence` must be unique among the run's stops, or
    the add is rejected with `ERR_DUPLICATE_STOP_SEQUENCE`."

    Design: Corner/validations/duplicate_stop_sequence_and_duplicate_site_rejected
    """
    incident, field_kitchen, run, sites, stops = setup_loaded_run_with_stops(
        [(10, None), (0, None)], loaded_meals=10
    )
    run = get_run(run["id"])
    refused = api_client.create_distribution_stop(
        {
            "distribution_run_id": run["id"],
            "distribution_site_id": sites[1]["id"],
            "stop_sequence": 1,
            "planned_meals": 0,
            "expected_distribution_run_version": run["version"],
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE)


def test_stop_admission_rejects_a_site_that_is_already_served(api):
    """PRD §3.7: "A receiving site may appear at most once among a run's stops,
    or the add is rejected with `ERR_DUPLICATE_STOP_SITE`."

    Design: Corner/validations/duplicate_stop_sequence_and_duplicate_site_rejected
    """
    incident, field_kitchen, run, sites, stops = setup_loaded_run_with_stops(
        [(10, None)], loaded_meals=10
    )
    run = get_run(run["id"])
    refused = api_client.create_distribution_stop(
        {
            "distribution_run_id": run["id"],
            "distribution_site_id": sites[0]["id"],
            "stop_sequence": 2,
            "planned_meals": 0,
            "expected_distribution_run_version": run["version"],
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_STOP_SITE)
    assert get_run(run["id"])["loaded_meals"] == 10


def test_stop_outcome_is_refused_while_the_run_is_not_delivering(api):
    """PRD §3.7: "Three conditions must hold: the parent run must be in
    `DELIVERING` status, or the request is rejected with
    `ERR_RUN_NOT_DELIVERING`"

    Design: Corner/validations/run_not_delivering_blocks_stop_outcome
    """
    incident, field_kitchen, run, sites, stops = setup_loaded_run_with_stops(
        [(30, None)], loaded_meals=30
    )
    stop = stops[0]

    refused = api_client.transition_distribution_stop(
        stop["id"], {"to_state": "DELIVERED", "delivered_meals": 30}, LOGISTICS
    )
    validate_error(refused, ApiErrorId.ERR_RUN_NOT_DELIVERING)
    stops, _ = validate_paginated(
        api_client.list_distribution_stops(LOGISTICS, {"distribution_run_id": run["id"]})
    )
    assert stops[0]["status"] == "PENDING"
    assert stops[0]["delivered_meals"] == 0


def test_blocked_site_is_reported_ahead_of_the_load_capacity_breach(api):
    """PRD §2.5: "When two conditions hold at once, the lower-numbered rule
    wins and its error identifier is the one returned"
    PRD §2.10: "Recording a stop against a blocked site, adding a stop for a
    blocked site, or siting a field kitchen against an assessment whose
    catchment is blocked is rejected with `ERR_SITE_ACCESS_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/site_access_safety_beats_run_capacity_constraint_on_stop_creation
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    open_site = create_distribution_site(incident["id"])
    blocked_site = create_distribution_site(
        incident["id"], site_name="Ridge Camp", site_type="COMMUNITY_CENTER",
        access_constraint="BLOCKED",
    )
    run = create_distribution_run(incident["id"], field_kitchen["id"])
    transition_distribution_run(run["id"], "LOADING", loaded_meals=10)
    add_stop(run["id"], open_site["id"], 1, 10)

    run = get_run(run["id"])
    refused = api_client.create_distribution_stop(
        {
            "distribution_run_id": run["id"],
            "distribution_site_id": blocked_site["id"],
            "stop_sequence": 2,
            "planned_meals": 10,
            "expected_distribution_run_version": run["version"],
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_SITE_ACCESS_BLOCKED)


def test_identical_load_breach_against_an_open_site_reports_the_capacity_error(api):
    """PRD §3.7: "the sum of `planned_meals` over the run's stops that are still
    `PENDING`, counted after the new stop is added, must stay at or below the
    run's `loaded_meals`, or the add is rejected with
    `ERR_RUN_LOAD_EXCEEDS_CAPACITY`"

    Design: Difficulty/priority_pair_validation_conflict/site_access_safety_beats_run_capacity_constraint_on_stop_creation
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    first_site = create_distribution_site(incident["id"])
    second_site = create_distribution_site(
        incident["id"], site_name="Mill School", site_type="SCHOOL"
    )
    run = create_distribution_run(incident["id"], field_kitchen["id"])
    transition_distribution_run(run["id"], "LOADING", loaded_meals=10)
    add_stop(run["id"], first_site["id"], 1, 10)

    run = get_run(run["id"])
    refused = api_client.create_distribution_stop(
        {
            "distribution_run_id": run["id"],
            "distribution_site_id": second_site["id"],
            "stop_sequence": 2,
            "planned_meals": 10,
            "expected_distribution_run_version": run["version"],
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_RUN_LOAD_EXCEEDS_CAPACITY)
    assert get_run(run["id"])["loaded_meals"] == 10


def test_reload_cycle_returns_the_run_to_en_route(api):
    """PRD §3.7: "A run may return to the depot for reload: `DELIVERING` back to
    `EN_ROUTE` requires that `returned_meals` is greater than 0 and that at
    least one stop of the run is still `PENDING`, and the reload cycle is
    `EN_ROUTE` to `DELIVERING` to `EN_ROUTE`."

    Design: Difficulty/non_linear_state_machine/distribution_run_reload_cycle_returns_to_en_route
    """
    incident, _, run, sites, stops = setup_delivering_run(
        [(4, None), (5, None)], loaded_meals=9
    )
    transition_distribution_stop_failed(stops[0]["id"], "ROAD_BLOCKED")

    reloaded = transition_distribution_run(run["id"], "EN_ROUTE")
    assert reloaded["status"] == "EN_ROUTE"


def test_completed_run_conserves_its_load_and_refuses_further_transitions(api):
    """PRD §3.7: "At every instant, a run's `loaded_meals` equals its
    `delivered_meals` plus its `returned_meals` plus the sum of `planned_meals`
    over its stops that are still `PENDING`"
    PRD §2.5: "Terminal-state guard — the entity named in the path is not in a
    terminal state. Failure yields `ERR_ENTITY_TERMINAL` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/distribution_run_reload_cycle_returns_to_en_route
    """
    incident, _, run, sites, stops = setup_delivering_run(
        [(4, None), (5, None)], loaded_meals=9
    )
    transition_distribution_stop_failed(stops[0]["id"], "ROAD_BLOCKED")
    transition_distribution_run(run["id"], "EN_ROUTE")
    transition_distribution_run(run["id"], "DELIVERING")
    deliver = api_client.transition_distribution_stop
    deliver(
        stops[1]["id"], {"to_state": "DELIVERED", "delivered_meals": 5},
        TEST_USERS["logistics_coordinator_headers"],
    )
    transition_distribution_run(run["id"], "COMPLETED")

    completed = get_run(run["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["loaded_meals"] == 9
    assert completed["delivered_meals"] == 5
    assert completed["returned_meals"] == 4

    refused = api_client.transition_distribution_run(
        run["id"], {"to_state": "EN_ROUTE"}, LOGISTICS
    )
    validate_error(refused, ApiErrorId.ERR_ENTITY_TERMINAL)


def transition_distribution_stop_failed(stop_id, reason):
    """Local helper: fail a pending stop as the logistics coordinator."""
    return validate_success(
        api_client.transition_distribution_stop(
            stop_id, {"to_state": "FAILED", "failure_reason": reason}, LOGISTICS
        )
    )

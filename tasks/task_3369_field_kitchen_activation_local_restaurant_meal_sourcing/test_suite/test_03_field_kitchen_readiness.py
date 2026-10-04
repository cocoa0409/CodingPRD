"""Field-kitchen siting, food-safety scoring and the clearance gates."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assessment,
    create_field_kitchen,
    get_field_kitchen_row,
    inspect_field_kitchen,
    setup_active_incident,
    setup_operational_field_kitchen,
    transition_field_kitchen,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

COORD = TEST_USERS["field_coordinator_headers"]
SAFETY = TEST_USERS["food_safety_officer_headers"]


def _utilities_pending_kitchen(**overrides):
    incident, assessment = setup_active_incident()
    kitchen = create_field_kitchen(incident["id"], assessment["id"], **overrides)
    transition_field_kitchen(kitchen["id"], "UTILITIES_PENDING")
    return incident, assessment, kitchen


def test_capacity_penalty_applies_below_five_hundred_meals(api):
    """PRD §3.2: "Against those, a site whose `daily_capacity_meals` is under
    500 takes a 10-point capacity penalty, because a very small site is harder
    to run safely at volume."
    PRD §3.2: "The boundaries matter exactly as stated: 12 hours earns the full
    cold-chain points and 11 does not, 6 hours earns the partial points and 5
    does not, and a capacity of 500 escapes the penalty while 499 does not."

    Design: Difficulty/combinatorial_formula/field_kitchen_readiness_three_input_nonlinear
    """
    _, _, kitchen = _utilities_pending_kitchen()
    scored = inspect_field_kitchen(
        kitchen["id"],
        power_source="GENERATOR",
        water_source="TRUCKED",
        refrigeration_hours_available=6,
        daily_capacity_meals=499,
    )
    # GENERATOR 30 + TRUCKED 25 + cold(6h) 15 - capacity penalty 10
    assert scored["food_safety_score"] == 60

    blocked = api_client.transition_field_kitchen(
        kitchen["id"], {"to_state": "FOOD_SAFETY_CLEARED"}, SAFETY
    )
    validate_error(blocked, ApiErrorId.ERR_FOOD_SAFETY_SCORE_TOO_LOW)
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "UTILITIES_PENDING"


def test_capacity_of_five_hundred_clears_at_exactly_seventy(api):
    """PRD §3.2: "a capacity of 500 escapes the penalty while 499 does not."
    PRD §3.2: "Moving from `UTILITIES_PENDING` to `FOOD_SAFETY_CLEARED`
    requires that `power_source` is not `NONE` and `water_source` is not
    `NONE`, and that `food_safety_score` is at least 70."

    Design: Difficulty/combinatorial_formula/field_kitchen_readiness_three_input_nonlinear
    """
    _, _, kitchen = _utilities_pending_kitchen()
    scored = inspect_field_kitchen(
        kitchen["id"],
        power_source="GENERATOR",
        water_source="TRUCKED",
        refrigeration_hours_available=6,
        daily_capacity_meals=500,
    )
    assert scored["food_safety_score"] == 70

    cleared = transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)
    assert cleared["site_status"] == "FOOD_SAFETY_CLEARED"

    full = inspect_field_kitchen(
        kitchen["id"],
        power_source="GENERATOR",
        water_source="TRUCKED",
        refrigeration_hours_available=12,
        daily_capacity_meals=500,
    )
    assert full["food_safety_score"] == 80


def test_cold_chain_term_steps_at_exactly_twelve_hours(api):
    """PRD §3.2: "Cold chain contributes 25 points when
    `refrigeration_hours_available` is at least 12, 15 points when it is at
    least 6 but under 12, and 0 otherwise."

    Design: Difficulty/boundary_precision_check/food_safety_gate_at_exactly_seventy_and_refrigeration_step_at_twelve
    """
    _, _, kitchen = _utilities_pending_kitchen(
        power_source="SOLAR", water_source="PIPED", daily_capacity_meals=800
    )
    at_five = inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="PIPED",
        refrigeration_hours_available=5,
        daily_capacity_meals=800,
    )
    assert at_five["food_safety_score"] == 55

    at_eleven = inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="PIPED",
        refrigeration_hours_available=11,
        daily_capacity_meals=800,
    )
    assert at_eleven["food_safety_score"] == 70

    at_twelve = inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="PIPED",
        refrigeration_hours_available=12,
        daily_capacity_meals=800,
    )
    assert at_twelve["food_safety_score"] == 80


def test_clearance_gate_is_inclusive_at_seventy(api):
    """PRD §3.2: "a site with utilities but a score of 69 is reported as
    `ERR_FOOD_SAFETY_SCORE_TOO_LOW`. Both are refusals at HTTP 422."
    PRD §2.10: "Once utilities are present, `food_safety_score` must be at
    least 70 or the transition is rejected with
    `ERR_FOOD_SAFETY_SCORE_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/food_safety_gate_at_exactly_seventy_and_refrigeration_step_at_twelve
    """
    _, _, kitchen = _utilities_pending_kitchen(
        power_source="SOLAR", water_source="PIPED", daily_capacity_meals=800
    )
    inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="PIPED",
        refrigeration_hours_available=5,
        daily_capacity_meals=800,
    )
    refused = api_client.transition_field_kitchen(
        kitchen["id"], {"to_state": "FOOD_SAFETY_CLEARED"}, SAFETY
    )
    validate_error(refused, ApiErrorId.ERR_FOOD_SAFETY_SCORE_TOO_LOW)

    inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="PIPED",
        refrigeration_hours_available=11,
        daily_capacity_meals=800,
    )
    cleared = transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)
    assert cleared["site_status"] == "FOOD_SAFETY_CLEARED"


def test_utility_gate_outranks_the_score_gate(api):
    """PRD §3.2: "The utility check runs first: a site with no water source is
    reported as `ERR_KITCHEN_UTILITY_MISSING` even though its score is also
    below the threshold, while a site with utilities but a score of 69 is
    reported as `ERR_FOOD_SAFETY_SCORE_TOO_LOW`."
    PRD §2.10: "the utility check is deliberately evaluated ahead of the score
    check so that a site with no potable water is reported as
    `ERR_KITCHEN_UTILITY_MISSING` rather than as a score failure."

    Design: Corner/validations/kitchen_utility_missing_blocks_clearance_ahead_of_score
    """
    _, _, kitchen = _utilities_pending_kitchen(
        site_name="Dry Creek Yard", power_source="GRID", water_source="NONE"
    )
    refused = api_client.transition_field_kitchen(
        kitchen["id"], {"to_state": "FOOD_SAFETY_CLEARED"}, SAFETY
    )
    validate_error(refused, ApiErrorId.ERR_KITCHEN_UTILITY_MISSING)
    row = get_field_kitchen_row(kitchen["id"])
    assert row["food_safety_score"] == 65
    assert row["site_status"] == "UTILITIES_PENDING"


def test_inspection_overwrites_utilities_and_rescores_an_operational_site(api):
    """PRD §3.2: "An inspection supplies `power_source`, `water_source`,
    `refrigeration_hours_available` and `daily_capacity_meals`; it overwrites
    all four on the site, stamps `last_inspection_at` with the current
    logical-clock instant, and re-runs the food-safety calculation."

    Design: Corner/endpoints/field_kitchen_inspection_action_overwrites_utilities_and_rescores
    """
    incident, _, kitchen = setup_operational_field_kitchen()
    inspected = inspect_field_kitchen(
        kitchen["id"],
        power_source="SOLAR",
        water_source="WELL",
        refrigeration_hours_available=6,
        daily_capacity_meals=400,
    )
    # SOLAR 20 + WELL 15 + cold(6h) 15 - capacity penalty 10
    assert inspected["food_safety_score"] == 40
    assert inspected["site_status"] == "OPERATIONAL"
    assert inspected["last_inspection_at"] is not None
    assert inspected["power_source"] == "SOLAR"
    assert inspected["daily_capacity_meals"] == 400


def test_field_kitchen_creation_derives_the_food_safety_score(api):
    """PRD §3.2: "The site's `food_safety_score` is computed at creation and
    recomputed on every inspection; it is an integer between 0 and 100 built
    from three positive terms and one penalty."

    Design: Corner/entities/field_kitchen_computed_food_safety_score_input_ignored
    """
    incident, assessment = setup_active_incident()
    kitchen = create_field_kitchen(incident["id"], assessment["id"])
    # GENERATOR 30 + TRUCKED 25 + cold(12h) 25 - 0
    assert kitchen["food_safety_score"] == 80
    assert kitchen["site_status"] == "SITED"


def test_repeating_the_utilities_pending_transition_is_refused(api):
    """PRD §2.5: "Transition reachability — the entity named in the path is in a
    state whose outgoing transitions include the requested `to_state`"

    Design: Corner/state_machines/field_kitchen_repeat_utilities_pending_returns_invalid_state
    """
    _, _, kitchen = _utilities_pending_kitchen()
    refused = api_client.transition_field_kitchen(
        kitchen["id"], {"to_state": "UTILITIES_PENDING"}, COORD
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "UTILITIES_PENDING"


def test_field_kitchen_list_filters_by_justifying_assessment(api):
    """PRD §4: "List field kitchens, filterable by activation and by justifying
    assessment"
    PRD §2.3: "Unless an endpoint's description in Section 4 states otherwise,
    list endpoints return resources sorted by `created_at` in ascending order."

    Design: Corner/endpoints/field_kitchen_list_filters_by_parent_assessment
    """
    incident, first_assessment = setup_active_incident()
    second_assessment = create_assessment(
        incident["id"], assessed_at="2026-09-01T07:00:00Z", population_affected=20000
    )
    first = create_field_kitchen(incident["id"], first_assessment["id"])
    second = create_field_kitchen(
        incident["id"], second_assessment["id"],
        site_name="North Field", power_source="GRID", water_source="PIPED",
        refrigeration_hours_available=24, daily_capacity_meals=900,
    )

    only_first, meta_first = validate_paginated(
        api.list_field_kitchens(COORD, {"assessment_id": first_assessment["id"]})
    )
    assert [row["id"] for row in only_first] == [first["id"]]
    assert meta_first["total_count"] == 1

    all_kitchens, meta_all = validate_paginated(
        api.list_field_kitchens(COORD, {"incident_id": incident["id"]})
    )
    assert meta_all["total_count"] == 2
    names = {row["id"]: row["site_name"] for row in all_kitchens}
    assert names[second["id"]] == "North Field"

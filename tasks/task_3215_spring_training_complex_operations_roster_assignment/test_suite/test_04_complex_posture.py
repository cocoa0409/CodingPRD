"""Complex posture: the 95 percent split, full capacity, and the closure cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_player,
    create_complex,
    create_group_with_assignment,
    create_published_group,
    create_workout_group,
    field_maintenance,
    fresh_group_version,
    get_complex,
    get_program_profile,
    get_workout_group,
    onboard_player,
    publish_group,
    set_test_clock,
    validate_error,
    validate_success,
)


def _complex_published_to(capacity_units, complex_capacity=100, **complex_overrides):
    """A complex whose single published group posts `capacity_units`."""
    complex_ = create_complex(facility_capacity_units=complex_capacity, **complex_overrides)
    create_published_group(complex_["id"], capacity_units=capacity_units,
                           group_name=f"Group {capacity_units}")
    return complex_


def _sweep(complex_id):
    return validate_success(api_client.posture_sweep(
        complex_id, TEST_USERS["complex_director_headers"]))


def test_posture_splits_exactly_at_the_95_percent_floor_and_at_capacity():
    """PRD 2.6: "it asks whether `posted_occupancy_units` has reached or exceeded
    ninety-five percent of effective capacity, that ninety-five percent figure
    being floored to a whole unit; if so the posture is `FIELD_RESTRICTED`."

    Design: Difficulty/boundary_precision_check/posture_sweep_splits_exactly_at_95_percent_and_at_full_capacity
    """
    set_test_clock()
    c94 = _complex_published_to(94)
    c95 = _complex_published_to(95)
    c99 = _complex_published_to(99)
    c100 = _complex_published_to(100)

    for complex_ in (c94, c95, c99, c100):
        _sweep(complex_["id"])

    assert get_complex(c94["id"])["posted_occupancy_units"] == 94
    assert get_complex(c94["id"])["facility_posture"] == "NORMAL"
    assert get_complex(c95["id"])["posted_occupancy_units"] == 95
    assert get_complex(c95["id"])["facility_posture"] == "FIELD_RESTRICTED"
    assert get_complex(c99["id"])["posted_occupancy_units"] == 99
    assert get_complex(c99["id"])["facility_posture"] == "FIELD_RESTRICTED"
    assert get_complex(c100["id"])["posted_occupancy_units"] == 100
    assert get_complex(c100["id"])["facility_posture"] == "CLOSED"


def test_full_capacity_does_not_flag_contention_but_exceeding_it_does():
    """PRD 2.6: "`contention_flagged` is true exactly when
    `posted_occupancy_units` exceeds the raw `facility_capacity_units`"

    Design: Difficulty/boundary_precision_check/posture_sweep_splits_exactly_at_95_percent_and_at_full_capacity
    """
    set_test_clock()
    at_capacity = _complex_published_to(100)
    over_capacity = _complex_published_to(120, complex_capacity=100)

    _sweep(at_capacity["id"])
    _sweep(over_capacity["id"])

    assert get_complex(at_capacity["id"])["contention_flagged"] is False
    assert get_complex(over_capacity["id"])["contention_flagged"] is True


def test_closing_the_field_cascades_through_assignments_groups_and_profiles():
    """PRD 3.9: "The first hop withdraws every group assignment on the complex
    whose status is `PROVISIONAL`... The second hop disbands every workout group
    that has lost its last provisional-or-active assignment... The third hop
    reaches the people: for every member player of a disbanded group, that
    player's `rehab_program_phase` is reset to `PHASE_1`"

    Design: Difficulty/transitive_cascade/complex_closure_cascade_withdraws_assignments_disbands_groups_and_resets_profiles
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=True, invitation=True)
    player = onboarded["player"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player["id"], assignment_kind="REHAB")

    validate_success(api_client.withdraw_assignment(
        assignment["id"], "CAMP_BREAKOUT", TEST_USERS["field_coordinator_headers"]))
    validate_success(field_maintenance(complex_["id"], "CLOSED"))

    closed = get_complex(complex_["id"])
    assert closed["facility_posture"] == "CLOSED"
    assert closed["field_maintenance_status"] == "CLOSED"
    assert closed["posted_occupancy_units"] == 0
    assert closed["reserved_major_units"] == 0
    assert get_workout_group(group["id"])["group_status"] == "DISBANDED"

    assignment_row = api_client.get_assignment(
        assignment["id"], TEST_USERS["field_coordinator_headers"]).json()["data"]
    assert assignment_row["assignment_status"] == "WITHDRAWN"


def test_closure_resets_member_profile_phase_and_clears_its_active_assignment():
    """PRD 3.9: "for every member player of a disbanded group, that player's
    `rehab_program_phase` is reset to `PHASE_1` from whichever of `PHASE_2` or
    `PHASE_1` it held, and the profile's `active_group_assignment_id` is
    cleared."

    Design: Difficulty/transitive_cascade/complex_closure_cascade_withdraws_assignments_disbands_groups_and_resets_profiles
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=True, invitation=True)
    player = onboarded["player"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player["id"], assignment_kind="REHAB")
    # drive the mirrored rehab phase to PHASE_2 so the reset is observable
    from test_helpers import setup_pitcher_program, log_catch_play, advance_phase
    onboarded2 = onboard_player(complex_["id"], clear=True, invitation=True)
    _group2, assignment2 = create_group_with_assignment(
        complex_["id"], onboarded2["player"]["id"], assignment_kind="REHAB",
        group_name="Pitchers Group B")
    program = validate_success(api_client.create_throw_program(
        assignment2["id"],
        {"group_assignment_id": assignment2["id"],
         "target_catch_play_throws": 40, "target_bullpen_sessions": 2},
        TEST_USERS["pitching_coordinator_headers"]), 201)
    log_catch_play(program["id"], 40)
    validate_success(advance_phase(program["id"], "ADVANCE"))
    profile = validate_success(api_client.list_player_program_profiles(
        onboarded2["player"]["id"], TEST_USERS["team_physician_headers"]))[0]
    assert profile["rehab_program_phase"] == "PHASE_2"

    # the provisional seats are released with the declared withdrawal action
    # before the field closes (the closing gate refuses a seated complex)
    validate_success(api_client.withdraw_assignment(
        assignment["id"], "CAMP_BREAKOUT", TEST_USERS["field_coordinator_headers"]))
    validate_success(api_client.withdraw_assignment(
        assignment2["id"], "CAMP_BREAKOUT", TEST_USERS["field_coordinator_headers"]))
    validate_success(field_maintenance(complex_["id"], "CLOSED"))

    reset = get_program_profile(profile["id"])
    assert reset["rehab_program_phase"] == "PHASE_1"
    assert not reset["active_group_assignment_id"]


def test_closing_the_field_is_blocked_while_a_provisional_assignment_occupies_a_seat():
    """PRD 3.9: "A provisional assignment left occupying a seat that the closure
    withdraws is refused with `ERR_MAINTENANCE_CONFLICT` (HTTP 409)."

    Design: Corner/validations/field_closure_is_blocked_while_a_provisional_assignment_occupies_a_seat
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=True, invitation=True)
    group = create_workout_group(complex_["id"])
    assignment = assign_player(group["id"], onboarded["player"]["id"])

    validate_error(
        field_maintenance(complex_["id"], "CLOSED"),
        ApiErrorId.ERR_MAINTENANCE_CONFLICT,
    )
    assert get_complex(complex_["id"])["field_maintenance_status"] == "OPEN"

    validate_success(api_client.withdraw_assignment(
        assignment["id"], "CAMP_BREAKOUT", TEST_USERS["field_coordinator_headers"]))
    validate_success(field_maintenance(complex_["id"], "CLOSED"))
    assert get_complex(complex_["id"])["facility_posture"] == "CLOSED"


def test_disbanding_an_already_disbanded_group_is_refused():
    """PRD 3.5: "A direct disband moves `group_status` to `DISBANDED` and
    withdraws every group assignment on the group whose status is `PROVISIONAL`
    or `ACTIVE`"
    PRD 3.9: "the second hop disbands every workout group that has lost its last
    provisional-or-active assignment, driving it from `FORMING` to `DISBANDED`"

    Design: Corner/state_machines/disbanding_an_already_disbanded_group_returns_invalid_state
    """
    set_test_clock()
    complex_ = create_complex()
    group = create_workout_group(complex_["id"])
    validate_success(api_client.disband_group(group["id"], TEST_USERS["complex_director_headers"]))

    validate_error(
        api_client.disband_group(group["id"], TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert get_workout_group(group["id"])["group_status"] == "DISBANDED"
    assert get_complex(complex_["id"])["posted_occupancy_units"] == 0


def test_publishing_a_group_reports_its_occupancy_immediately():
    """PRD 3.5: "Publication moves `group_status` to `PUBLISHED`, recomputes the
    complex's `posted_occupancy_units`, `reserved_major_units` and
    `reserved_minor_units`"

    Design: Corner/consistency_model/every_write_is_visible_in_the_same_response_and_the_next_read
    """
    set_test_clock()
    complex_ = create_complex()
    group = create_workout_group(complex_["id"], capacity_units=40)
    published = validate_success(api_client.publish_group(
        group["id"], fresh_group_version(group["id"]),
        TEST_USERS["complex_director_headers"]))
    assert published["group_status"] == "PUBLISHED"

    refreshed = get_complex(complex_["id"])
    assert refreshed["posted_occupancy_units"] == 40
    assert refreshed["facility_posture"] == "NORMAL"
"""Cross-cutting corner coverage: server-minted fields, derived reconciliation,
selector policy and list-filter pagination under mutation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_player,
    cleared_player,
    create_complex,
    create_published_group,
    create_group_with_assignment,
    create_workout_group,
    fresh_group_version,
    get_program_profile,
    get_workout_group,
    log_bullpen,
    log_catch_play,
    onboard_player,
    publish_group,
    register_player,
    set_test_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_client_supplied_id_and_created_at_are_not_accepted_inputs():
    """PRD 2.4: "Every entity in this specification carries an `id` that is a
    server-minted UUID, unique across the platform and carrying no type prefix"
    PRD 2.9: "Structural validity last: a missing required body field or a
    structurally invalid value ... is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/id_created_at_and_updated_at_are_server_minted_and_ignore_input
    """
    set_test_clock()
    complex_ = create_complex()
    validate_error(
        api_client.create_player(
            {"full_name": "System Fields", "idp_number": "IDP-60401", "position_code": "P",
             "acquisition_channel": "DRAFT_PICK", "home_country": "United States",
             "home_complex_id": complex_["id"], "id": "client-supplied-id",
             "created_at": "2000-01-01T00:00:00.000Z"},
            TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    created = validate_success(api_client.create_player(
        {"full_name": "System Fields", "idp_number": "IDP-60401b", "position_code": "P",
         "acquisition_channel": "DRAFT_PICK", "home_country": "United States",
         "home_complex_id": complex_["id"]},
        TEST_USERS["roster_manager_headers"]), 201)
    assert created["id"] != "client-supplied-id"
    assert created["version"] == 1
    assert created["created_at"] and created["updated_at"]


def test_derived_occupancy_aggregates_reconcile_after_an_assignment_withdrawal():
    """PRD 3.5: "Withdrawing a provisional assignment records the reason onto
    `withdrawal_reason`, moves the status to `WITHDRAWN`, recomputes the group's
    `assigned_units`, the complex's reserved aggregates, and the profile's group
    counts and `active_group_assignment_id`"

    Design: Corner/cross_cutting/derived_aggregates_recompute_after_an_assignment_withdrawal
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    major_group, _major_assignment = create_group_with_assignment(
        complex_["id"], player_id, roster_bucket="MAJOR", group_name="Pitchers Group A")
    minor_group, minor_assignment = create_group_with_assignment(
        complex_["id"], player_id, roster_bucket="MINOR", assignment_kind="REHAB",
        group_name="Rehab Group B")

    validate_success(api_client.withdraw_assignment(
        minor_assignment["id"], "REHAB_COMPLETE", TEST_USERS["field_coordinator_headers"]))

    assert get_workout_group(minor_group["id"])["assigned_units"] == 0
    profile = get_program_profile(onboarded["profile"]["id"])
    assert profile["minor_group_count"] == 0
    assert profile["major_group_count"] == 1
    # both groups remain PUBLISHED, so both posts still count toward the
    # complex's occupancy even after the minor assignment is withdrawn
    assert api_client.get_complex(
        complex_["id"], TEST_USERS["complex_director_headers"]
    ).json()["data"]["posted_occupancy_units"] == 80


def test_the_selector_points_a_profile_at_its_published_group_assignment():
    """PRD 3.5: "When several assignments of one player are simultaneously
    eligible to be the active one, the profile is pointed at the group assignment
    the selector chooses; when a withdrawal removes the assignment it was pointed
    at, the pointer is recomputed over what remains"
    PRD 3.6: "when the post-advance score reads `MET`, causes the group-assignment
    selector to pick the player's workout group and create a fresh group
    assignment"

    Design: Corner/cross_cutting/group_assignment_selector_uses_the_published_group_rules
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player_id, roster_bucket="MAJOR", assignment_kind="REHAB")
    program = validate_success(api_client.create_throw_program(
        assignment["id"],
        {"group_assignment_id": assignment["id"], "target_catch_play_throws": 40,
         "target_bullpen_sessions": 1},
        TEST_USERS["pitching_coordinator_headers"]), 201)

    log_catch_play(program["id"], 50)
    log_bullpen(program["id"])
    for _ in range(3):
        api_client.advance_phase(
            program["id"], "ADVANCE", TEST_USERS["pitching_coordinator_headers"])

    profile = get_program_profile(onboarded["profile"]["id"])
    assert profile["active_group_assignment_id"] == assignment["id"]
    assert profile["major_group_count"] == 1
    assert api_client.get_complex(
        complex_["id"], TEST_USERS["complex_director_headers"]
    ).json()["data"]["reserved_major_units"] == 1


def test_a_filtered_assignment_list_scopes_its_total_and_tracks_withdrawals():
    """PRD 2.3: "The `meta` object of a list response additionally carries all
    four pagination fields — `limit`, `offset`, `total_count` and `has_more` —
    where `total_count` is the number of records matching the filter across all
    pages"

    Design: Corner/endpoints/assignment_lists_filter_and_paginate_consistently_under_mutation
    """
    set_test_clock()
    complex_ = create_complex()
    group = create_workout_group(complex_["id"], capacity_units=10)
    assignments = []
    for i in range(3):
        player = register_player(complex_["id"], full_name=f"Filter {i}")
        assignments.append(assign_player(group["id"], player["id"]))

    page_one, meta_one = validate_paginated(api_client.list_group_assignments(
        TEST_USERS["field_coordinator_headers"],
        params={"workout_group_id": group["id"], "assignment_status": "PROVISIONAL",
                "limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert all(row["assignment_status"] == "PROVISIONAL" for row in page_one)

    validate_success(api_client.withdraw_assignment(
        assignments[0]["id"], "CAMP_BREAKOUT", TEST_USERS["field_coordinator_headers"]))

    page_two, meta_two = validate_paginated(api_client.list_group_assignments(
        TEST_USERS["field_coordinator_headers"],
        params={"workout_group_id": group["id"], "assignment_status": "PROVISIONAL",
                "limit": 2, "offset": 0}))
    assert len(page_two) == 2
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False
    assert get_workout_group(group["id"])["assigned_units"] == 2


def test_computed_posture_fields_cannot_be_supplied_by_a_client():
    """PRD 2.6: "The posture is never set directly; it is the output of a sweep."

    Design: Corner/entities/complex_posture_and_occupancy_are_computed_never_client_supplied
    """
    set_test_clock()
    validate_error(
        api_client.create_complex(
            {"name": "Computed Complex", "host_city": "Mesa", "season_split_track": "DEDICATED",
             "timezone": "America/Phoenix", "facility_capacity_units": 120,
             "posted_occupancy_units": 999, "facility_posture": "CLOSED",
             "maintenance_block_units": 77},
            TEST_USERS["platform_admin_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    computed = validate_success(api_client.create_complex(
        {"name": "Computed Complex", "host_city": "Mesa", "season_split_track": "DEDICATED",
         "timezone": "America/Phoenix", "facility_capacity_units": 120},
        TEST_USERS["platform_admin_headers"]), 201)
    assert computed["posted_occupancy_units"] == 0
    assert computed["maintenance_block_units"] == 0
    assert computed["facility_posture"] == "NORMAL"
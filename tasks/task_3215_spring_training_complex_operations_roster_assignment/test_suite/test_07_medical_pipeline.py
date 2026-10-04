"""Medical pipeline: physicals, clearance cascade and the invitation report window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cleared_player,
    create_complex,
    create_group_with_assignment,
    get_invitation,
    get_physical,
    get_player,
    issue_invitation,
    onboard_player,
    perform_passing_physical,
    register_player,
    schedule_physical,
    schedule_then_perform,
    set_test_clock,
    validate_error,
    validate_success,
)


def build_headers_for(player_id):
    from test_helpers import make_player_headers
    return make_player_headers(player_id)


def test_a_passing_physical_carries_the_player_into_the_cleared_band():
    """PRD 3.2: "When the result is `PASSED` or `PASSED_WITH_MODIFICATION`, the
    player's `eligibility_status` moves to `CAMP_ELIGIBLE`; when the result is
    `FAILED`, it moves to `TURNED_AWAY`."

    Design: Corner/entities/player_get_round_trips_every_stored_field
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False)
    player_id = onboarded["player"]["id"]

    perform_passing_physical(player_id)

    profile = validate_success(api_client.list_player_program_profiles(
        player_id, TEST_USERS["team_physician_headers"]))[0]
    assert profile["eligibility_status"] == "CAMP_ELIGIBLE"
    assert get_player(player_id)["clearance_status"] == "CAMP_CLEARED"


def _player_with_two_scheduled_physicals(complex_id, why="INF", country="United States"):
    onboarded = onboard_player(complex_id, clear=False, invitation=False,
                               **{"position_code": why, "home_country": country})
    player_id = onboarded["player"]["id"]
    first = schedule_physical(player_id, "2026-01-10T00:00:00Z")
    second = schedule_physical(player_id, "2026-01-11T00:00:00Z")
    return onboarded, first, second


def test_a_second_physical_within_the_clearance_buffer_is_refused():
    """PRD 3.2: "two performed examinations on the same player may not collide:
    the two visits are compatible only when the earlier examination's
    `performed_at` plus the examination duration falls at or before the later
    examination's `scheduled_visit_date`, or when at least a two-day clearance
    buffer separates the two visits. A collision is refused with
    `ERR_PHYSICAL_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/performed_physicals_collide_inside_the_clearance_buffer
    """
    set_test_clock("2026-02-01T00:00:00Z")
    complex_ = create_complex()
    onboarded, first, second = _player_with_two_scheduled_physicals(complex_["id"])

    validate_success(api_client.perform_physical(
        first["id"], "PASSED", TEST_USERS["team_physician_headers"]))
    validate_error(
        api_client.perform_physical(
            second["id"], "PASSED", TEST_USERS["team_physician_headers"]),
        ApiErrorId.ERR_PHYSICAL_DOUBLE_BOOKED,
    )
    assert get_physical(first["id"])["status"] == "PERFORMED"
    assert get_physical(second["id"])["status"] == "SCHEDULED"


def test_a_second_physical_after_a_full_two_day_buffer_is_performed():
    """PRD 3.2: "the two visits are compatible only when ... at least a two-day
    clearance buffer separates the two visits"

    Design: Difficulty/resource_temporal_overlap/performed_physicals_collide_inside_the_clearance_buffer
    """
    set_test_clock("2026-02-01T00:00:00Z")
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False,
                               position_code="INF")
    player_id = onboarded["player"]["id"]
    first = schedule_physical(player_id, "2026-01-10T00:00:00Z")
    second = schedule_physical(player_id, "2026-01-12T00:00:00Z")

    validate_success(api_client.perform_physical(
        first["id"], "PASSED", TEST_USERS["team_physician_headers"]))
    validate_success(api_client.perform_physical(
        second["id"], "PASSED", TEST_USERS["team_physician_headers"]))

    assert get_physical(second["id"])["status"] == "PERFORMED"
    assert get_player(player_id)["clearance_status"] == "CAMP_CLEARED"


def test_a_failed_physical_turns_the_player_away_and_withdraws_assignments():
    """PRD 3.2: "When the result is `PASSED` or `PASSED_WITH_MODIFICATION`, the
    player's `eligibility_status` moves to `CAMP_ELIGIBLE`; when the result is
    `FAILED`, it moves to `TURNED_AWAY`."
    PRD 3.2: "If the player was turned away, every group assignment they hold
    with status `PROVISIONAL` or `ACTIVE` is withdrawn"

    Design: Difficulty/transitive_cascade/medical_failure_cascade_turns_away_clears_clearance_and_empties_groups
    """
    set_test_clock("2026-01-05T00:00:00Z")
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player_id, assignment_kind="ACTIVE_WORKOUT")
    set_test_clock("2026-01-05T00:00:00Z")
    validate_success(schedule_then_perform(player_id, "2026-01-06T00:00:00Z", "FAILED"))

    profile = validate_success(api_client.list_player_program_profiles(
        player_id, TEST_USERS["team_physician_headers"]))[0]
    assert profile["eligibility_status"] == "TURNED_AWAY"
    assert get_player(player_id)["clearance_status"] == "TURNED_AWAY"
    assignment_row = api_client.get_assignment(
        assignment["id"], TEST_USERS["field_coordinator_headers"]).json()["data"]
    assert assignment_row["assignment_status"] == "WITHDRAWN"


def test_a_failed_physical_leaves_the_complex_occupancy_aggregate_intact():
    """PRD 3.2: "in both branches the complex's `posted_occupancy_units`,
    `reserved_major_units` and `reserved_minor_units` are recomputed"

    Design: Difficulty/transitive_cascade/medical_failure_cascade_turns_away_clears_clearance_and_empties_groups
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player_id, capacity_units=40)
    before = api_client.get_complex(
        complex_["id"], TEST_USERS["complex_director_headers"]).json()["data"]

    set_test_clock("2026-01-05T00:00:00Z")
    validate_success(schedule_then_perform(player_id, "2026-01-06T00:00:00Z", "FAILED"))

    after = api_client.get_complex(
        complex_["id"], TEST_USERS["complex_director_headers"]).json()["data"]
    assert after["reserved_major_units"] == 0
    assert after["posted_occupancy_units"] == before["posted_occupancy_units"]


def test_a_non_domestic_physical_must_sit_five_days_before_the_report_date():
    """PRD 3.2: "For a player whose `home_country` is not the United States, the
    `scheduled_visit_date` must sit at least five days before the invitation's
    `report_current_date`; a visit scheduled closer than that is refused with
    `ERR_PHYSICAL_WINDOW_LEAD` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/physical_perform_gate_depends_on_the_invitation_report_window
    """
    set_test_clock("2026-02-01T00:00:00Z")
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False,
                               position_code="P", home_country="Dominican Republic")
    player_id = onboarded["player"]["id"]
    invitation = issue_invitation(player_id)
    assert get_invitation(invitation["id"])["report_current_date"] == "2026-01-27T00:00:00.000Z"

    inside = schedule_physical(player_id, "2026-01-10T00:00:00Z")
    late = schedule_physical(player_id, "2026-01-25T00:00:00Z")

    validate_success(api_client.perform_physical(
        inside["id"], "PASSED", TEST_USERS["team_physician_headers"]))
    assert get_physical(inside["id"])["status"] == "PERFORMED"

    validate_error(
        api_client.perform_physical(late["id"], "PASSED", TEST_USERS["team_physician_headers"]),
        ApiErrorId.ERR_PHYSICAL_WINDOW_LEAD,
    )
    assert get_physical(late["id"])["status"] == "SCHEDULED"
    # the passing examination carried the player's clearance on to CAMP_CLEARED
    assert get_player(player_id)["clearance_status"] == "CAMP_CLEARED"


def test_the_five_day_lead_is_inclusive_at_exactly_the_boundary():
    """PRD 3.2: "For a player whose `home_country` is not the United States, the
    `scheduled_visit_date` must sit at least five days before the invitation's
    `report_current_date`; a visit scheduled closer than that is refused with
    `ERR_PHYSICAL_WINDOW_LEAD` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/physical_perform_gate_depends_on_the_invitation_report_window
    """
    set_test_clock("2026-02-01T00:00:00Z")
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False,
                               position_code="P", home_country="Dominican Republic")
    player_id = onboarded["player"]["id"]
    invitation = issue_invitation(player_id)
    # report_current_date is 2026-01-27, so exactly five days before is 2026-01-22
    assert get_invitation(invitation["id"])["report_current_date"] == "2026-01-27T00:00:00.000Z"

    at_boundary = schedule_physical(player_id, "2026-01-22T00:00:00Z")
    validate_success(api_client.perform_physical(
        at_boundary["id"], "PASSED", TEST_USERS["team_physician_headers"]))
    assert get_physical(at_boundary["id"])["status"] == "PERFORMED"

    too_close = schedule_physical(player_id, "2026-01-23T00:00:00Z")
    validate_error(
        api_client.perform_physical(
            too_close["id"], "PASSED", TEST_USERS["team_physician_headers"]),
        ApiErrorId.ERR_PHYSICAL_WINDOW_LEAD,
    )
    assert get_physical(too_close["id"])["status"] == "SCHEDULED"


def test_report_date_variants_separate_pitchers_position_players_and_guests():
    """PRD 3.3: "A lead is subtracted from it: fourteen days for a player whose
    `position_code` is `P` or `C` ... and twenty-one days for a position player
    whose `position_code` is `INF`, `OF` or `DH`. A guest instructor invitation
    adds seven further days to that lead."

    Design: Corner/calculations/report_date_variants_put_pitchers_and_position_players_seven_days_apart
    """
    set_test_clock()
    complex_ = create_complex()
    catcher = register_player(complex_["id"], position_code="C")
    infielder = register_player(complex_["id"], position_code="INF")
    guest = register_player(complex_["id"], position_code="C")

    inv_c = issue_invitation(catcher["id"], invitation_kind="CAMP_INVITEE")
    inv_i = issue_invitation(infielder["id"], invitation_kind="CAMP_INVITEE")
    inv_g = issue_invitation(guest["id"], invitation_kind="GUEST_INSTRUCTOR")

    assert inv_c["report_current_date"] == "2026-01-27T00:00:00.000Z"
    assert inv_c["report_final_date"] == "2026-02-10T00:00:00.000Z"
    assert inv_i["report_current_date"] == "2026-01-20T00:00:00.000Z"
    assert inv_i["report_final_date"] == "2026-02-03T00:00:00.000Z"
    assert inv_g["report_current_date"] == "2026-01-20T00:00:00.000Z"


def test_acknowledging_an_already_arrived_invitation_is_refused():
    """PRD 3.3: "The player then acknowledges the invitation, an act reserved to
    the `Player` role and permitted only while the invitation is `ISSUED`"

    Design: Corner/state_machines/acknowledging_an_already_arrived_invitation_is_rejected
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player = onboarded["player"]
    invitation = onboarded["invitation"]
    player_headers = build_headers_for(player["id"])
    validate_success(api_client.acknowledge(invitation["id"], player_headers))
    validate_success(api_client.arrive(invitation["id"], TEST_USERS["travel_coordinator_headers"]))
    arrived = get_invitation(invitation["id"])
    assert arrived["invitation_status"] == "ARRIVED"

    validate_error(
        api_client.acknowledge(invitation["id"], player_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert get_invitation(invitation["id"])["invitation_status"] == "ARRIVED"


def test_a_player_may_only_acknowledge_their_own_invitation():
    """PRD 2.1: "The acknowledgement of a camp invitation is the one operation
    only the invited player may perform, and the check is that the acting
    `Player` entity's `id` equals the invitation's `player_id`."

    Design: Corner/rbac/a_player_may_only_acknowledge_their_own_invitation
    """
    set_test_clock()
    complex_ = create_complex()
    owner = cleared_player(complex_["id"])
    other = register_player(complex_["id"])
    invitation = owner["invitation"]

    validate_error(
        api_client.acknowledge(invitation["id"], build_headers_for(other["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert get_invitation(invitation["id"])["invitation_status"] == "ISSUED"

    validate_success(api_client.acknowledge(invitation["id"], build_headers_for(owner["player"]["id"])))
    assert get_invitation(invitation["id"])["invitation_status"] == "ACKNOWLEDGED"


def test_invitation_report_sweep_marks_only_the_stale_invitation_no_show():
    """PRD 3.3: "When an operations checkpoint of type `invitation-report-sweep`
    runs, every invitation whose logical clock is past `report_final_date` and
    whose `actual_report_date` is still empty is driven from `ISSUED` to
    `NO_SHOW`."

    Design: Corner/endpoints/invitation_report_sweep_marks_stale_invitations_no_show
    """
    set_test_clock("2026-05-01T00:00:00Z")
    complex_ = create_complex()
    stale_player = register_player(complex_["id"], position_code="INF")
    fresh_player = register_player(complex_["id"], position_code="OF")
    stale = issue_invitation(stale_player["id"])
    fresh = issue_invitation(fresh_player["id"], report_base_date="2026-07-10T00:00:00Z")

    payload = validate_success(api_client.run_ops(
        "invitation-report-sweep", TEST_USERS["platform_admin_headers"]))

    assert get_invitation(stale["id"])["invitation_status"] == "NO_SHOW"
    assert get_invitation(fresh["id"])["invitation_status"] == "ISSUED"
    assert payload["stale_invitations_expired"] >= 1
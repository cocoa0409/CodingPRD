"""Waiver routing and camp break-out logistics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cleared_player,
    create_active_agreement_with_record,
    create_complex,
    get_minor_league_assignment,
    make_actor_headers,
    onboard_player,
    register_player,
    roster_to_designated_for_assignment,
    roster_to_nri_released,
    set_test_clock,
    validate_error,
    validate_success,
)


def _record_for(player_id):
    return validate_success(api_client.list_player_roster_records(
        player_id, TEST_USERS["roster_manager_headers"]))[0]


def test_the_waiver_route_cycles_back_through_states_it_already_occupied():
    """PRD 3.10: "An outcome of `PENDING` is available only from
    `WAIVER_CLAIMED` and returns the player to `WAIVER_PENDING`, which is the
    un-record edge before finalization. An outcome of `RETURNED` is available only
    from `WAIVER_PENDING` and sends the player back to
    `DESIGNATED_FOR_ASSIGNMENT`"

    Design: Difficulty/non_linear_state_machine/waiver_claim_route_cycles_through_pending_claimed_and_returned
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_designated_for_assignment(complex_["id"])
    player_id = onboarded["player"]["id"]
    headers = TEST_USERS["roster_manager_headers"]

    pending = validate_success(api_client.request_waivers(player_id, headers))
    assert pending["current_roster_status"] == "WAIVER_PENDING"

    claimed = validate_success(api_client.record_waiver_outcome(player_id, "CLAIMED", headers))
    assert claimed["current_roster_status"] == "WAIVER_CLAIMED"

    unrecorded = validate_success(api_client.record_waiver_outcome(player_id, "PENDING", headers))
    assert unrecorded["current_roster_status"] == "WAIVER_PENDING"

    returned = validate_success(api_client.record_waiver_outcome(player_id, "RETURNED", headers))
    assert returned["current_roster_status"] == "DESIGNATED_FOR_ASSIGNMENT"


def test_the_waiver_route_can_be_reopened_with_the_decision_still_pending():
    """PRD 3.10: "Placing a player on waivers is available only from
    `DESIGNATED_FOR_ASSIGNMENT` and only when `waivers_required` is true; it
    moves the player to `WAIVER_PENDING` and records the effective claim window"

    Design: Difficulty/non_linear_state_machine/waiver_claim_route_cycles_through_pending_claimed_and_returned
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_designated_for_assignment(complex_["id"])
    player_id = onboarded["player"]["id"]
    headers = TEST_USERS["roster_manager_headers"]

    validate_success(api_client.request_waivers(player_id, headers))
    validate_success(api_client.record_waiver_outcome(player_id, "CLAIMED", headers))
    validate_success(api_client.record_waiver_outcome(player_id, "PENDING", headers))
    validate_success(api_client.record_waiver_outcome(player_id, "RETURNED", headers))

    reopened = validate_success(api_client.request_waivers(player_id, headers))
    assert reopened["current_roster_status"] == "WAIVER_PENDING"

    final = validate_success(api_client.record_waiver_outcome(player_id, "CLAIMED", headers))
    assert final["current_roster_status"] == "WAIVER_CLAIMED"
    assert final["roster_decision_status"] == "DECISION_PENDING"


def test_farm_scoped_entity_mutation_is_refused_for_a_mapped_player():
    """PRD 2.10: "While a player is mapped into an `ACTIVE` trail row, that
    player is outside the farm-scoped camp machinery: the roster-decision path,
    the finalization and void path, the active-roster selection, the
    program-profile reinstatement, and the recording of physical examination
    outcomes are all refused for that player with `ERR_FARM_ENTITY_EXCLUDED`
    (HTTP 409)."

    Design: Corner/validations/farm_scoped_entity_mutation_is_refused_for_a_mapped_player
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False)
    player_id = onboarded["player"]["id"]
    trail = validate_success(api_client.create_spring_trail(
        player_id, "AAA", TEST_USERS["minor_league_coordinator_headers"]), 201)

    validate_error(
        api_client.decide(player_id, "OPTION_ASSIGN", TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_FARM_ENTITY_EXCLUDED,
    )
    record = _record_for(player_id)
    assert record["current_roster_status"] == "NRI"
    assert record["roster_decision_status"] == "DECISION_PENDING"
    assert trail["trail_status"] == "ACTIVE"


def test_settling_an_under_funded_sponsorship_is_refused_until_it_is_funded():
    """PRD 3.7: "Settling a sponsorship requires it to be `UNSETTLED` and
    requires `received_amount_cents` to have reached `committed_amount_cents`;
    settling an under-funded commitment is refused with
    `ERR_SPONSORSHIP_NOT_FULLY_FUNDED` (HTTP 422)."

    Design: Corner/validations/settling_an_under_funded_sponsorship_is_rejected
    """
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(complex_["id"], tickets=None)
    sponsorship = validate_success(api_client.create_sponsorship(
        record["id"],
        {"host_community_record_id": record["id"], "sponsor_name": "Under Funded Sponsor",
         "sponsor_tier": "LOCAL", "committed_amount_cents": 20000},
        TEST_USERS["community_liaison_headers"]), 201)
    validate_success(api_client.contribute(
        sponsorship["id"], 5000, "CONTRIBUTE", TEST_USERS["community_liaison_headers"]))

    validate_error(
        api_client.settle_sponsorship(sponsorship["id"], TEST_USERS["community_liaison_headers"]),
        ApiErrorId.ERR_SPONSORSHIP_NOT_FULLY_FUNDED,
    )
    assert api_client.get_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]
    ).json()["data"]["reconciliation_status"] == "UNSETTLED"

    validate_success(api_client.contribute(
        sponsorship["id"], 15000, "CONTRIBUTE", TEST_USERS["community_liaison_headers"]))
    settled = validate_success(api_client.settle_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))
    assert settled["reconciliation_status"] == "SETTLED"
    assert settled["fulfillment_completed"] is True


def test_breaking_out_of_camp_moves_a_finalized_record_to_the_minor_level():
    """PRD 3.11: "It requires the record's decision status to be
    `DECISION_FINALIZED` and its current roster status to be a valid source for
    the requested level. Breaking to `AAA` is available from `NRI` and from
    `OPTIONED_MINORS`"

    Design: Corner/rbac/roster_manager_cannot_break_a_player_out_of_camp
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    # NONROSTER_RELEASE finalizes to NRI_RELEASED, which has no AAA edge; use
    # the OPTION_ASSIGN -> finalize path instead so NRI->AAA stays reachable
    validate_success(api_client.decide(
        player_id, "OPTION_ASSIGN", make_actor_headers("rm-applier", "RosterManager")))
    validate_success(api_client.finalize_decision(
        player_id, make_actor_headers("rm-checker", "RosterManager")))
    record = _record_for(player_id)
    assert record["roster_decision_status"] == "DECISION_FINALIZED"

    broken = validate_success(api_client.break_out_camp(
        record["id"], "AAA", TEST_USERS["minor_league_coordinator_headers"]))
    assert broken["current_roster_status"] == "ASSIGNED_AAA"


def test_a_settled_break_out_cannot_be_voided_by_its_own_settler():
    """PRD 3.11: "Voiding a settled break-out is the compensating action, and it
    carries the segregation-of-duties gate: the operator voiding must not be the
    operator recorded in `settlement_actor_id`, else the void is refused with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/calculations/minor_league_assignment_void_returns_the_breakout_liability_to_zero
    """
    set_test_clock()
    complex_ = create_complex()
    _agreement, _record = create_active_agreement_with_record(complex_["id"], tickets=None)
    onboarded = roster_to_nri_released(complex_["id"])
    player_id = onboarded["player"]["id"]
    ml = validate_success(api_client.create_minor_league_assignment(
        player_id,
        {"player_id": player_id, "roster_record_id": onboarded["roster"]["id"],
         "assigned_level": "AAA", "affiliate_name": "Iowa Cubs",
         "effective_datetime": "2026-03-15T00:00:00Z"},
        TEST_USERS["minor_league_coordinator_headers"]), 201)
    assert ml["travel_day_count"] == 16

    settler = make_actor_headers("ml-settler", "MinorLeagueCoordinator")
    validate_success(api_client.settle_minor_league_assignment(ml["id"], settler))
    assert get_minor_league_assignment(ml["id"])["assignment_status"] == "SETTLED"

    validate_error(
        api_client.void_breakout(ml["id"], settler),
        ApiErrorId.ERR_SOD_VIOLATION,
    )

    voider = make_actor_headers("ml-voider", "MinorLeagueCoordinator")
    voided = validate_success(api_client.void_breakout(ml["id"], voider))
    assert voided["assignment_status"] == "BREAKOUT_VOIDED"
    assert voided["break_out_liability_cents"] == 0


def test_publishing_a_group_with_an_unmet_pitcher_is_refused():
    """PRD 3.5: "no group assignment on the group may belong to a player whose
    throwing program has `requirement_status` `UNMET` — publishing a group
    containing an under-worked pitcher is refused with
    `ERR_THROW_REQUIREMENT_UNMET` (HTTP 422)."

    Design: Corner/state_machines/workout_group_create_starts_in_forming
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    from test_helpers import assign_player, create_workout_group, fresh_group_version, log_catch_play
    group = create_workout_group(complex_["id"])
    assignment = assign_player(group["id"], player_id, assignment_kind="REHAB")
    program = validate_success(api_client.create_throw_program(
        assignment["id"],
        {"group_assignment_id": assignment["id"], "target_catch_play_throws": 200,
         "target_bullpen_sessions": 2},
        TEST_USERS["pitching_coordinator_headers"]), 201)
    # a partial workload lands below the PHASE_1 band floor, so the requirement
    # reads UNMET and the group may not be published while it is a member
    log_catch_play(program["id"], 10)
    assert api_client.get_throw_program(
        program["id"], TEST_USERS["pitching_coordinator_headers"]
    ).json()["data"]["requirement_status"] == "UNMET"

    validate_error(
        api_client.publish_group(
            group["id"], fresh_group_version(group["id"]),
            TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_THROW_REQUIREMENT_UNMET,
    )
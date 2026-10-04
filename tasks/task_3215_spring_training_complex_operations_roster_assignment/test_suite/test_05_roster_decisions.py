"""Roster decisions: option eligibility, segregation of duties, break-out gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cleared_player,
    create_active_agreement_with_record,
    create_complex,
    create_group_with_assignment,
    get_player,
    make_actor_headers,
    onboard_player,
    open_roster_record,
    publish_group,
    register_player,
    roster_to_nri_released,
    roster_to_optioned_minors_finalized,
    set_test_clock,
    validate_error,
    validate_success,
)


def _record_for(player_id):
    return validate_success(api_client.list_player_roster_records(
        player_id, TEST_USERS["roster_manager_headers"]))[0]


def test_option_eligibility_boundary_sits_at_exactly_three_charges():
    """PRD 3.10: "The eligibility read is `OPTION_AVAILABLE` when charges are
    below three and `NO_OPTION_REMAINING` otherwise, so the boundary sits exactly
    at three: charges of 2 are available and charges of 3 are exhausted. The
    `waivers_required` read is true exactly when the eligibility read is
    `NO_OPTION_REMAINING`."

    Design: Corner/calculations/option_eligibility_flips_at_exactly_three_charges_and_void_restores_one
    """
    set_test_clock()
    complex_ = create_complex()
    under = register_player(complex_["id"], minor_league_option_years_used=2)
    at_limit = register_player(complex_["id"], minor_league_option_years_used=3)
    open_roster_record(under["id"])
    open_roster_record(at_limit["id"])

    record_under = _record_for(under["id"])
    record_limit = _record_for(at_limit["id"])

    assert record_under["option_eligibility"] == "OPTION_AVAILABLE"
    assert record_under["waivers_required"] is False
    assert record_limit["option_eligibility"] == "NO_OPTION_REMAINING"
    assert record_limit["waivers_required"] is True


def test_option_assign_passes_every_guard_from_available_allowance():
    """PRD 3.10: "From a pending record, an `OPTION_ASSIGN` decision requires
    `option_eligibility` to be `OPTION_AVAILABLE` and moves the player to
    `OPTIONED_MINORS`."

    Design: Corner/validations/satisfiable_roster_decision_passes_every_guard
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"], minor_league_option_years_used=0)

    result = validate_success(api_client.decide(
        onboarded["player"]["id"], "OPTION_ASSIGN", TEST_USERS["roster_manager_headers"]))

    assert result["current_roster_status"] == "OPTIONED_MINORS"
    assert result["roster_decision_status"] == "DECISION_PENDING"
    assert result["decision_sequence"] == 1
    assert result["option_eligibility"] == "OPTION_AVAILABLE"


def test_finalize_by_the_same_principal_is_refused_then_a_second_principal_succeeds():
    """PRD 3.10: "it requires the finalizing operator's `X-User-ID` to differ
    from `last_decision_actor_id`, which is the segregation-of-duties gate — the
    person who applied the decision may not also be the person who finalizes it,
    and the refusal is `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/finalize_by_the_same_principal_that_applied_the_decision_is_forbidden
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    applier = make_actor_headers("rm-applier", "RosterManager")
    validate_success(api_client.decide(player_id, "OPTION_ASSIGN", applier))

    validate_error(
        api_client.finalize_decision(player_id, applier),
        ApiErrorId.ERR_SOD_VIOLATION,
    )
    assert _record_for(player_id)["roster_decision_status"] == "DECISION_PENDING"

    checker = make_actor_headers("rm-checker", "RosterManager")
    final = validate_success(api_client.finalize_decision(player_id, checker))
    assert final["roster_decision_status"] == "DECISION_FINALIZED"
    assert final["last_decision_actor_id"] == "rm-applier"


def test_breakout_from_a_terminal_record_reports_the_transition_error_first():
    """PRD 3.11: "A break-out attempted from a state that is not a valid source
    is refused with `ERR_ROSTER_STATUS_INVALID_TRANSITION` (HTTP 409), and one
    attempted against a record in a terminal status is refused with
    `ERR_ROSTER_ALREADY_FINAL` (HTTP 409)."
    PRD 2.9: "the terminal-status guard `ERR_ROSTER_ALREADY_FINAL` (HTTP 409)"
    follows `ERR_ROSTER_STATUS_INVALID_TRANSITION`.

    Design: Difficulty/priority_pair_validation_conflict/roster_state_precondition_outranks_terminal_breakout_precondition
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_nri_released(complex_["id"])
    record = onboarded["roster"]

    validate_error(
        api_client.break_out_camp(
            record["id"], "AAA", TEST_USERS["minor_league_coordinator_headers"]),
        ApiErrorId.ERR_ROSTER_STATUS_INVALID_TRANSITION,
    )
    assert _record_for(onboarded["player"]["id"])["current_roster_status"] == "NRI_RELEASED"


def test_breakout_from_a_terminal_record_does_not_create_an_assignment():
    """PRD 3.11: "The terminal roster statuses are `RELEASED`, `NRI_RELEASED`,
    `ASSIGNED_AAA` and `ASSIGNED_AA`. Once a record reaches one of them it can no
    longer accept a further decision or break-out"

    Design: Difficulty/priority_pair_validation_conflict/roster_state_precondition_outranks_terminal_breakout_precondition
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_nri_released(complex_["id"])
    player_id = onboarded["player"]["id"]

    resp = api_client.break_out_camp(
        onboarded["roster"]["id"], "AAA", TEST_USERS["minor_league_coordinator_headers"])
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_ROSTER_ALREADY_FINAL"

    assignments = validate_success(api_client.list_minor_league_assignments(
        TEST_USERS["minor_league_coordinator_headers"], params={"player_id": player_id}))
    assert assignments == []


def test_void_decision_after_the_report_date_is_refused():
    """PRD 3.10: "it requires the logical clock to be strictly before the owning
    player's invitation `report_current_date` — a clock at exactly the report
    date is too late, and the refusal is `ERR_OUTSIDE_WINDOW` (HTTP 422)."

    Design: Corner/errors/schedule_change_outside_the_packaging_window_is_rejected
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_optioned_minors_finalized(complex_["id"])
    player_id = onboarded["player"]["id"]

    set_test_clock("2026-02-01T00:00:00Z")
    validate_error(
        api_client.void_decision(player_id, make_actor_headers("rm-voider", "RosterManager")),
        ApiErrorId.ERR_OUTSIDE_WINDOW,
    )
    record = _record_for(player_id)
    assert record["roster_decision_status"] == "DECISION_FINALIZED"
    assert record["current_roster_status"] == "OPTIONED_MINORS"


def test_roster_manager_cannot_break_a_player_out_of_camp():
    """PRD 3.11: "Breaking out of camp is a `MinorLeagueCoordinator` action"
    PRD 2.1: "Authorization failures always take precedence over domain
    rejections: a role that is not permitted for an operation is refused before
    any state, window or business rule is examined."

    Design: Corner/rbac/roster_manager_cannot_break_a_player_out_of_camp
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = roster_to_nri_released(complex_["id"])

    validate_error(
        api_client.break_out_camp(
            onboarded["roster"]["id"], "AAA", TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert _record_for(onboarded["player"]["id"])["current_roster_status"] == "NRI_RELEASED"


def test_a_second_active_assignment_is_refused():
    """PRD 3.5: "no other assignment of that player may already be `ACTIVE`,
    since a player holds at most one — a second active assignment is refused with
    `ERR_PLAYER_ALREADY_ASSIGNED` (HTTP 409)."

    Design: Corner/state_machines/reassigning_an_active_player_to_a_second_active_group_is_refused
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    player_id = onboarded["player"]["id"]
    group_a, assignment_a = create_group_with_assignment(
        complex_["id"], player_id, group_name="Pitchers Group A")
    group_b, assignment_b = create_group_with_assignment(
        complex_["id"], player_id, group_name="Pitchers Group B")

    validate_success(api_client.call_up(
        assignment_a["id"], TEST_USERS["field_coordinator_headers"]))
    validate_error(
        api_client.call_up(assignment_b["id"], TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_PLAYER_ALREADY_ASSIGNED,
    )
    assert api_client.get_assignment(
        assignment_b["id"], TEST_USERS["field_coordinator_headers"]
    ).json()["data"]["assignment_status"] == "PROVISIONAL"
    assert api_client.get_assignment(
        assignment_a["id"], TEST_USERS["field_coordinator_headers"]
    ).json()["data"]["assignment_status"] == "ACTIVE"
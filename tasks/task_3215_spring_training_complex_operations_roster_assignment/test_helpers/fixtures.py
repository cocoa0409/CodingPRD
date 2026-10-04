"""Composite setup helpers.

The harness restarts the API server before every test, so each test starts
against an empty database. Every helper here builds its preconditions from
scratch through PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_actor_headers


def _d(response):
    """Lenient setup validator: any 2xx, clear failure message."""
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 0: clock and simple entities
# ---------------------------------------------------------------------------

def set_test_clock(current_utc=TEST_DEFAULTS["DEFAULT_CURRENT_UTC"]):
    """Move the logical clock. The server never reads wall-clock time."""
    return _d(api_client.set_clock(current_utc, TEST_USERS["platform_admin_headers"]))


def create_complex(**overrides):
    resp = api_client.create_complex(
        factories.create_complex_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return _d(resp)


def create_many_complexes(count, **overrides):
    return [create_complex(**overrides) for _ in range(count)]


def create_agreement(complex_id, **overrides):
    resp = api_client.create_agreement(
        factories.create_agreement_payload(complex_id, **overrides),
        TEST_USERS["community_liaison_headers"],
    )
    return _d(resp)


def activate_agreement(agreement_id):
    return _d(api_client.activate_agreement(
        agreement_id, TEST_USERS["community_liaison_headers"]))


def open_host_community_record(agreement_id):
    return _d(api_client.open_host_community_record(
        agreement_id, TEST_USERS["community_liaison_headers"]))


def open_ticketing(record_id):
    return _d(api_client.open_ticketing(record_id, TEST_USERS["community_liaison_headers"]))


def sell_tickets(record_id, quantity):
    return _d(api_client.sell_tickets(
        record_id, quantity, TEST_USERS["community_liaison_headers"]))


def create_active_agreement_with_record(complex_id, tickets=0, **ag_overrides):
    """Complex -> ACTIVE agreement -> host community record, optionally on sale
    with `tickets` already sold. Returns (agreement, record)."""
    agreement = create_agreement(complex_id, **ag_overrides)
    activate_agreement(agreement["id"])
    record = open_host_community_record(agreement["id"])
    if tickets is not None:
        open_ticketing(record["id"])
        if tickets > 0:
            sell_tickets(record["id"], tickets)
        record = get_host_community_record(record["id"])
    return agreement, record


def get_host_community_record(record_id):
    return _d(api_client.get_host_community_record(
        record_id, TEST_USERS["community_liaison_headers"]))


def get_ledger(record_id):
    return _d(api_client.get_ledger(record_id, TEST_USERS["community_liaison_headers"]))


def get_agreement(agreement_id):
    return _d(api_client.get_agreement(agreement_id, TEST_USERS["community_liaison_headers"]))


def get_complex(complex_id):
    return _d(api_client.get_complex(complex_id, TEST_USERS["complex_director_headers"]))


def field_maintenance(complex_id, maintenance_action):
    return api_client.field_maintenance(
        complex_id, maintenance_action, TEST_USERS["complex_director_headers"])


def get_workout_group(group_id):
    return _d(api_client.get_workout_group(group_id, TEST_USERS["complex_director_headers"]))


def get_invitation(invitation_id):
    return _d(api_client.get_invitation(invitation_id, TEST_USERS["travel_coordinator_headers"]))


def get_throw_program(program_id):
    return _d(api_client.get_throw_program(program_id, TEST_USERS["pitching_coordinator_headers"]))


def get_sponsorship(sponsorship_id):
    return _d(api_client.get_sponsorship(sponsorship_id, TEST_USERS["community_liaison_headers"]))


def get_travel_arrangement(arrangement_id):
    return _d(api_client.get_travel_arrangement(
        arrangement_id, TEST_USERS["travel_coordinator_headers"]))


def get_program_profile(profile_id):
    return _d(api_client.get_program_profile(profile_id, TEST_USERS["team_physician_headers"]))


def get_player(player_id):
    return _d(api_client.get_player(player_id, TEST_USERS["roster_manager_headers"]))


def get_game(game_id):
    return _d(api_client.get_game(game_id, TEST_USERS["complex_director_headers"]))


def get_participation(participation_id):
    return _d(api_client.get_participation(
        participation_id, TEST_USERS["field_coordinator_headers"]))


def get_physical(physical_id):
    return _d(api_client.get_physical(physical_id, TEST_USERS["team_physician_headers"]))


def get_minor_league_assignment(assignment_id):
    return _d(api_client.get_minor_league_assignment(
        assignment_id, TEST_USERS["minor_league_coordinator_headers"]))


def fresh_group_version(group_id):
    return get_workout_group(group_id)["version"]


def fresh_invitation_version(invitation_id):
    return get_invitation(invitation_id)["version"]


def fresh_game_version(game_id):
    return _d(api_client.get_game(game_id, TEST_USERS["complex_director_headers"]))["version"]


# ---------------------------------------------------------------------------
# Tier 1: player onboarding and the medical pipeline
# ---------------------------------------------------------------------------

def register_player(complex_id, **overrides):
    resp = api_client.create_player(
        factories.create_player_payload(complex_id, **overrides),
        TEST_USERS["roster_manager_headers"],
    )
    return _d(resp)


def open_roster_record(player_id):
    return _d(api_client.open_roster_record(player_id, TEST_USERS["roster_manager_headers"]))


def open_program_profile(player_id):
    return _d(api_client.open_program_profile(player_id, TEST_USERS["team_physician_headers"]))


def issue_invitation(player_id, **overrides):
    resp = api_client.create_invitation(
        player_id,
        factories.create_invitation_payload(player_id, **overrides),
        TEST_USERS["travel_coordinator_headers"],
    )
    return _d(resp)


def send_letter(invitation_id):
    return _d(api_client.send_letter(invitation_id, TEST_USERS["travel_coordinator_headers"]))


def create_sent_letter_invitation(player_id, **overrides):
    invitation = issue_invitation(player_id, **overrides)
    send_letter(invitation["id"])
    return get_invitation(invitation["id"])


def schedule_physical(player_id, scheduled_visit_date=TEST_DEFAULTS["PHYSICAL_VISIT"]):
    return _d(api_client.create_physical(
        player_id, scheduled_visit_date, TEST_USERS["team_physician_headers"]))


def _at_or_after_visit(scheduled_visit_date):
    """The server refuses a perform before the visit date is reached, so a setup
    physical is performed at the visit instant when the clock has not yet
    reached it."""
    from datetime import datetime, timezone

    def _p(text):
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)

    if _p(scheduled_visit_date) > _p(TEST_DEFAULTS["DEFAULT_CURRENT_UTC"]):
        set_test_clock(scheduled_visit_date)


def perform_passing_physical(player_id, scheduled_visit_date=TEST_DEFAULTS["PHYSICAL_VISIT"]):
    """Schedule + perform a PASSED physical, clearing the player."""
    physical = schedule_physical(player_id, scheduled_visit_date)
    _at_or_after_visit(scheduled_visit_date)
    _d(api_client.perform_physical(
        physical["id"], "PASSED", TEST_USERS["team_physician_headers"]))
    return physical


def schedule_then_perform(player_id, scheduled_visit_date, result="PASSED"):
    """Schedule a physical and record its outcome, moving the clock to the visit
    first when the visit has not yet been reached. Used by tests whose subject
    is the outcome of a later examination rather than the visit window."""
    physical = schedule_physical(player_id, scheduled_visit_date)
    _at_or_after_visit(scheduled_visit_date)
    return api_client.perform_physical(
        physical["id"], result, TEST_USERS["team_physician_headers"])


def onboard_player(complex_id, clear=True, invitation=True, **player_overrides):
    """Player + roster record + program profile (+ sent-letter invitation)
    (+ a PASSED physical) in one call. Returns a dict of the created rows.

    The logical clock is deliberately left where the caller set it: fixtures
    build preconditions, they do not move the clock."""
    player = register_player(complex_id, **player_overrides)
    roster = open_roster_record(player["id"])
    profile = open_program_profile(player["id"])
    result = {"player": player, "roster": roster, "profile": profile}
    if invitation:
        result["invitation"] = create_sent_letter_invitation(player["id"])
    if clear:
        result["physical"] = perform_passing_physical(player["id"])
        result["player"] = _d(api_client.get_player(
            player["id"], TEST_USERS["roster_manager_headers"]))
    return result


def cleared_player(complex_id, **player_overrides):
    return onboard_player(complex_id, clear=True, invitation=True, **player_overrides)


# ---------------------------------------------------------------------------
# Tier 2: workout groups, assignments and throwing programs
# ---------------------------------------------------------------------------

def create_workout_group(complex_id, **overrides):
    resp = api_client.create_workout_group(
        complex_id,
        factories.create_workout_group_payload(complex_id, **overrides),
        TEST_USERS["complex_director_headers"],
    )
    return _d(resp)


def publish_group(group_id):
    """Re-read the group's version, then publish."""
    return _d(api_client.publish_group(
        group_id, fresh_group_version(group_id), TEST_USERS["complex_director_headers"]))


def create_published_group(complex_id, publish=True, **overrides):
    group = create_workout_group(complex_id, **overrides)
    if publish:
        group = publish_group(group["id"])
    return group


def assign_player(group_id, player_id, roster_bucket="MAJOR",
                  assignment_kind="ACTIVE_WORKOUT", expected_group_version=None):
    """Create a GroupAssignment. When no version is supplied the group's
    current version is read first."""
    if expected_group_version is None:
        expected_group_version = fresh_group_version(group_id)
    payload = factories.create_assignment_payload(
        group_id, player_id, expected_group_version,
        roster_bucket=roster_bucket, assignment_kind=assignment_kind,
    )
    return _d(api_client.create_assignment(group_id, payload,
                                           TEST_USERS["field_coordinator_headers"]))


def create_group_with_assignment(complex_id, player_id, publish=True,
                                 roster_bucket="MAJOR", assignment_kind="ACTIVE_WORKOUT",
                                 **group_overrides):
    """Published (by default) group holding one PROVISIONAL assignment.
    Returns (group, assignment)."""
    group = create_workout_group(complex_id, roster_bucket=roster_bucket, **group_overrides)
    assignment = assign_player(group["id"], player_id,
                               roster_bucket=roster_bucket,
                               assignment_kind=assignment_kind)
    if publish:
        group = publish_group(group["id"])
    return group, assignment


def withdraw_assignment(assignment_id, reason="CAMP_BREAKOUT"):
    return _d(api_client.withdraw_assignment(
        assignment_id, reason, TEST_USERS["field_coordinator_headers"]))


def call_up_assignment(assignment_id):
    return _d(api_client.call_up(assignment_id, TEST_USERS["field_coordinator_headers"]))


def create_throw_program(assignment_id, target_catch_play_throws=200,
                         target_bullpen_sessions=2):
    return _d(api_client.create_throw_program(
        assignment_id,
        factories.create_throw_program_payload(
            assignment_id,
            target_catch_play_throws=target_catch_play_throws,
            target_bullpen_sessions=target_bullpen_sessions),
        TEST_USERS["pitching_coordinator_headers"]))


def log_catch_play(program_id, throws, logged_at="2026-01-05T00:00:00Z"):
    return _d(api_client.log_throw_session(
        program_id,
        factories.log_session_payload(program_id, "CATCH_PLAY",
                                      play_catch_throws=throws, logged_at=logged_at),
        TEST_USERS["pitching_coordinator_headers"]))


def log_bullpen(program_id, logged_at="2026-01-05T00:00:00Z"):
    return _d(api_client.log_throw_session(
        program_id,
        factories.log_session_payload(program_id, "BULLPEN",
                                      play_catch_throws=0, logged_at=logged_at),
        TEST_USERS["pitching_coordinator_headers"]))


def advance_phase(program_id, direction="ADVANCE"):
    return api_client.advance_phase(program_id, direction,
                                    TEST_USERS["pitching_coordinator_headers"])


def setup_pitcher_program(complex_id, target_catch_play_throws=200,
                          target_bullpen_sessions=2, assignment_kind="REHAB",
                          group_overrides=None, **player_overrides):
    """Cleared pitcher -> published MAJOR group -> assignment -> throw program.

    Returns (player, roster, profile, group, assignment, program).
    """
    onboarded = cleared_player(complex_id, **player_overrides)
    player = onboarded["player"]
    group, assignment = create_group_with_assignment(
        complex_id, player["id"], assignment_kind=assignment_kind,
        **(group_overrides or {}))
    program = create_throw_program(
        assignment["id"],
        target_catch_play_throws=target_catch_play_throws,
        target_bullpen_sessions=target_bullpen_sessions)
    return player, onboarded["roster"], onboarded["profile"], group, assignment, program


def onboard_to_phase(complex_id, target_phase, target_catch_play_throws=40,
                     target_bullpen_sessions=2):
    """Carry a fresh program to `target_phase` (PHASE_2, PHASE_3 or PHASE_4)."""
    onboarded = cleared_player(complex_id)
    player = onboarded["player"]
    group, assignment = create_group_with_assignment(
        complex_id, player["id"], assignment_kind="REHAB")
    program = create_throw_program(
        assignment["id"],
        target_catch_play_throws=target_catch_play_throws,
        target_bullpen_sessions=target_bullpen_sessions)
    log_catch_play(program["id"], target_catch_play_throws)
    # `setup_pitcher_program` defaults target_catch_play_throws to 200; when the
    # caller leaves it at that default the design index's workload is a 200-throw
    # session followed by a 50-throw one, so the accumulated figure is 250.
    if target_catch_play_throws == 200:
        log_catch_play(program["id"], 50)
    if target_phase == "PHASE_1":
        return onboarded, group, assignment, program
    advance_phase(program["id"], "ADVANCE")            # -> PHASE_2
    if target_phase == "PHASE_2":
        return onboarded, group, assignment, program
    log_bullpen(program["id"])
    advance_phase(program["id"], "ADVANCE")            # -> PHASE_3
    if target_phase == "PHASE_3":
        return onboarded, group, assignment, program
    advance_phase(program["id"], "ADVANCE")            # -> PHASE_4
    return onboarded, group, assignment, program


# ---------------------------------------------------------------------------
# Tier 2: community ledger, travel and sponsorships
# ---------------------------------------------------------------------------

def create_settled_sponsorship(record_id, committed_cents=20000, tier="LOCAL",
                               contribute_cents=None):
    """Sponsorship contributed to its full commitment and settled."""
    sponsorship = _d(api_client.create_sponsorship(
        record_id,
        factories.create_sponsorship_payload(
            record_id, sponsor_tier=tier, committed_amount_cents=committed_cents),
        TEST_USERS["community_liaison_headers"]))
    amount = committed_cents if contribute_cents is None else contribute_cents
    _d(api_client.contribute(
        sponsorship["id"], amount, "CONTRIBUTE", TEST_USERS["community_liaison_headers"]))
    _d(api_client.settle_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))
    return sponsorship


def create_confirmed_arrangement(invitation_id, travel_cost_cents=50000,
                                 mode="AIR", travel_radius_miles=300,
                                 departure_at=TEST_DEFAULTS["DEPARTURE_AT"],
                                 expected_invitation_version=None):
    if expected_invitation_version is None:
        expected_invitation_version = fresh_invitation_version(invitation_id)
    payload = factories.create_travel_arrangement_payload(
        invitation_id, expected_invitation_version,
        mode=mode, travel_radius_miles=travel_radius_miles,
        travel_cost_cents=travel_cost_cents, departure_at=departure_at, confirm=True)
    return _d(api_client.create_travel_arrangement(
        invitation_id, payload, TEST_USERS["travel_coordinator_headers"]))


def setup_travel_funding_scenario(complex_id, tickets=4, **ag_overrides):
    """ACTIVE agreement + record with tickets sold + two signed pitchers each
    with a sent letter. Returns a dict of the fixture rows, ready for
    arrangement confirmation."""
    set_test_clock()
    agreement, record = create_active_agreement_with_record(
        complex_id, tickets=tickets, **ag_overrides)
    players = []
    for name in ("Nico Ferran", "Owen Marsh"):
        player = register_player(complex_id, full_name=name)
        open_roster_record(player["id"])
        open_program_profile(player["id"])
        invitation = create_sent_letter_invitation(player["id"])
        perform_passing_physical(player["id"])
        players.append({"player": player, "invitation": invitation})
    return {"agreement": agreement, "record": record, "players": players}


def create_corpus_member(complex_id, roster_bucket="MAJOR",
                         assignment_kind="ACTIVE_WORKOUT", publish=True,
                         **group_overrides):
    """One player + an open program profile + a group assignment, so the player
    enters the recognition corpus with the matching group count.
    Returns (player, group, assignment)."""
    onboarded = cleared_player(complex_id)
    player = onboarded["player"]
    group, assignment = create_group_with_assignment(
        complex_id, player["id"], publish=publish,
        roster_bucket=roster_bucket, assignment_kind=assignment_kind,
        **group_overrides)
    return player, group, assignment


def setup_recognition_corpus(complex_id, major_players=1, minor_players=0,
                             publish_major=True):
    """Build a recognition corpus: players holding MAJOR and/or MINOR group
    assignments in published groups. Returns the list of participating players."""
    members = []
    for i in range(major_players):
        onboarded = cleared_player(complex_id, full_name=f"Major Member {i}")
        _, _ = create_group_with_assignment(
            complex_id, onboarded["player"]["id"], roster_bucket="MAJOR",
            assignment_kind="ACTIVE_WORKOUT",
            group_name=f"Major Group {i}")
        members.append(onboarded["player"])
    for i in range(minor_players):
        onboarded = cleared_player(complex_id, full_name=f"Minor Member {i}")
        _, _ = create_group_with_assignment(
            complex_id, onboarded["player"]["id"], roster_bucket="MINOR",
            assignment_kind="ACTIVE_WORKOUT",
            group_name=f"Minor Group {i}")
        members.append(onboarded["player"])
    return members


# ---------------------------------------------------------------------------
# Tier 3: games and gameday
# ---------------------------------------------------------------------------

def create_game(complex_id, **overrides):
    return _d(api_client.create_game(
        complex_id,
        factories.create_game_payload(complex_id, **overrides),
        TEST_USERS["complex_director_headers"]))


def publish_game(game_id):
    return _d(api_client.publish_game(
        game_id, fresh_game_version(game_id), TEST_USERS["complex_director_headers"]))


def create_published_game(complex_id, **overrides):
    game = create_game(complex_id, **overrides)
    return publish_game(game["id"])


def add_participation(game_id, player_id, **overrides):
    return _d(api_client.create_participation(
        game_id,
        factories.create_participation_payload(game_id, player_id, **overrides),
        TEST_USERS["field_coordinator_headers"]))


def confirm_participation(game_id, participation_id, expected_game_version=None):
    if expected_game_version is None:
        expected_game_version = fresh_game_version(game_id)
    return api_client.confirm_participation(
        game_id, participation_id, expected_game_version,
        TEST_USERS["field_coordinator_headers"])


# ---------------------------------------------------------------------------
# Tier 4: roster decision progression
# ---------------------------------------------------------------------------

def roster_to_optioned_minors(complex_id, decide_actor="rm-decider"):
    """Cleared player whose decision path is at OPTIONED_MINORS /
    DECISION_PENDING. Returns the onboarded dict plus the roster record."""
    onboarded = cleared_player(complex_id)
    headers = make_actor_headers(decide_actor, "RosterManager")
    _d(api_client.decide(onboarded["player"]["id"], "OPTION_ASSIGN", headers))
    roster = _d(api_client.list_player_roster_records(
        onboarded["player"]["id"], TEST_USERS["roster_manager_headers"]))[0]
    onboarded["roster"] = roster
    return onboarded


def roster_to_nri_released(complex_id, decide_actor="rm-decider"):
    onboarded = cleared_player(complex_id)
    headers = make_actor_headers(decide_actor, "RosterManager")
    _d(api_client.decide(onboarded["player"]["id"], "NONROSTER_RELEASE", headers))
    roster = _d(api_client.list_player_roster_records(
        onboarded["player"]["id"], TEST_USERS["roster_manager_headers"]))[0]
    onboarded["roster"] = roster
    return onboarded


def roster_to_optioned_minors_finalized(complex_id, decide_actor="rm-decider",
                                        finalize_actor="rm-authorizer"):
    """OPTION_ASSIGN applied by one principal and finalized by another."""
    onboarded = roster_to_optioned_minors(complex_id, decide_actor)
    _d(api_client.finalize_decision(
        onboarded["player"]["id"], make_actor_headers(finalize_actor, "RosterManager")))
    onboarded["roster"] = _d(api_client.list_player_roster_records(
        onboarded["player"]["id"], TEST_USERS["roster_manager_headers"]))[0]
    return onboarded


def roster_to_designated_for_assignment(complex_id, decide_actor="rm-decider"):
    """Drive NRI -> OPTIONED_MINORS -> DESIGNATED_FOR_ASSIGNMENT. The applied
    option decision consumes one option credit, so
    `minor_league_option_years_used=2` leaves `option_eligibility` at
    `NO_OPTION_REMAINING` (and `waivers_required` true) once the outright
    assignment's precondition is evaluated."""
    onboarded = cleared_player(complex_id, minor_league_option_years_used=2)
    headers = make_actor_headers(decide_actor, "RosterManager")
    _d(api_client.decide(onboarded["player"]["id"], "OPTION_ASSIGN", headers))
    _d(api_client.decide(onboarded["player"]["id"], "OUTRIGHT_ASSIGN", headers))
    onboarded["roster"] = _d(api_client.list_player_roster_records(
        onboarded["player"]["id"], TEST_USERS["roster_manager_headers"]))[0]
    return onboarded
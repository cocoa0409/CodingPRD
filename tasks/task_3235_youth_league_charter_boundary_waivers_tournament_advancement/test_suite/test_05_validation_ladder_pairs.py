"""Validation-ladder ordering pairs: earlier categories beat later ones when a
single request would violate several rules at once."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    set_clock, charter_league, register_player, get_game, get_player,
    setup_tournament_entry, create_game,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestStateBeatsSafetyOnFinalize:
    """Finalizing a SCHEDULED game surfaces the state error even when the
    payload also carries an over-cap correction."""

    def test_finalize_scheduled_game_with_overcap_correction_reports_state(
            self, api):
        """PRD §2.7: "the ordering is normative: when a request would violate
        several rules at once, the error that surfaces is the one belonging to
        the earliest category on the ladder. The ladder, from first to last, is:
        (1) authentication context — the presence and validity of the two
        headers; (2) authorization — whether the role may perform the operation;
        (3) resource existence, left to right as described above; (4) the league
        charter gate described in §2.8; (5) the state precondition of the target
        entity (renewal pending, waiver pending, roster open, game in progress,
        and so on); (6) pitching and screening safety rules"

        Design: Difficulty/priority_pair_validation_conflict/state_game_not_in_progress_beats_safety_pitch_cap_on_finalize
        """
        ctx = setup_tournament_entry(league_name="Priority One LL")
        set_clock("2027-06-01T00:00:00Z")
        game = create_game(ctx["entry"]["id"])
        assert game["play_status"] == "SCHEDULED"

        err = validate_error(api.finalize_game(
            ctx["entry"]["id"], game["id"],
            {"our_score": 5, "opponent_score": 3,
             "expected_game_version": game["version"],
             "scorebook_corrections": [
                 {"appearance_id": NON_EXISTENT_UUID, "official_pitches": 99}]},
            TD), ApiErrorId.ERR_GAME_NOT_IN_PROGRESS)
        assert err["error_id"] == "ERR_GAME_NOT_IN_PROGRESS"
        # State category (5) precedes pitching safety (6): the 99-pitch
        # correction never surfaces its own error here.
        assert get_game(game["id"])["play_status"] == "SCHEDULED"

    def test_finalize_scheduled_game_with_valid_payload_also_reports_state(
            self, api):
        """PRD §3.7: "A finalization against a game not `IN_PROGRESS` is rejected
        with `ERR_GAME_NOT_IN_PROGRESS`."

        Design: Difficulty/priority_pair_validation_conflict/state_game_not_in_progress_beats_safety_pitch_cap_on_finalize
        """
        ctx = setup_tournament_entry(league_name="Priority One LL Two")
        set_clock("2027-06-01T00:00:00Z")
        game = create_game(ctx["entry"]["id"])
        err = validate_error(api.finalize_game(
            ctx["entry"]["id"], game["id"],
            {"our_score": 5, "opponent_score": 3,
             "expected_game_version": game["version"]},
            TD), ApiErrorId.ERR_GAME_NOT_IN_PROGRESS)
        assert err["error_id"] == "ERR_GAME_NOT_IN_PROGRESS"
        assert get_game(game["id"])["play_status"] == "SCHEDULED"


class TestTemporalWindowBeatsMissingDocument:
    """A closed registration window is reported before the missing-document
    referential check."""

    def test_verify_outside_window_with_no_documents_reports_window(self, api):
        """PRD §2.7: "A charter-gate failure therefore surfaces as
        `ERR_LEAGUE_NOT_CHARTERED` even when the request would also fail a later
        business rule, and a state precondition surfaces before any window or
        integrity check."
        PRD §2.7: "(7) temporal-window rules such as renewal, registration,
        document freshness, and screening coverage windows; (8) cross-entity
        referential integrity such as document presence, boundary satisfaction,
        division assignment, roster membership, overlap checks, insurance
        containment, advancement prerequisites, and roster size bounds"

        Design: Difficulty/priority_pair_validation_conflict/temporal_window_closed_beats_referential_missing_document_on_verify
        """
        ctx = charter_league(league_name="Priority Two LL")
        set_clock("2027-02-01T00:00:00Z")
        player = register_player(ctx["league"]["id"], last_name="Docs")
        # No eligibility documents attached at all.
        set_clock("2027-05-15T00:00:00Z")
        err = validate_error(api.verify_eligibility(
            ctx["league"]["id"], player["id"], LA, {}),
            ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED)
        assert err["error_id"] == "ERR_REGISTRATION_WINDOW_CLOSED"
        assert get_player(player["id"])["eligibility_status"] == "PENDING"

    def test_verify_outside_window_reports_window_not_boundary(self, api):
        """PRD §3.4: "the clock date at verification must fall within January 1
        through April 30 of the league's `season_year`, inclusive; outside that
        window the verification is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`
        (HTTP 422)."
        PRD §2.7: "(7) temporal-window rules such as renewal, registration,
        document freshness, and screening coverage windows; (8) cross-entity
        referential integrity such as document presence, boundary satisfaction,
        division assignment, roster membership, overlap checks, insurance
        containment, advancement prerequisites, and roster size bounds"

        Design: Difficulty/priority_pair_validation_conflict/temporal_window_closed_beats_referential_missing_document_on_verify
        """
        ctx = charter_league(league_name="Priority Two LL Three")
        set_clock("2027-02-01T00:00:00Z")
        # Outside boundary AND no documents — both later categories than the
        # registration window.
        player = register_player(ctx["league"]["id"], last_name="Out",
                                 residence=False, school=False)
        set_clock("2027-05-15T00:00:00Z")
        err = validate_error(api.verify_eligibility(
            ctx["league"]["id"], player["id"], LA, {}),
            ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED)
        assert err["error_id"] == "ERR_REGISTRATION_WINDOW_CLOSED"
        assert get_player(player["id"])["eligibility_status"] == "PENDING"

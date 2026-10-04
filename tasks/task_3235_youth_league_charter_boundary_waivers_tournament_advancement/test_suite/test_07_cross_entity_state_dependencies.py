"""Cross-entity state dependencies: the league charter gate on roster/entry
creation, and the player eligibility gate on roster selections."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    set_clock, charter_league, create_league_raw, major_division,
    register_player, create_open_roster, get_roster, get_league,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestCharterGateBlocksRosterAndEntry:
    """A PROVISIONAL league gates roster and entry creation even when every
    other precondition would pass."""

    def test_roster_creation_blocked_in_provisional_league(self, api):
        """PRD §2.8: "A league must be `CHARTERED` — not `PROVISIONAL`, not
        `SUSPENDED` — before any of the following six operations will proceed:
        registering a player, requesting a boundary waiver, creating an all-star
        roster, adding a selection to a roster, submitting a roster, and
        creating a tournament entry. Any of these attempted while the league is
        `PROVISIONAL` or `SUSPENDED` is rejected with `ERR_LEAGUE_NOT_CHARTERED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/tournament_entry_blocked_when_league_not_chartered
        """
        set_clock("2026-10-15T00:00:00Z")
        league, divisions = create_league_raw(league_name="Ungated LL")
        assert league["charter_status"] == "PROVISIONAL"
        major = {d["division_code"]: d for d in divisions}["MAJOR"]

        err = validate_error(api.create_all_star_roster(
            league["id"], {"division_id": major["id"]}, LA),
            ApiErrorId.ERR_LEAGUE_NOT_CHARTERED)
        assert err["error_id"] == "ERR_LEAGUE_NOT_CHARTERED"
        assert get_league(league["id"])["charter_status"] == "PROVISIONAL"

    def test_entry_creation_blocked_in_provisional_league(self, api):
        """PRD §2.7: "The ladder, from first to last, is: (1) authentication
        context — the presence and validity of the two headers; (2)
        authorization — whether the role may perform the operation; (3) resource
        existence, left to right as described above; (4) the league charter gate
        described in §2.8; (5) the state precondition of the target entity
        (renewal pending, waiver pending, roster open, game in progress, and so
        on)"
        PRD §2.8: "A league must be `CHARTERED` — not `PROVISIONAL`, not
        `SUSPENDED` — before any of the following six operations will proceed:
        registering a player, requesting a boundary waiver, creating an all-star
        roster, adding a selection to a roster, submitting a roster, and
        creating a tournament entry. Any of these attempted while the league is
        `PROVISIONAL` or `SUSPENDED` is rejected with `ERR_LEAGUE_NOT_CHARTERED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/tournament_entry_blocked_when_league_not_chartered
        """
        set_clock("2026-10-15T00:00:00Z")
        league, _divisions = create_league_raw(league_name="Ungated LL Two")
        # The referenced roster does not exist; the charter gate (category 4)
        # precedes the roster-state precondition (category 5).
        err = validate_error(api.create_tournament_entry(
            league["id"],
            {"roster_id": NON_EXISTENT_UUID, "level": "DISTRICT"}, TD),
            ApiErrorId.ERR_LEAGUE_NOT_CHARTERED)
        assert err["error_id"] == "ERR_LEAGUE_NOT_CHARTERED"
        assert get_league(league["id"])["charter_status"] == "PROVISIONAL"


class TestSelectionRequiresEligiblePlayer:
    """A PENDING player cannot be selected even on an OPEN roster."""

    def test_pending_player_selection_rejected(self, api):
        """PRD §3.6: "The candidate player must be `ELIGIBLE`, or the add is
        rejected with `ERR_PLAYER_NOT_ELIGIBLE` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/selection_blocked_when_player_not_eligible
        """
        ctx = charter_league(league_name="Pending Player LL")
        set_clock("2027-02-01T00:00:00Z")
        player = register_player(ctx["league"]["id"], last_name="Nding")
        assert player["eligibility_status"] == "PENDING"
        roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])

        err = validate_error(api.add_roster_selection(
            ctx["league"]["id"], roster["id"], {"player_id": player["id"]}, LA),
            ApiErrorId.ERR_PLAYER_NOT_ELIGIBLE)
        assert err["error_id"] == "ERR_PLAYER_NOT_ELIGIBLE"
        assert get_roster(ctx["league"]["id"], roster["id"])["roster_size"] == 0

    def test_pending_player_rejection_leaves_roster_open_and_empty(self, api):
        """PRD §3.6: "The candidate player must be `ELIGIBLE`, or the add is
        rejected with `ERR_PLAYER_NOT_ELIGIBLE` (HTTP 409)"
        PRD §3.6: "A successful add appends a selection with status `ACTIVE` and
        recomputes `roster_size`."

        Design: Difficulty/cross_entity_state_dependency/selection_blocked_when_player_not_eligible
        """
        ctx = charter_league(league_name="Pending Player LL Two")
        set_clock("2027-02-01T00:00:00Z")
        player = register_player(ctx["league"]["id"], last_name="Nding2")
        roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])

        validate_error(api.add_roster_selection(
            ctx["league"]["id"], roster["id"], {"player_id": player["id"]}, LA),
            ApiErrorId.ERR_PLAYER_NOT_ELIGIBLE)
        after = get_roster(ctx["league"]["id"], roster["id"])
        assert after["status"] == "OPEN"
        assert after["roster_size"] == 0
        assert after["selections"] == []

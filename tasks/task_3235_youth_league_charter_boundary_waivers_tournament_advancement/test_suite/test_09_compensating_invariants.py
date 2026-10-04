"""Compensating invariants: recorded_pitch_total across protest reversal and
roster_size across add + cascade vacate."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_paginated,
    get_success_data,
    set_clock, charter_league, register_and_verify_player, major_division,
    create_open_roster, add_selection, submit_roster, get_roster, get_game,
    get_appearance, get_player,
    setup_tournament_entry, create_game, record_appearance,
    assert_recorded_pitch_total_invariant, assert_roster_size_invariant,
)

LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestPitchTotalInvariantAcrossReversal:
    """An upheld eligibility challenge reverses appearances with zero drift."""

    def test_reversed_appearance_contributes_zero_to_pitch_total(self, api):
        """PRD §3.7: "The `recorded_pitch_total` is always exactly the sum over
        the game's `RECORDED` appearances of each appearance's effective count —
        `official_pitches` when set, else `pitches_thrown` — with `REVERSED`
        appearances contributing zero."
        PRD §3.8: "Upholding an `ELIGIBILITY_CHALLENGE` instead strikes the
        player: every `RECORDED` pitching appearance of the protest's
        `target_player_id` in that game moves to `REVERSED`, the game's
        `recorded_pitch_total` is recomputed excluding the reversed appearances,
        and the game itself stays where it is."

        Design: Difficulty/compensating_invariant/pitch_total_invariant_holds_across_protest_reversal
        """
        ctx = setup_tournament_entry(league_name="Ledger LL")
        set_clock("2027-06-01T00:00:00Z")
        game = create_game(ctx["entry"]["id"])
        a1 = record_appearance(
            ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 30)
        a2 = record_appearance(
            ctx["entry"]["id"], game["id"], ctx["players"][1]["id"], 40)
        assert get_game(game["id"])["recorded_pitch_total"] == 70

        protest = get_success_data(api.file_protest(
            ctx["entry"]["id"], game["id"],
            {"protest_type": "ELIGIBILITY_CHALLENGE",
             "grounds": "pitcher not roster-eligible",
             "target_player_id": ctx["players"][1]["id"]}, TD))
        resolved = validate_success(api.resolve_protest(
            ctx["entry"]["id"], game["id"], protest["id"],
            {"action": "UPHOLD"}, TD), 200)
        assert resolved["status"] == "UPHELD"

        assert get_appearance(a2["id"])["status"] == "REVERSED"
        assert get_appearance(a1["id"])["status"] == "RECORDED"
        game_after = get_game(game["id"])
        assert game_after["recorded_pitch_total"] == 30, (
            "the reversal must leave the total at exactly the sum over "
            f"RECORDED appearances, got {game_after['recorded_pitch_total']}")
        assert game_after["protest_status"] == "RESOLVED"

    def test_pitch_total_invariant_matches_appearance_listing(self, api):
        """PRD §3.7: "The `recorded_pitch_total` is always exactly the sum over
        the game's `RECORDED` appearances of each appearance's effective count —
        `official_pitches` when set, else `pitches_thrown` — with `REVERSED`
        appearances contributing zero."

        Design: Difficulty/compensating_invariant/pitch_total_invariant_holds_across_protest_reversal
        """
        ctx = setup_tournament_entry(league_name="Ledger LL Two")
        set_clock("2027-06-01T00:00:00Z")
        game = create_game(ctx["entry"]["id"])
        record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 30)
        record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][1]["id"], 40)
        protest = get_success_data(api.file_protest(
            ctx["entry"]["id"], game["id"],
            {"protest_type": "ELIGIBILITY_CHALLENGE",
             "grounds": "pitcher not roster-eligible",
             "target_player_id": ctx["players"][1]["id"]}, TD))
        validate_success(api.resolve_protest(
            ctx["entry"]["id"], game["id"], protest["id"],
            {"action": "UPHOLD"}, TD), 200)

        appearances, _meta = validate_paginated(
            api.list_pitching_appearances(ctx["entry"]["id"], game["id"],
                                          TD))
        assert_recorded_pitch_total_invariant(get_game(game["id"]), appearances)


class TestRosterSizeInvariantAcrossVacate:
    """Adds and the cascade vacate keep roster_size equal to the ACTIVE count."""

    def test_roster_size_tracks_adds_and_cascade_vacate(self, api):
        """PRD §3.6: "The roster's `roster_size` is maintained as an invariant:
        it is always exactly the count of selections whose status is `ACTIVE`,
        recomputed whenever a selection is added or vacated."
        PRD §3.4: "On every all-star roster holding an `ACTIVE` selection of
        this player, that selection becomes `VACATED` and the roster's
        `roster_size` is recomputed; if such a roster was `SUBMITTED` it is
        recalled to `RECALLED`"

        Design: Difficulty/compensating_invariant/roster_size_invariant_holds_across_add_and_cascade_vacate
        """
        ctx = charter_league(league_name="Roster Count LL")
        set_clock("2027-02-01T00:00:00Z")
        births = ["2015-03-10", "2015-04-11", "2015-05-12", "2015-06-13"]
        players = [register_and_verify_player(
            ctx["league"]["id"], birth_date=b, last_name=f"P{i}")
            for i, b in enumerate(births)]
        roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
        for player in players:
            roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
        assert roster["roster_size"] == 4
        roster = submit_roster(ctx["league"]["id"], roster["id"])
        assert roster["status"] == "SUBMITTED"

        validate_success(api.revoke_eligibility(
            ctx["league"]["id"], players[1]["id"],
            LA, {"reason": "school enrollment lapsed"}), 200)

        after = get_roster(ctx["league"]["id"], roster["id"])
        assert after["status"] == "RECALLED"
        assert after["roster_size"] == 3
        vacated = [s for s in after["selections"] if s["status"] == "VACATED"]
        active = [s for s in after["selections"] if s["status"] == "ACTIVE"]
        assert len(vacated) == 1 and vacated[0]["player_id"] == players[1]["id"]
        assert len(active) == 3
        assert_roster_size_invariant(after)

    def test_revoked_player_reports_ineligible_after_cascade(self, api):
        """PRD §3.4: "Revocation flips the player to `INELIGIBLE` and fires a
        deliberate cascade across the tournament side of the system."
        PRD §3.6: "The roster's `roster_size` is maintained as an invariant:
        it is always exactly the count of selections whose status is `ACTIVE`,
        recomputed whenever a selection is added or vacated."

        Design: Difficulty/compensating_invariant/roster_size_invariant_holds_across_add_and_cascade_vacate
        """
        ctx = charter_league(league_name="Roster Count LL Two")
        set_clock("2027-02-01T00:00:00Z")
        births = ["2015-03-10", "2015-04-11", "2015-05-12", "2015-06-13"]
        players = [register_and_verify_player(
            ctx["league"]["id"], birth_date=b, last_name=f"Q{i}")
            for i, b in enumerate(births)]
        roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
        for player in players:
            roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
        submit_roster(ctx["league"]["id"], roster["id"])

        revoked = validate_success(api.revoke_eligibility(
            ctx["league"]["id"], players[0]["id"], LA, {}), 200)
        assert revoked["eligibility_status"] == "INELIGIBLE"
        assert get_player(players[0]["id"])["eligibility_status"] == "INELIGIBLE"
        after = get_roster(ctx["league"]["id"], roster["id"])
        assert_roster_size_invariant(after)
        assert after["roster_size"] == 3

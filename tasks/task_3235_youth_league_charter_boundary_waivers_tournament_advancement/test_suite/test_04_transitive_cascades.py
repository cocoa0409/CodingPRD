"""Transitive cascades: charter lapse (League -> Division -> Entry -> Game)
and eligibility revocation (Player -> Roster -> Entry -> Game)."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, get_success_data,
    set_clock, major_division, get_league, get_entry, get_game,
    get_division, get_roster,
    setup_tournament_entry, create_game,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestCharterLapseCascade:
    """The clock sweep suspends a lapsed league and cascades three levels down."""

    def test_lapse_cascades_league_division_entry_game(self, api):
        """PRD §3.8: "When the clock sweep of §2.5 detects that a `CHARTERED`
        league's latest approved renewal covers season Y, the new clock date
        falls after March 31 of season Y+1, and no approved renewal for season
        Y+1 exists, the league moves `CHARTERED` → `SUSPENDED`. The cascade then
        runs in order: every `ACTIVE` division of the league becomes `SUSPENDED`;
        every `ACTIVE` tournament entry of the league becomes `WITHDRAWN`; every
        still-`SCHEDULED` game of those withdrawn entries becomes `CANCELLED`;
        and the league's `version` increments by 1."

        Design: Difficulty/transitive_cascade/charter_lapse_cascade_league_division_entry_game
        """
        ctx = setup_tournament_entry(league_name="Lapse LL")
        game = create_game(ctx["entry"]["id"])
        assert game["play_status"] == "SCHEDULED"

        # No renewal for 2028; jumping past the 2028 late-window close lapses.
        set_clock("2028-04-01T00:00:00Z")

        league = get_league(ctx["league"]["id"])
        assert league["charter_status"] == "SUSPENDED"
        division = get_division(major_division(ctx)["id"])
        assert division["status"] == "SUSPENDED"
        entry = get_entry(ctx["entry"]["id"])
        assert entry["status"] == "WITHDRAWN"
        game_after = get_game(game["id"])
        assert game_after["play_status"] == "CANCELLED"

    def test_suspension_sweep_bumps_the_league_version(self, api):
        """PRD §3.8: "The cascade then runs in order: every `ACTIVE` division of
        the league becomes `SUSPENDED`; every `ACTIVE` tournament entry of the
        league becomes `WITHDRAWN`; every still-`SCHEDULED` game of those
        withdrawn entries becomes `CANCELLED`; and the league's `version`
        increments by 1."

        Design: Difficulty/transitive_cascade/charter_lapse_cascade_league_division_entry_game
        """
        ctx = setup_tournament_entry(league_name="Lapse LL Two")
        before = get_league(ctx["league"]["id"])
        # create (1) + charter approval (1) = 2.
        assert before["version"] == 2
        set_clock("2028-04-01T00:00:00Z")
        after = get_league(ctx["league"]["id"])
        assert after["charter_status"] == "SUSPENDED"
        assert after["version"] == before["version"] + 1


class TestEligibilityRevocationCascade:
    """Revoking an ELIGIBLE player vacates the roster selection, withdraws the
    entry, and cancels its scheduled game."""

    def test_revocation_cascades_player_roster_entry_game(self, api):
        """PRD §3.4: "Revocation flips the player to `INELIGIBLE` and fires a
        deliberate cascade across the tournament side of the system. On every
        all-star roster holding an `ACTIVE` selection of this player, that
        selection becomes `VACATED` and the roster's `roster_size` is recomputed;
        if such a roster was `SUBMITTED` it is recalled to `RECALLED`, while a
        `LOCKED` roster stays `LOCKED` — a self-loop in which only the selection
        and the count change (§3.6). Every tournament entry with status `ACTIVE`
        whose roster contains — or contained — an `ACTIVE` selection of this
        player is withdrawn, and every still-`SCHEDULED` game of those entries
        is cancelled."

        Design: Difficulty/transitive_cascade/eligibility_revocation_cascade_player_roster_entry_game
        """
        ctx = setup_tournament_entry(n=4, league_name="Revoke LL")
        game = create_game(ctx["entry"]["id"])

        revoked = validate_success(api.revoke_eligibility(
            ctx["league"]["id"], ctx["players"][0]["id"],
            LA, {"reason": "residence audit failed"}), 200)
        assert revoked["eligibility_status"] == "INELIGIBLE"

        roster = get_roster(ctx["league"]["id"], ctx["roster"]["id"])
        # Entry creation locked the roster; the self-loop keeps it LOCKED.
        assert roster["status"] == "LOCKED"
        assert roster["roster_size"] == 3
        vacated = [s for s in roster["selections"]
                   if s["player_id"] == ctx["players"][0]["id"]]
        assert len(vacated) == 1
        assert vacated[0]["status"] == "VACATED"

        entry = get_entry(ctx["entry"]["id"])
        assert entry["status"] == "WITHDRAWN"
        game_after = get_game(game["id"])
        assert game_after["play_status"] == "CANCELLED"

    def test_revoked_player_selection_vacates_and_recomputes_roster_size(
            self, api):
        """PRD §3.6: "The roster's `roster_size` is maintained as an invariant:
        it is always exactly the count of selections whose status is `ACTIVE`,
        recomputed whenever a selection is added or vacated."
        PRD §3.6: "On a `LOCKED` roster the same revocation leaves the status
        untouched — a `LOCKED` → `LOCKED` self-loop in which the selection
        becomes `VACATED`, `roster_size` is recomputed, and the roster stays
        locked while the withdrawal cascade plays out on the tournament entry
        instead."

        Design: Difficulty/transitive_cascade/eligibility_revocation_cascade_player_roster_entry_game
        """
        ctx = setup_tournament_entry(n=4, league_name="Revoke LL Two")
        before = get_roster(ctx["league"]["id"], ctx["roster"]["id"])
        assert before["status"] == "LOCKED"
        assert before["roster_size"] == 4

        validate_success(api.revoke_eligibility(
            ctx["league"]["id"], ctx["players"][1]["id"], LA, {}), 200)

        after = get_roster(ctx["league"]["id"], ctx["roster"]["id"])
        assert after["roster_size"] == 3
        active = [s for s in after["selections"] if s["status"] == "ACTIVE"]
        assert len(active) == 3, (
            "roster_size must equal the count of ACTIVE selections")
        assert after["status"] == "LOCKED"

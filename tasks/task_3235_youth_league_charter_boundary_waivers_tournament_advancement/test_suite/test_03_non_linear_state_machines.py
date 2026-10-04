"""Non-linear state machines: the player eligibility cycle and the protest
driven game-reopen / elimination-reversal loop."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, charter_league, register_and_verify_player, verify_player,
    get_player, get_entry, get_game,
    setup_tournament_entry, create_game, record_appearance, finalize_game,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestPlayerEligibilityCycle:
    """PENDING -> ELIGIBLE -> INELIGIBLE -> ELIGIBLE is a legal loop."""

    def test_revoke_then_reverify_completes_the_cycle(self, api):
        """PRD §3.4: "Verification turns a `PENDING` player — or an `INELIGIBLE`
        one being reinstated — into `ELIGIBLE`, performed by a
        `LeagueAdministrator` through the player's verify-eligibility action."
        PRD §3.4: "A `LeagueAdministrator` may revoke eligibility, optionally
        attaching a `reason`, only for a player currently `ELIGIBLE`"

        Design: Difficulty/non_linear_state_machine/player_eligibility_revoke_reverify_cycle
        """
        ctx = charter_league(league_name="Cycle LL")
        set_clock("2027-02-01T00:00:00Z")
        player = register_and_verify_player(ctx["league"]["id"], last_name="Cle")
        assert player["eligibility_status"] == "ELIGIBLE"

        revoked = validate_success(api.revoke_eligibility(
            ctx["league"]["id"], player["id"],
            LA, {"reason": "boundary audit"}), 200)
        assert revoked["eligibility_status"] == "INELIGIBLE"

        reinstated = verify_player(ctx["league"]["id"], player["id"])
        assert reinstated["eligibility_status"] == "ELIGIBLE", (
            "re-verification from INELIGIBLE must complete the cycle")

    def test_each_leg_of_the_cycle_increments_the_player_version(self, api):
        """PRD §2.4: "Every resource with the standard common fields also carries
        `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three
        fractional digits, and a `version` integer that starts at its initial
        value on creation and increments by 1 on every mutation of that resource."

        Design: Difficulty/non_linear_state_machine/player_eligibility_revoke_reverify_cycle
        """
        ctx = charter_league(league_name="Cycle LL Two")
        set_clock("2027-02-01T00:00:00Z")
        player = register_and_verify_player(ctx["league"]["id"], last_name="Ver")
        # create (1) + verify (2).
        assert player["version"] == 2
        validate_success(api.revoke_eligibility(
            ctx["league"]["id"], player["id"], LA, {"reason": "audit"}), 200)
        assert get_player(player["id"])["version"] == 3
        reinstated = verify_player(ctx["league"]["id"], player["id"])
        assert reinstated["version"] == 4, (
            "four mutations (create + verify + revoke + verify) must yield "
            f"version 4, got {reinstated['version']}")


class TestProtestReopenReversesElimination:
    """An UPHELD RULE_INTERPRETATION protest reopens a FINAL game, voids its
    result, and resurrects an ELIMINATED entry; OVERTURN changes nothing."""

    def _setup_eliminated_with_protest(self, league_name):
        ctx = setup_tournament_entry(league_name=league_name)
        set_clock("2027-06-01T00:00:00Z")
        # Game 1: first loss (DOUBLE_ELIMINATION -> still ACTIVE).
        g1 = create_game(ctx["entry"]["id"])
        record_appearance(ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 10)
        finalize_game(ctx["entry"]["id"], g1["id"], 2, 5, g1["version"] + 1)
        # Game 2: second loss -> ELIMINATED.
        g2 = create_game(ctx["entry"]["id"])
        record_appearance(ctx["entry"]["id"], g2["id"], ctx["players"][1]["id"], 10)
        finalize_game(ctx["entry"]["id"], g2["id"], 1, 4, g2["version"] + 1)
        entry = get_entry(ctx["entry"]["id"])
        assert entry["status"] == "ELIMINATED"
        assert entry["losses_count"] == 2
        protest = get_success_data(api_client.file_protest(
            ctx["entry"]["id"], g2["id"],
            {"protest_type": "RULE_INTERPRETATION",
             "grounds": "mercy rule misapplied"}, TD))
        return ctx, g2, protest

    def test_upheld_rule_interpretation_reopens_game_and_reverses_elimination(
            self, api):
        """PRD §3.8: "Upholding a `RULE_INTERPRETATION` protest reopens the game:
        a `FINAL` game moves back to `IN_PROGRESS`, its `result` is cleared to
        null, and `our_score`/`opponent_score` are retained on the record but no
        longer authoritative. If the voided result had been a `LOSS`, the entry's
        `losses_count` is decremented by 1, and if that loss had previously
        pushed the entry to `ELIMINATED` by reaching the elimination limit, the
        entry is restored from `ELIMINATED` to `ACTIVE`. Because the game has
        reopened, its `protest_status` is then reset from `RESOLVED` to `NONE`,
        so the game can be protested again."

        Design: Difficulty/non_linear_state_machine/protest_uphold_reopens_final_game_and_reverses_elimination
        """
        ctx, g2, protest = self._setup_eliminated_with_protest("Reopen LL")
        resolved = validate_success(api.resolve_protest(
            ctx["entry"]["id"], g2["id"], protest["id"],
            {"action": "UPHOLD"}, TD), 200)
        assert resolved["status"] == "UPHELD"

        game = get_game(g2["id"])
        assert game["play_status"] == "IN_PROGRESS"
        assert game["result"] is None
        assert game["protest_status"] == "NONE"
        entry = get_entry(ctx["entry"]["id"])
        assert entry["status"] == "ACTIVE"
        assert entry["losses_count"] == 1

    def test_overturned_protest_leaves_every_counter_untouched(self, api):
        """PRD §3.8: "Overturning a protest lets everything stand — the game
        result, counters, and appearances are unchanged; only the protest moves
        to `OVERTURNED` and the game's `protest_status` to `RESOLVED`."

        Design: Difficulty/non_linear_state_machine/protest_uphold_reopens_final_game_and_reverses_elimination
        """
        ctx, g2, protest = self._setup_eliminated_with_protest("Overturn LL")
        resolved = validate_success(api.resolve_protest(
            ctx["entry"]["id"], g2["id"], protest["id"],
            {"action": "OVERTURN"}, TD), 200)
        assert resolved["status"] == "OVERTURNED"

        game = get_game(g2["id"])
        assert game["play_status"] == "FINAL"
        assert game["result"] == "LOSS"
        assert game["protest_status"] == "RESOLVED"
        entry = get_entry(ctx["entry"]["id"])
        assert entry["status"] == "ELIMINATED"
        assert entry["losses_count"] == 2

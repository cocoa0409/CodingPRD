"""Boundary precision: the 65/66 pitch rest-tier edge and the 60.00
participation threshold."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    ApiErrorId,
    set_clock, get_game, get_roster, major_division,
    charter_league, register_and_verify_player, create_open_roster,
    setup_tournament_entry, create_game, record_appearance,
)

LA = TEST_USERS["league_admin_headers"]


class TestPitchTierBoundary65Vs66:
    """One pitch flips the rest tier."""

    def test_65_pitches_lands_in_tier_3_and_66_in_tier_4(self, api):
        """PRD §3.7: "The tiers are closed intervals: 1 through 20 pitches
        require 0 rest days, 21 through 35 require 1 day, 36 through 50 require
        2 days, 51 through 65 require 3 days, and 66 pitches up to and including
        the division maximum require 4 days. The appearance's `eligible_again_on`
        is the `appearance_date` plus `rest_days_required` days."

        Design: Difficulty/boundary_precision_check/pitch_count_65_vs_66_rest_tier_boundary
        """
        ctx = setup_tournament_entry(league_name="Boundary Pitch LL")
        set_clock("2027-06-01T00:00:00Z")
        g1 = create_game(ctx["entry"]["id"])
        g2 = create_game(ctx["entry"]["id"])
        a65 = record_appearance(
            ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 65)
        a66 = record_appearance(
            ctx["entry"]["id"], g2["id"], ctx["players"][1]["id"], 66)
        assert a65["rest_days_required"] == 3
        assert a65["eligible_again_on"] == "2027-06-04"
        assert a66["rest_days_required"] == 4
        assert a66["eligible_again_on"] == "2027-06-05"

    def test_recorded_pitch_total_tracks_each_side_of_the_boundary(self, api):
        """PRD §3.7: "A recording that passes all three rules recomputes the
        game's `recorded_pitch_total` and bumps the game's `version` by 1."
        PRD §3.7: "The `recorded_pitch_total` is always exactly the sum over the
        game's `RECORDED` appearances of each appearance's effective count —
        `official_pitches` when set, else `pitches_thrown` — with `REVERSED`
        appearances contributing zero."

        Design: Difficulty/boundary_precision_check/pitch_count_65_vs_66_rest_tier_boundary
        """
        ctx = setup_tournament_entry(league_name="Boundary Pitch LL Two")
        set_clock("2027-06-01T00:00:00Z")
        g1 = create_game(ctx["entry"]["id"])
        g2 = create_game(ctx["entry"]["id"])
        record_appearance(ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 65)
        record_appearance(ctx["entry"]["id"], g2["id"], ctx["players"][1]["id"], 66)
        assert get_game(g1["id"])["recorded_pitch_total"] == 65
        assert get_game(g2["id"])["recorded_pitch_total"] == 66


class TestParticipationThreshold:
    """Exactly 60.00 passes; 55.56 and the zero-denominator 0.00 fail."""

    def _three_player_roster(self, league_name):
        ctx = charter_league(league_name=league_name)
        set_clock("2027-02-01T00:00:00Z")
        p60 = register_and_verify_player(
            ctx["league"]["id"], birth_date="2015-03-10",
            games_played=3, games_scheduled=5, last_name="Sixty")
        p55 = register_and_verify_player(
            ctx["league"]["id"], birth_date="2015-04-11",
            games_played=5, games_scheduled=9, last_name="FiftyFive")
        p0 = register_and_verify_player(
            ctx["league"]["id"], birth_date="2015-05-12",
            games_played=0, games_scheduled=0, last_name="Zero")
        roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
        return ctx, p60, p55, p0, roster

    def test_exactly_60_passes_and_55_56_fails(self, api):
        """PRD §3.3: "The participation threshold used by all-star selection is
        60.00, and a player at exactly 60.00 passes."
        PRD §3.6: "the player's `participation_pct` must be at least 60.00 —
        exactly 60.00 passes — or the add is rejected with
        `ERR_PARTICIPATION_THRESHOLD_NOT_MET` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/participation_exactly_60_passes_and_below_fails
        """
        ctx, p60, p55, _p0, roster = self._three_player_roster(
            "Participation LL")
        assert p60["participation_pct"] == pytest.approx(60.00, abs=0.001)
        assert p55["participation_pct"] == pytest.approx(55.56, abs=0.001)

        after = validate_success(api.add_roster_selection(
            ctx["league"]["id"], roster["id"], {"player_id": p60["id"]}, LA), 201)
        assert after["roster_size"] == 1

        err = validate_error(api.add_roster_selection(
            ctx["league"]["id"], roster["id"], {"player_id": p55["id"]}, LA),
            ApiErrorId.ERR_PARTICIPATION_THRESHOLD_NOT_MET)
        assert err["error_id"] == "ERR_PARTICIPATION_THRESHOLD_NOT_MET"
        assert get_roster(ctx["league"]["id"], roster["id"])["roster_size"] == 1

    def test_zero_denominator_computes_zero_and_fails(self, api):
        """PRD §3.3: "When `games_scheduled` is zero the percentage is 0.00.
        Otherwise it is one hundred times `games_played` divided by
        `games_scheduled`, rounded half up to two decimal places."
        PRD §3.6: "the player's `participation_pct` must be at least 60.00 —
        exactly 60.00 passes — or the add is rejected with
        `ERR_PARTICIPATION_THRESHOLD_NOT_MET` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/participation_exactly_60_passes_and_below_fails
        """
        ctx, _p60, _p55, p0, roster = self._three_player_roster(
            "Participation LL Two")
        assert p0["participation_pct"] == 0.00
        err = validate_error(api.add_roster_selection(
            ctx["league"]["id"], roster["id"], {"player_id": p0["id"]}, LA),
            ApiErrorId.ERR_PARTICIPATION_THRESHOLD_NOT_MET)
        assert err["error_id"] == "ERR_PARTICIPATION_THRESHOLD_NOT_MET"
        assert get_roster(ctx["league"]["id"], roster["id"])["roster_size"] == 0

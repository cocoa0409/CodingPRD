"""Dual-variant calculations: provisional vs final renewal fee, and provisional
vs official pitch-rest computation for the same appearance."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, validate_success, get_success_data,
    charter_league, set_clock, create_league_raw, add_insurance,
    patch_team_count, major_division, get_league, get_renewal, get_appearance,
    setup_tournament_entry, create_game, record_appearance,
    GAME_CLOCK,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestCharterFeeProvisionalVsFinal:
    """The two renewal-fee variants read team counts at different instants."""

    def _setup_team_counts_moved(self):
        """League season 2027, MINOR 2 + MAJOR 1 at submission (3 teams);
        TEE_BALL patched to 1 between submission and approval (4 teams)."""
        set_clock("2026-10-15T00:00:00Z")
        league, divisions = create_league_raw(league_name="Twin Rivers LL")
        add_insurance(league["id"])
        by_code = {d["division_code"]: d for d in divisions}
        patch_team_count(league["id"], by_code["MINOR"]["id"], 2)
        patch_team_count(league["id"], by_code["MAJOR"]["id"], 1)
        renewal = get_success_data(api_client.create_charter_renewal(
            league["id"], {"season_year": 2027}, LA))
        patch_team_count(league["id"], by_code["TEE_BALL"]["id"], 1)
        return league, renewal

    def test_provisional_fee_snapshots_submission_team_counts(self, api):
        """PRD §3.2: "Submission also computes the renewal's `provisional_fee_cents`.
        The fee is built line by line: one line of 50000 cents — the base charter
        fee, i.e. 500 dollars — plus one line per division of the league equal to
        that division's `team_count` multiplied by 7500 cents (75 dollars per team)."
        PRD §3.2: "The provisional fee freezes the division team counts as they
        exist at the moment of submission."

        Design: Difficulty/dual_variant_calc/charter_fee_provisional_vs_final_diverge_when_team_counts_move
        """
        league, renewal = self._setup_team_counts_moved()
        # At submission: MINOR 2 + MAJOR 1 -> 50000 + 2*7500 + 1*7500 = 72500.
        assert renewal["provisional_fee_cents"] == 72500, (
            "provisional fee must freeze the submission-time team counts "
            f"(3 teams), got {renewal['provisional_fee_cents']}")
        # The TEE_BALL patch between submission and approval must not have
        # retroactively changed the provisional snapshot.
        reread = get_renewal(renewal["id"])
        assert reread["provisional_fee_cents"] == 72500

    def test_final_fee_recomputes_at_approval_and_diverges(self, api):
        """PRD §3.2: "An approved renewal recomputes the fee as `final_fee_cents`,
        using the same line-by-line construction — base fee, per-team lines, the
        1.175 late multiplier with per-line rounding when `LATE` — but reading the
        divisions' `team_count` values as they exist at approval time rather than
        submission time. The final fee therefore diverges from the provisional fee
        whenever team counts changed in between; until a renewal is approved,
        `final_fee_cents` is null."

        Design: Difficulty/dual_variant_calc/charter_fee_provisional_vs_final_diverge_when_team_counts_move
        """
        league, renewal = self._setup_team_counts_moved()
        decided = validate_success(api.decide_charter_renewal(
            league["id"], renewal["id"],
            {"action": "APPROVE", "late_fee_paid": False}, DA), 200)
        # At approval: 4 teams -> 50000 + 4*7500 = 80000.
        assert decided["provisional_fee_cents"] == 72500
        assert decided["final_fee_cents"] == 80000, (
            "final fee must read approval-time team counts (4 teams), got "
            f"{decided['final_fee_cents']}")
        assert decided["final_fee_cents"] - decided["provisional_fee_cents"] == 7500
        after = get_league(league["id"])
        assert after["charter_status"] == "CHARTERED"


class TestPitchRestProvisionalVsOfficial:
    """The two pitch-rest variants compute eligible_again_on from different
    effective pitch counts for the same appearance."""

    def test_correction_crossing_tier_boundary_changes_eligible_again_on(self, api):
        """PRD §3.7: "each correction writes `official_pitches` onto the named
        appearance (null until corrected), and for that appearance the effective
        pitch count becomes the `official_pitches` value rather than
        `pitches_thrown`; the `rest_days_required` and `eligible_again_on` are
        recomputed from the corrected count using the same tier table, so a
        correction that crosses a tier boundary — say from 60 to 70 pitches —
        changes the same appearance's rest window."

        Design: Difficulty/dual_variant_calc/pitch_rest_provisional_vs_official_after_scorebook_correction
        """
        ctx = setup_tournament_entry(league_name="Rest Valley LL")
        set_clock(GAME_CLOCK)
        game = create_game(ctx["entry"]["id"])
        appearance = record_appearance(
            ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 60)
        # Provisional variant: 60 pitches -> tier 51..65 -> 3 days.
        assert appearance["rest_days_required"] == 3
        assert appearance["eligible_again_on"] == "2027-06-04"

        validate_success(api.finalize_game(
            ctx["entry"]["id"], game["id"],
            {"our_score": 5, "opponent_score": 3,
             "expected_game_version": game["version"] + 1,
             "scorebook_corrections": [
                 {"appearance_id": appearance["id"], "official_pitches": 70}]},
            TD), 200)

        corrected = get_appearance(appearance["id"])
        assert corrected["official_pitches"] == 70
        # Official variant: 70 pitches -> tier 66..cap -> 4 days.
        assert corrected["rest_days_required"] == 4
        assert corrected["eligible_again_on"] == "2027-06-05"
        assert corrected["eligible_again_on"] != appearance["eligible_again_on"]

    def test_provisional_rest_uses_reported_pitches_at_recording(self, api):
        """PRD §3.7: "the rest tier: the appearance's `rest_days_required` is
        computed from the effective pitch count, which at recording time is
        simply `pitches_thrown`. The tiers are closed intervals: 1 through 20
        pitches require 0 rest days, 21 through 35 require 1 day, 36 through 50
        require 2 days, 51 through 65 require 3 days, and 66 pitches up to and
        including the division maximum require 4 days. The appearance's
        `eligible_again_on` is the `appearance_date` plus `rest_days_required`
        days."

        Design: Difficulty/dual_variant_calc/pitch_rest_provisional_vs_official_after_scorebook_correction
        """
        ctx = setup_tournament_entry(league_name="Rest Valley LL 2")
        set_clock(GAME_CLOCK)
        game = create_game(ctx["entry"]["id"])
        a60 = record_appearance(
            ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 60)
        a70 = record_appearance(
            ctx["entry"]["id"], game["id"], ctx["players"][1]["id"], 70)
        # Same appearance_date, two different provisional rest windows.
        assert a60["rest_days_required"] == 3
        assert a60["eligible_again_on"] == "2027-06-04"
        assert a70["rest_days_required"] == 4
        assert a70["eligible_again_on"] == "2027-06-05"
        assert a60["official_pitches"] is None
        assert a70["official_pitches"] is None

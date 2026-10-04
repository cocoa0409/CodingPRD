"""Combinatorial formulas: the tiered pitch-rest gate interacting with the
division cap, and the pinned per-line rounding order for late renewal fees."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, create_league_raw, add_insurance, patch_team_count,
    submit_renewal, get_game,
    setup_tournament_entry, create_game, record_appearance,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestPitchRestTieredGate:
    """A 70-pitch outing blocks the next appearance until the rest gate clears,
    and exactly the division cap is permitted once eligible again."""

    def test_rest_gate_blocks_strictly_before_eligible_again_on(self, api):
        """PRD §3.7: "the rest gate: recording a new appearance for a player is
        rejected with `ERR_REST_REQUIREMENT_VIOLATION` (HTTP 409) when the clock
        date falls strictly before the `eligible_again_on` of that player's
        latest `RECORDED` appearance — latest by `appearance_date`, with ties
        broken by `created_at` ascending so that the appearance with the later
        `created_at` counts as the latest."

        Design: Difficulty/combinatorial_formula/pitch_rest_tiered_gate_three_input_interaction
        """
        ctx = setup_tournament_entry(league_name="Tier Gate LL")
        set_clock("2027-06-01T00:00:00Z")
        g1 = create_game(ctx["entry"]["id"])
        # 70 pitches in MAJOR -> tier 66..85 -> 4 days -> eligible again 2027-06-05.
        first = record_appearance(
            ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 70)
        assert first["eligible_again_on"] == "2027-06-05"
        g2 = create_game(ctx["entry"]["id"])

        set_clock("2027-06-04T00:00:00Z")
        err = validate_error(
            api.record_pitching_appearance(
                ctx["entry"]["id"], g2["id"],
                {"player_id": ctx["players"][0]["id"], "pitches_thrown": 10},
                TEST_USERS["official_scorer_headers"]),
            ApiErrorId.ERR_REST_REQUIREMENT_VIOLATION)
        assert err["error_id"] == "ERR_REST_REQUIREMENT_VIOLATION"
        # One day later the gate clears and exactly the cap (85) is permitted.
        set_clock("2027-06-05T00:00:00Z")
        second = record_appearance(
            ctx["entry"]["id"], g2["id"], ctx["players"][0]["id"], 85)
        assert second["pitches_thrown"] == 85

    def test_cap_inclusive_and_tier_recompute_on_second_appearance(self, api):
        """PRD §3.7: "at recording time, the reported `pitches_thrown` must not
        exceed the pitch maximum of the player's division — 50 for `TEE_BALL`,
        75 for `MINOR`, 85 for `MAJOR`, 95 for `JUNIOR`, and 95 for `SENIOR` —
        or the recording is rejected with `ERR_PITCH_COUNT_EXCEEDED` (HTTP 422)."
        PRD §3.7: "66 pitches up to and including the division maximum require
        4 days. The appearance's `eligible_again_on` is the `appearance_date`
        plus `rest_days_required` days."

        Design: Difficulty/combinatorial_formula/pitch_rest_tiered_gate_three_input_interaction
        """
        ctx = setup_tournament_entry(league_name="Tier Gate LL Two")
        set_clock("2027-06-01T00:00:00Z")
        g1 = create_game(ctx["entry"]["id"])
        record_appearance(ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 70)
        g2 = create_game(ctx["entry"]["id"])

        set_clock("2027-06-05T00:00:00Z")
        # 85 == MAJOR cap: permitted, tier 66..85 -> 4 days -> 2027-06-09.
        a2 = record_appearance(
            ctx["entry"]["id"], g2["id"], ctx["players"][0]["id"], 85)
        assert a2["rest_days_required"] == 4
        assert a2["eligible_again_on"] == "2027-06-09"
        game2 = get_game(g2["id"])
        assert game2["recorded_pitch_total"] == 85


class TestLateRenewalPerLineRounding:
    """Per-line multiply-and-round first, then sum."""

    def _late_renewal_ctx(self):
        set_clock("2026-10-15T00:00:00Z")
        league, divisions = create_league_raw(league_name="Late Fee LL")
        add_insurance(league["id"])
        by_code = {d["division_code"]: d for d in divisions}
        patch_team_count(league["id"], by_code["TEE_BALL"]["id"], 1)
        patch_team_count(league["id"], by_code["MINOR"]["id"], 1)
        set_clock("2027-02-01T00:00:00Z")
        renewal = submit_renewal(league["id"])
        return league, renewal

    def test_provisional_late_fee_rounds_each_line_before_summing(self, api):
        """PRD §3.2: "For a `LATE` submission each line is first multiplied by
        1.175 and rounded half up to integer cents, and the fee is the sum of
        those rounded lines. The rounding order is pinned: multiply and round
        each line to whole cents first, then sum. Rounding the grand total
        instead would produce different cent values and is not permitted."

        Design: Difficulty/combinatorial_formula/late_renewal_fee_per_line_rounding_beats_total_rounding
        """
        league, renewal = self._late_renewal_ctx()
        assert renewal["window_classification"] == "LATE"
        # Per line: round(50000*1.175)=58750; round(7500*1.175)=8813 (x2).
        # Sum = 58750 + 8813 + 8813 = 76376. Total-first rounding of
        # 65000*1.175 would be 76375 — the pinned order yields 76376.
        assert renewal["provisional_fee_cents"] == 76376, (
            "per-line rounding must produce 76376, got "
            f"{renewal['provisional_fee_cents']}")

    def test_final_late_fee_matches_when_team_counts_unchanged(self, api):
        """PRD §3.2: "An approved renewal recomputes the fee as `final_fee_cents`,
        using the same line-by-line construction — base fee, per-team lines, the
        1.175 late multiplier with per-line rounding when `LATE` — but reading
        the divisions' `team_count` values as they exist at approval time rather
        than submission time."

        Design: Difficulty/combinatorial_formula/late_renewal_fee_per_line_rounding_beats_total_rounding
        """
        league, renewal = self._late_renewal_ctx()
        decided = validate_success(api.decide_charter_renewal(
            league["id"], renewal["id"],
            {"action": "APPROVE", "late_fee_paid": True}, DA), 200)
        # Team counts unchanged between submission and approval: same lines.
        assert decided["final_fee_cents"] == 76376
        assert decided["provisional_fee_cents"] == 76376

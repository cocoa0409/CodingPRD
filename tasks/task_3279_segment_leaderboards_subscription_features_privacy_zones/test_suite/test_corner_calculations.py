"""Calculation corner claims: rank tie-breaks, rank recompute on exclusion,
and category-correction exclusion."""

from test_helpers import (
    assert_leaderboard_ranks,
    create_active_segment,
    create_athlete,
    create_activity_with_effort,
    flag_effort,
    make_athlete_headers,
    uphold_flag,
    validate_success,
)


class TestRankTieBrokenByCreatedAt:
    def test_equal_times_rank_by_creation_order(self, api):
        """PRD 3.5: "A segment's **leaderboard** is the ordered list of its `ELIGIBLE` efforts, sorted by `elapsed_time_s` ascending with ties broken by the effort's `created_at` ascending — never by id."

        Design: Corner/calculations/rank_tie_broken_by_created_at
        """
        creator = create_athlete(api, email="rt1@x.com", display_name="RT1")
        early = create_athlete(api, email="rt2@x.com", display_name="RT2")
        late = create_athlete(api, email="rt3@x.com", display_name="RT3")
        segment = create_active_segment(
            api, creator["id"], name="Tie Run", sport_type="RUN",
            start_lat=53.00, start_lng=-138.00, end_lat=53.01, end_lng=-138.00,
            distance_m=1000, city="Tieville",
        )
        create_activity_with_effort(api, segment, early["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        create_activity_with_effort(api, segment, late["id"], elapsed_time_s=100, started_at="2026-09-01T07:00:00Z")
        board = validate_success(
            api.get_leaderboard(segment["id"], make_athlete_headers(creator["id"])), 200
        )
        assert len(board) == 2
        assert_leaderboard_ranks(board)
        assert board[0]["athlete_id"] == early["id"]
        assert board[1]["athlete_id"] == late["id"]

    def test_faster_effort_ranks_first_despite_later_creation(self, api):
        """PRD 3.5: "sorted by `elapsed_time_s` ascending with ties broken by the effort's `created_at` ascending".

        Design: Corner/calculations/rank_tie_broken_by_created_at
        """
        creator = create_athlete(api, email="rt4@x.com", display_name="RT4")
        slow = create_athlete(api, email="rt5@x.com", display_name="RT5")
        fast = create_athlete(api, email="rt6@x.com", display_name="RT6")
        segment = create_active_segment(api, creator["id"], sport_type="RUN", distance_m=1000)
        create_activity_with_effort(api, segment, slow["id"], elapsed_time_s=120, started_at="2026-09-01T06:00:00Z")
        create_activity_with_effort(api, segment, fast["id"], elapsed_time_s=100, started_at="2026-09-01T07:00:00Z")
        board = validate_success(api.get_leaderboard(segment["id"], make_athlete_headers(creator["id"])), 200)
        assert [row["athlete_id"] for row in board] == [fast["id"], slow["id"]]
        assert_leaderboard_ranks(board)


class TestEffortExclusionRecomputesRanks:
    def test_upheld_exclusion_promotes_next_effort(self, api):
        """PRD 3.6: "Whenever an effort leaves `ELIGIBLE`, rank snapshots for the remaining eligible efforts on its segment are recomputed."
        PRD 3.5: "Each effort carries a `rank_snapshot`: its one-based position in that ordering, refreshed on every leaderboard-relevant mutation".

        Design: Corner/calculations/effort_exclusion_recomputes_ranks
        """
        flagger = create_athlete(api, email="rx_c@x.com", display_name="RX C")
        athlete_a = create_athlete(api, email="rx_a@x.com", display_name="RX A")
        athlete_b = create_athlete(api, email="rx_b@x.com", display_name="RX B")
        segment = create_active_segment(
            api, flagger["id"], name="Recompute Run", sport_type="RUN",
            start_lat=54.00, start_lng=-139.00, end_lat=54.01, end_lng=-139.00,
            distance_m=1000, city="Recompville",
        )
        pair_a = create_activity_with_effort(api, segment, athlete_a["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        pair_b = create_activity_with_effort(api, segment, athlete_b["id"], elapsed_time_s=110, started_at="2026-09-01T07:00:00Z")
        before = validate_success(api.get_effort(pair_b["effort"]["id"], make_athlete_headers(athlete_b["id"])), 200)
        assert before["rank_snapshot"] == 2
        flag = flag_effort(api, pair_a["effort"]["id"], flagger["id"], reason="VEHICLE_ASSISTED")
        uphold_flag(api, flag["id"])
        after = validate_success(api.get_effort(pair_b["effort"]["id"], make_athlete_headers(athlete_b["id"])), 200)
        assert after["rank_snapshot"] == 1

    def test_excluded_effort_removed_from_leaderboard(self, api):
        """PRD 3.5: "A segment's **leaderboard** is the ordered list of its `ELIGIBLE` efforts".
        PRD 3.6: "**Upholding** a flag moves it to `UPHELD` and triggers the confirmation cascade: the effort moves from `FLAGGED` to `EXCLUDED` with `exclusion_reason` `FLAG_UPHELD`".

        Design: Corner/calculations/effort_exclusion_recomputes_ranks
        """
        flagger = create_athlete(api, email="rx_d@x.com", display_name="RX D")
        athlete_a = create_athlete(api, email="rx_e@x.com", display_name="RX E")
        athlete_b = create_athlete(api, email="rx_f@x.com", display_name="RX F")
        segment = create_active_segment(api, flagger["id"], sport_type="RUN", distance_m=1000)
        pair_a = create_activity_with_effort(api, segment, athlete_a["id"], elapsed_time_s=90, started_at="2026-09-01T06:00:00Z")
        create_activity_with_effort(api, segment, athlete_b["id"], elapsed_time_s=100, started_at="2026-09-01T07:00:00Z")
        flag = flag_effort(api, pair_a["effort"]["id"], flagger["id"], reason="VEHICLE_ASSISTED")
        uphold_flag(api, flag["id"])
        board = validate_success(api.get_leaderboard(segment["id"], make_athlete_headers(flagger["id"])), 200)
        assert [row["athlete_id"] for row in board] == [athlete_b["id"]]
        excluded = validate_success(api.get_effort(pair_a["effort"]["id"], make_athlete_headers(athlete_a["id"])), 200)
        assert excluded["flag_status"] == "EXCLUDED"
        assert excluded["exclusion_reason"] == "FLAG_UPHELD"


class TestCategoryCorrectionExcludesEfforts:
    def test_run_to_ride_correction_excludes_run_segment_effort(self, api):
        """PRD 3.4: "A correction re-runs eligibility: every still-`ELIGIBLE` effort whose segment's `sport_type` no longer matches the corrected category is excluded with `exclusion_reason` `CATEGORY_MISMATCH`".

        Design: Corner/calculations/category_correction_excludes_efforts
        """
        creator = create_athlete(api, email="cc_c@x.com", display_name="CC C")
        owner = create_athlete(api, email="ca_c@x.com", display_name="CA C")
        segment = create_active_segment(
            api, creator["id"], name="Correction Run", sport_type="RUN",
            start_lat=55.00, start_lng=-140.00, end_lat=55.01, end_lng=-140.00,
            distance_m=1000, city="Correctville",
        )
        pair = create_activity_with_effort(api, segment, owner["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        assert pair["effort"]["flag_status"] == "ELIGIBLE"
        validate_success(
            api.correct_activity_category(pair["activity"]["id"], "RIDE", make_athlete_headers(owner["id"])), 200
        )
        after = validate_success(api.get_effort(pair["effort"]["id"], make_athlete_headers(owner["id"])), 200)
        assert after["flag_status"] == "EXCLUDED"
        assert after["exclusion_reason"] == "CATEGORY_MISMATCH"

    def test_correction_drops_effort_from_leaderboard(self, api):
        """PRD 3.5: "A segment's **leaderboard** is the ordered list of its `ELIGIBLE` efforts".
        PRD 3.4: "every still-`ELIGIBLE` effort whose segment's `sport_type` no longer matches the corrected category is excluded with `exclusion_reason` `CATEGORY_MISMATCH`".

        Design: Corner/calculations/category_correction_excludes_efforts
        """
        creator = create_athlete(api, email="cc_d@x.com", display_name="CC D")
        owner = create_athlete(api, email="ca_d@x.com", display_name="CA D")
        segment = create_active_segment(api, creator["id"], sport_type="RUN", distance_m=1000)
        pair = create_activity_with_effort(api, segment, owner["id"], elapsed_time_s=100)
        validate_success(api.get_leaderboard(segment["id"], make_athlete_headers(creator["id"])), 200)
        validate_success(
            api.correct_activity_category(pair["activity"]["id"], "SWIM", make_athlete_headers(owner["id"])), 200
        )
        board = validate_success(api.get_leaderboard(segment["id"], make_athlete_headers(creator["id"])), 200)
        assert board == []

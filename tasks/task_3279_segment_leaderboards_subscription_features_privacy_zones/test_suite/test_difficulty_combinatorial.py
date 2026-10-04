"""Difficulty queue A: combinatorial formulas.

speed_gate_mode_a covers the tiered speed/assist-factor speed check with its
strict-less-than boundary; route_load_mode_c covers the pinned evaluation
order of the route load score with its conditional spike bonus.
"""

from test_helpers import (
    create_active_segment,
    create_athlete,
    create_route_plan,
    create_subscription,
    upload_activity,
    validate_success,
)


class TestSpeedGateModeA:
    def _segment(self, api, suffix):
        creator = create_athlete(api, email=f"r_spd{suffix}@x.com", display_name=f"R Spd{suffix}")
        segment = create_active_segment(
            api, creator["id"], name=f"Speed Gate 500 {suffix}", sport_type="RIDE",
            start_lat=37.50, start_lng=-122.50, end_lat=37.505, end_lng=-122.50,
            distance_m=500, city="Speedtown",
        )
        return creator, segment

    def _ride_effort(self, api, segment, rider_id, elapsed, started_at, key):
        activity = upload_activity(
            api, rider_id,
            device_source="garmin-edge", sport_type="RIDE", started_at=started_at,
            duration_s=elapsed, distance_m=500,
            track_points=[
                {"lat": 37.50, "lng": -122.50, "t_offset_s": 0},
                {"lat": 37.505, "lng": -122.50, "t_offset_s": elapsed},
            ],
            start_lat=37.50, start_lng=-122.50, end_lat=37.505, end_lng=-122.50,
            idempotency_key=key,
            effort_hints=[{"segment_id": segment["id"], "elapsed_time_s": elapsed, "elevation_gain_m": 0}],
        )
        from test_helpers import make_athlete_headers

        efforts = validate_success(
            api.list_efforts(make_athlete_headers(rider_id), params={"activity_id": activity["id"]}), 200
        )
        assert len(efforts) == 1
        return efforts[0]

    def test_one_second_below_threshold_flagged_speed_impossible(self, api):
        """PRD 3.4: "The comparison is strict and performed in unrounded double precision: an elapsed time exactly equal to the threshold passes, while anything faster flags the effort as `SPEED_IMPOSSIBLE`. For example, on a 500-meter `RIDE` segment the threshold works out to exactly 18 seconds, so a 17-second effort is flagged while an 18-second effort passes".

        Design: Difficulty/combinatorial_formula/speed_gate_mode_a
        """
        _, segment = self._segment(api, "a")
        rider = create_athlete(api, email="o_spda@x.com", display_name="O SpdA")
        effort = self._ride_effort(api, segment, rider["id"], 17, "2026-09-01T10:00:00Z", "spd-a-fast")
        assert effort["flag_status"] == "FLAGGED"
        assert effort["exclusion_reason"] == "SPEED_IMPOSSIBLE"

    def test_exactly_at_threshold_passes_with_rounded_speed(self, api):
        """PRD 3.4: "an elapsed time exactly equal to the threshold passes".
        PRD 3.4: "The effort's `avg_speed_kmh` is then computed as its `distance_m` divided by its `elapsed_time_s` and multiplied by 3.6, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/speed_gate_mode_a
        """
        _, segment = self._segment(api, "b")
        rider = create_athlete(api, email="o_spdb@x.com", display_name="O SpdB")
        effort = self._ride_effort(api, segment, rider["id"], 18, "2026-09-01T11:00:00Z", "spd-b-edge")
        assert effort["flag_status"] == "ELIGIBLE"
        assert effort["avg_speed_kmh"] == 100.0


class TestRouteLoadModeC:
    def _subscribed_rider_with_base(self, api, email, key_prefix):
        athlete = create_athlete(api, email=email, display_name="L Load")
        create_subscription(api, athlete["id"], started_at="2026-08-01T00:00:00Z", expires_at="2027-08-01T00:00:00Z")
        for started, key in (("2026-08-25T10:00:00Z", f"{key_prefix}-1"), ("2026-08-28T10:00:00Z", f"{key_prefix}-2")):
            upload_activity(
                api, athlete["id"],
                device_source="wahoo-elemnt", sport_type="RIDE", started_at=started,
                duration_s=7200, distance_m=60000,
                track_points=[
                    {"lat": 37.20, "lng": -122.20, "t_offset_s": 0},
                    {"lat": 37.60, "lng": -122.20, "t_offset_s": 7200},
                ],
                start_lat=37.20, start_lng=-122.20, end_lat=37.60, end_lng=-122.20,
                idempotency_key=key,
            )
        return athlete

    def test_spike_bonus_applies_when_plan_exceeds_one_and_a_half_times_recent(self, api):
        """PRD 3.8: "Each plan computes an `estimated_load_score` at creation: first sum the `distance_m` of the athlete's `COMPLETED` activities — any sport — whose `started_at` falls in the trailing 28 days before `week_start` (zero when there are none); then take the plan's `distance_m` divided by 1000, add the recent-distance sum divided by 2000; and, when the recent-distance sum is greater than zero and the plan's distance exceeds one and a half times that sum, add a further 25 as a spike bonus. The result is rounded half-up to one decimal place."

        Design: Difficulty/combinatorial_formula/route_load_mode_c
        """
        athlete = self._subscribed_rider_with_base(api, "l_load@x.com", "load")
        plan = create_route_plan(
            api, athlete["id"],
            name="Big Sunday",
            waypoints=[{"lat": 37.20, "lng": -122.20}, {"lat": 38.20, "lng": -122.20}],
            distance_m=200000, week_start="2026-09-07",
        )
        # recent = 120000; raw = 200000/1000 + 120000/2000 = 260.0;
        # 200000 > 120000 * 1.5 -> +25 bonus; round_half_up(285.0, 1) == 285.0
        assert plan["estimated_load_score"] == 285.0

    def test_no_bonus_when_plan_within_one_and_a_half_times_recent(self, api):
        """PRD 3.8: "when the recent-distance sum is greater than zero and the plan's distance exceeds one and a half times that sum, add a further 25 as a spike bonus" — at or below 1.5x the bonus does not apply.

        Design: Difficulty/combinatorial_formula/route_load_mode_c
        """
        athlete = self._subscribed_rider_with_base(api, "l_load2@x.com", "load2")
        plan = create_route_plan(
            api, athlete["id"],
            name="Steady Sunday",
            waypoints=[{"lat": 37.20, "lng": -122.20}, {"lat": 38.20, "lng": -122.20}],
            distance_m=180000, week_start="2026-09-07",
        )
        # 180000 > 120000 * 1.5 is false (180000 == 180000, "exceeds" is strict)
        # raw = 180 + 60 = 240.0, no bonus.
        assert plan["estimated_load_score"] == 240.0

"""Trips: distance aggregation, speed events, driver score, trip uniqueness."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    get_success_data,
    invite_and_grant_member,
    make_member_headers,
    post_fix,
    reset_clock,
    set_clock,
    start_trip,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def _closed_trips(api, circle_id, member_id, headers):
    resp = api.list_trips(circle_id, member_id, headers, params={"trip_status": "CLOSED"})
    data, _meta = validate_paginated(resp)
    return data


class TestTripDistance:
    def test_trip_distance_mode_b_per_segment_rounding(self, api, system_headers):
        """PRD §3.6: "The `distance_m` is the sum, over each consecutive pair of
        `ACCEPTED` `DRIVING` fixes within the trip's window, of the haversine
        distance between the pair — and the rounding is per-segment: each leg
        is rounded half-up to a whole metre before being added to the running
        total. Computing haversine on the full polyline and rounding once at
        the end is forbidden and produces a different value."
        PRD §2.9: "Haversine distances are computed to one decimal place
        (0.1 m) using an earth radius of 6,371,000 metres"

        Design: Difficulty/combinatorial_formula/trip_distance_mode_b_per_segment_rounding
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="DistFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 lat=37.7700, lng=-122.4194, speed_mps=20.0, battery_pct=90,
                 motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:01:00Z",
                 lat=37.7800, lng=-122.4194, speed_mps=20.0, battery_pct=89,
                 motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z",
                 lat=37.7900, lng=-122.4194, speed_mps=20.0, battery_pct=88,
                 motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:03:00Z",
                 lat=37.7900, lng=-122.4194, speed_mps=0.0, battery_pct=88,
                 motion_context="STILL")
        trips = _closed_trips(api, circle["id"], owner_id, owner_headers)
        assert len(trips) == 1
        # Each leg is 1111.949 m -> round_half_up -> 1112; two legs sum to 2224.
        assert trips[0]["distance_m"] == 2224

    def test_trip_distance_excludes_non_driving_legs(self, api, system_headers):
        """PRD §3.6: "The pair sequence is the member's accepted `DRIVING` fixes
        whose `recorded_at` falls within the trip's `started_at`-to-`ended_at`
        window, ordered by `recorded_at` ascending with ties broken by
        `created_at` ascending."

        Design: Difficulty/combinatorial_formula/trip_distance_mode_b_per_segment_rounding
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="DistFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 lat=37.7000, speed_mps=20.0, motion_context="DRIVING")
        # Closing fix far away must NOT contribute a leg to the distance.
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:01:00Z",
                 lat=37.7900, speed_mps=0.0, motion_context="STILL")
        trips = _closed_trips(api, circle["id"], owner_id, owner_headers)
        assert len(trips) == 1
        assert trips[0]["distance_m"] == 0


class TestSpeedEvents:
    def test_speed_event_not_counted_when_both_fixes_below_threshold(self, api, system_headers):
        """PRD §3.6: "The `speed_event_count` counts consecutive-fix pairs whose
        average speed exceeds the tier's speed-event threshold."

        Design: Corner/calculations/speed_event_counted_only_when_pair_avg_exceeds_threshold
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="SpeedFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 lat=37.7000, speed_mps=20.0, battery_pct=90, motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:30Z",
                 lat=37.7005, speed_mps=26.0, battery_pct=89, motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z",
                 lat=37.7005, speed_mps=0.0, battery_pct=88, motion_context="STILL")
        trips = _closed_trips(api, circle["id"], owner_id, owner_headers)
        assert len(trips) == 1
        # Pair (20,26) averages 23 — does not exceed 27 -> zero events.
        assert trips[0]["speed_event_count"] == 0


class TestDriverScoreVariants:
    def test_driver_score_trip_level_vs_rolling_30d(self, api, system_headers):
        """PRD §3.6: "The score starts at 100 and subtracts three penalties: 8
        points per speed event, capped at 5 events; 5 points per phone-use
        event, capped at 6 events; and 1 point per whole mile of distance,
        where a mile is 1,609 metres and the per-mile count is the floor of
        `distance_m` divided by 1,609. The result is clamped to the inclusive
        range from 0 to 100 and is an integer. The trip-level variant is
        computed when a trip closes, against that single trip's aggregates, and
        is written to the trip's `driver_score`. The rolling variant is computed
        on read of the member's driver profile against all of the member's
        `CLOSED` trips whose `ended_at` is within the trailing 30 days and
        whose consent was `GRANTED` at end time; `ABANDONED` trips are excluded
        from both variants. The rolling variant is never persisted on the trip
        row — the same physical trips can produce a different rolling score
        than the trip-level view."

        Design: Difficulty/dual_variant_calc/driver_score_trip_level_vs_rolling_30d
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="ScoreFam")
        teo = invite_and_grant_member(circle, owner_headers, display_name="Teo", email="teo@example.com")
        teo_headers = make_member_headers(teo["id"])
        # Trip A: constant 30 m/s, one phone-use fix at speed 30,
        # distance ~22239 m (20 legs of ~1112 m). The logical clock is
        # advanced alongside recorded_at so every fix stays within the
        # 300 s ingestion skew window (PRD §3.4).
        for i in range(21):
            lat = round(37.7000 + 0.0100 * i, 6)
            ts = f"2026-09-01T00:{i:02d}:00Z"
            set_clock(ts)
            post_fix(circle, teo, teo_headers,
                     recorded_at=ts,
                     lat=lat, speed_mps=30.0, battery_pct=90,
                     phone_in_use=(i == 1), motion_context="DRIVING")
        set_clock("2026-09-01T00:21:00Z")
        post_fix(circle, teo, teo_headers, recorded_at="2026-09-01T00:21:00Z",
                 lat=37.9000, speed_mps=0.0, battery_pct=89, motion_context="STILL")
        # Trip B: constant 20 m/s, no phone use, 1 leg of ~1112 m.
        set_clock("2026-09-01T02:00:00Z")
        post_fix(circle, teo, teo_headers, recorded_at="2026-09-01T02:00:00Z",
                 lat=37.7000, speed_mps=20.0, battery_pct=80, motion_context="DRIVING")
        set_clock("2026-09-01T02:01:00Z")
        post_fix(circle, teo, teo_headers, recorded_at="2026-09-01T02:01:00Z",
                 lat=37.7100, speed_mps=20.0, battery_pct=79, motion_context="DRIVING")
        set_clock("2026-09-01T02:02:00Z")
        post_fix(circle, teo, teo_headers, recorded_at="2026-09-01T02:02:00Z",
                 lat=37.7100, speed_mps=0.0, battery_pct=79, motion_context="STILL")
        trips = _closed_trips(api, circle["id"], teo["id"], teo_headers)
        assert len(trips) == 2
        # Trip A is identified by its phone-use fix (PRD pins phone events as
        # phone_in_use && speed_mps >= 1.0); trip B has none. The numeric
        # speed-event threshold is not stated in the PRD, so the formula
        # checks below read speed_event_count back from the response rather
        # than assuming a threshold value.
        trip_a = next(t for t in trips if t["phone_use_event_count"] > 0)
        trip_b = next(t for t in trips if t["phone_use_event_count"] == 0)
        # Trip A: speed events capped at 5; phone events 1; miles floor(distance/1609)
        assert trip_a["phone_use_event_count"] == 1
        expected_a = 100 - 8 * min(trip_a["speed_event_count"], 5) - 5 * 1 - (trip_a["distance_m"] // 1609)
        assert trip_a["driver_score"] == expected_a
        # Trip B: 0 phone events; miles floor(distance/1609)
        assert trip_b["phone_use_event_count"] == 0
        expected_b = 100 - 8 * min(trip_b["speed_event_count"], 5) - (trip_b["distance_m"] // 1609)
        assert trip_b["driver_score"] == expected_b

    def test_driver_score_persisted_trip_value_unchanged_by_later_trips(self, api, system_headers):
        """PRD §3.6: "The trip-level variant is computed when a trip closes,
        against that single trip's aggregates, and is written to the trip's
        `driver_score`."
        PRD §3.6: "The rolling variant is never persisted on the trip row — the
        same physical trips can produce a different rolling score than the
        trip-level view."

        Design: Difficulty/dual_variant_calc/driver_score_trip_level_vs_rolling_30d
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="ScoreFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        # Trip 1: clean drive, one leg (no phone use). The logical clock is
        # advanced alongside recorded_at so fixes stay within the 300 s
        # ingestion skew window (PRD §3.4).
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 lat=37.7000, speed_mps=20.0, motion_context="DRIVING")
        set_clock("2026-09-01T00:01:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:01:00Z",
                 lat=37.7100, speed_mps=20.0, motion_context="DRIVING")
        set_clock("2026-09-01T00:02:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z",
                 lat=37.7100, speed_mps=0.0, motion_context="STILL")
        trips1 = _closed_trips(api, circle["id"], owner_id, owner_headers)
        assert len(trips1) == 1
        first_score = trips1[0]["driver_score"]
        first_id = trips1[0]["id"]
        assert first_score == 100 - 8 * min(trips1[0]["speed_event_count"], 5) - (trips1[0]["distance_m"] // 1609)
        # Trip 2: heavy phone use.
        for i in range(8):
            lat = round(37.7000 + 0.0100 * i, 6)
            ts = f"2026-09-01T03:{i:02d}:00Z"
            set_clock(ts)
            post_fix(circle, owner, owner_headers,
                     recorded_at=ts,
                     lat=lat, speed_mps=30.0, phone_in_use=True, motion_context="DRIVING")
        set_clock("2026-09-01T03:08:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T03:08:00Z",
                 lat=37.7700, speed_mps=0.0, motion_context="STILL")
        trips2 = _closed_trips(api, circle["id"], owner_id, owner_headers)
        assert len(trips2) == 2
        first_again = next(t for t in trips2 if t["id"] == first_id)
        assert first_again["driver_score"] == first_score
        second = next(t for t in trips2 if t["id"] != first_id)
        expected_second = (
            100
            - 8 * min(second["speed_event_count"], 5)
            - 5 * min(second["phone_use_event_count"], 6)
            - second["distance_m"] // 1609
        )
        assert second["driver_score"] == max(0, expected_second)


class TestTripUniqueness:
    def test_trip_open_uniqueness_temporal_interval(self, api, system_headers):
        """PRD §3.6: "A trip opens the first time a member with `consent_state`
        `GRANTED` posts a fix whose `motion_context` is `DRIVING` and no `OPEN`
        trip exists for that member. The trip's `started_at` is the timestamp
        of that first `DRIVING` fix. ... The trip closes — `trip_status`
        becomes `CLOSED` — on the first accepted non-`DRIVING` fix or after 600
        seconds have elapsed without a `DRIVING` fix (a timeout sweep);
        `ended_at` is the timestamp of the last `DRIVING` fix before close."

        Design: Difficulty/resource_temporal_overlap/trip_open_uniqueness_temporal_interval
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="TripFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 lat=37.7000, speed_mps=30.0, motion_context="DRIVING")
        set_clock("2026-09-01T00:05:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:05:00Z",
                 lat=37.7050, speed_mps=0.0, motion_context="STILL")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:05:00Z",
                 lat=37.7050, speed_mps=30.0, motion_context="DRIVING")
        closed = _closed_trips(api, circle["id"], owner_id, owner_headers)
        open_data, _meta = validate_paginated(
            api.list_trips(circle["id"], owner_id, owner_headers, params={"trip_status": "OPEN"})
        )
        assert len(closed) == 1
        assert len(open_data) == 1
        # PRD §3.6: "ended_at is the timestamp of the last DRIVING fix before
        # close" — the last DRIVING fix of the first trip was at 00:00:00.
        assert closed[0]["ended_at"] == "2026-09-01T00:00:00.000Z" or closed[0]["ended_at"].startswith("2026-09-01T00:00:00")
        assert open_data[0]["started_at"].startswith("2026-09-01T00:05:00")

    def test_trip_driving_fix_while_trip_open_extends_same_trip(self, api, system_headers):
        """PRD §3.6: "A trip opens the first time a member with `consent_state`
        `GRANTED` posts a fix whose `motion_context` is `DRIVING` and no `OPEN`
        trip exists for that member. The trip's `started_at` is the timestamp
        of that first `DRIVING` fix. Subsequent `DRIVING` fixes extend the
        trip."

        Design: Difficulty/resource_temporal_overlap/trip_open_uniqueness_temporal_interval
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="TripFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z",
                 speed_mps=30.0, motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:01:00Z",
                 lat=37.7010, speed_mps=30.0, motion_context="DRIVING")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z",
                 lat=37.7020, speed_mps=30.0, motion_context="DRIVING")
        open_data, meta = validate_paginated(
            api.list_trips(circle["id"], owner_id, owner_headers, params={"trip_status": "OPEN"})
        )
        assert meta["total_count"] == 1
        assert open_data[0]["started_at"].startswith("2026-09-01T00:00:00")

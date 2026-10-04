"""Difficulty queue A: dual-variant calculations.

late_join_progress_divergence covers the late-join baseline variant of
challenge progress; obfuscation_full_vs_partial covers the full-swallow
variant of route obfuscation.
"""

from test_helpers import (
    create_active_challenge,
    create_athlete,
    create_club,
    create_privacy_zone,
    join_challenge,
    join_club,
    make_athlete_headers,
    set_clock,
    upload_activity,
    validate_success,
)
from test_helpers.factories import create_activity_payload


class TestLateJoinProgressDivergence:
    def _world(self, api, email_suffix):
        owner = create_athlete(api, email=f"own_{email_suffix}@x.com", display_name=f"Own {email_suffix}")
        joiner = create_athlete(api, email=f"join_{email_suffix}@x.com", display_name=f"Join {email_suffix}")
        club = create_club(api, owner["id"], name=f"Late Join Club {email_suffix}", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], joiner["id"])
        challenge = create_active_challenge(
            api, club["id"], owner["id"],
            name=f"September 50k {email_suffix}", goal_type="DISTANCE_M", goal_target=50000,
            start_date="2026-09-01", end_date="2026-09-07", join_mode="OPEN",
        )
        return owner, joiner, club, challenge

    def _run12000(self, api, athlete_id, started_at, key):
        return upload_activity(
            api, athlete_id,
            sport_type="RUN", started_at=started_at, duration_s=3600, distance_m=12000,
            track_points=[
                {"lat": 37.10, "lng": -122.00, "t_offset_s": 0},
                {"lat": 37.11, "lng": -122.00, "t_offset_s": 1800},
                {"lat": 37.12, "lng": -122.00, "t_offset_s": 3600},
            ],
            start_lat=37.10, start_lng=-122.00, end_lat=37.12, end_lng=-122.00,
            idempotency_key=key,
        )

    def test_late_joiner_counts_only_post_join_activity(self, api):
        """PRD 3.7: "Athletes who join late are subject to the late-join baseline: the retroactive sweep at join time counts only qualifying activities whose completion instant is strictly after `joined_at`; anything completed before the join contributes zero, so two athletes with identical histories but different join instants finish with different progress."

        Design: Difficulty/dual_variant_calc/late_join_progress_divergence
        """
        owner, joiner, club, challenge = self._world(api, "lj1")
        # Activity completed BEFORE the join.
        set_clock(api, "2026-09-02T12:00:00Z")
        self._run12000(api, joiner["id"], "2026-09-02T10:00:00Z", "lj1-act-1")
        participation = join_challenge(api, challenge["id"], joiner["id"])
        # Activity completed AFTER the join.
        set_clock(api, "2026-09-04T12:00:00Z")
        self._run12000(api, joiner["id"], "2026-09-04T10:00:00Z", "lj1-act-2")
        part = validate_success(api.get_participation(participation["id"], make_athlete_headers(joiner["id"])), 200)
        assert part["progress_value"] == 12000
        assert part["status"] == "JOINED"

    def test_early_joiner_counts_everything(self, api):
        """PRD 3.7: "anything completed before the join contributes zero, so two athletes with identical histories but different join instants finish with different progress."
        PRD 3.7: "for `DISTANCE_M` the activity's `distance_m` is added".

        Design: Difficulty/dual_variant_calc/late_join_progress_divergence
        """
        owner, joiner, club, challenge = self._world(api, "lj2")
        # Join FIRST at the default clock (2026-09-01T00:00:00Z), then complete
        # two identical 12000m activities inside the window.
        participation = join_challenge(api, challenge["id"], joiner["id"])
        set_clock(api, "2026-09-02T12:00:00Z")
        self._run12000(api, joiner["id"], "2026-09-02T10:00:00Z", "lj2-act-1")
        set_clock(api, "2026-09-04T12:00:00Z")
        self._run12000(api, joiner["id"], "2026-09-04T10:00:00Z", "lj2-act-2")
        part = validate_success(api.get_participation(participation["id"], make_athlete_headers(joiner["id"])), 200)
        assert part["progress_value"] == 24000
        assert part["status"] == "JOINED"


class TestObfuscationFullVsPartial:
    def _zone_owner(self, api, email):
        athlete = create_athlete(api, email=email, display_name="Z Obf")
        create_privacy_zone(api, athlete["id"], center_lat=37.000, center_lng=-122.000, radius_m=1000)
        return athlete

    def test_fully_swallowed_activity_yields_empty_track_and_null_corners(self, api):
        """PRD 3.3: "If every track point lies inside at least one active zone, the activity is fully swallowed: `obfuscated_track` is empty and all four obfuscated coordinate fields are null — yet the activity still completes and still matches segments, because matching always uses the raw track, never the obfuscated one."

        Design: Difficulty/dual_variant_calc/obfuscation_full_vs_partial
        """
        athlete = self._zone_owner(api, "z_obf1@x.com")
        activity = upload_activity(
            api, athlete["id"],
            device_source="mobile-app", sport_type="RUN", started_at="2026-09-01T08:00:00Z",
            duration_s=600, distance_m=1500,
            track_points=[
                {"lat": 37.001, "lng": -122.001, "t_offset_s": 0},
                {"lat": 37.002, "lng": -122.000, "t_offset_s": 300},
                {"lat": 37.001, "lng": -122.002, "t_offset_s": 600},
            ],
            start_lat=37.001, start_lng=-122.001, end_lat=37.001, end_lng=-122.002,
            idempotency_key="obf1-in",
        )
        assert activity["status"] == "COMPLETED"
        view = validate_success(api.get_activity(activity["id"], make_athlete_headers(athlete["id"])), 200)
        assert view["obfuscated_track"] == []
        assert view["obfuscated_start_lat"] is None
        assert view["obfuscated_start_lng"] is None
        assert view["obfuscated_end_lat"] is None
        assert view["obfuscated_end_lng"] is None

    def test_activity_outside_zone_keeps_full_track(self, api):
        """PRD 3.3: "The surviving ordered points form the activity's `obfuscated_track`; `obfuscated_start_lat` and `obfuscated_start_lng` hold the first surviving point's coordinates, and `obfuscated_end_lat` and `obfuscated_end_lng` hold the last surviving point's coordinates."

        Design: Difficulty/dual_variant_calc/obfuscation_full_vs_partial
        """
        athlete = self._zone_owner(api, "z_obf2@x.com")
        activity = upload_activity(
            api, athlete["id"],
            device_source="mobile-app", sport_type="RUN", started_at="2026-09-01T09:00:00Z",
            duration_s=600, distance_m=1500,
            track_points=[
                {"lat": 37.100, "lng": -122.100, "t_offset_s": 0},
                {"lat": 37.101, "lng": -122.100, "t_offset_s": 300},
                {"lat": 37.102, "lng": -122.100, "t_offset_s": 600},
            ],
            start_lat=37.100, start_lng=-122.100, end_lat=37.102, end_lng=-122.100,
            idempotency_key="obf2-out",
        )
        view = validate_success(api.get_activity(activity["id"], make_athlete_headers(athlete["id"])), 200)
        assert len(view["obfuscated_track"]) == 3
        assert view["obfuscated_start_lat"] == 37.100
        assert view["obfuscated_start_lng"] == -122.100
        assert view["obfuscated_end_lat"] == 37.102
        assert view["obfuscated_end_lng"] == -122.100

    def test_full_swallow_still_matches_segments_via_raw_track(self, api):
        """PRD 3.3: "the activity still completes and still matches segments, because matching always uses the raw track, never the obfuscated one."

        Design: Difficulty/dual_variant_calc/obfuscation_full_vs_partial
        """
        from test_helpers import create_active_segment

        athlete = self._zone_owner(api, "z_obf3@x.com")
        # Segment wholly inside the zone: only the raw track can match it.
        segment = create_active_segment(
            api, athlete["id"], name="Inside Zone Run", sport_type="RUN",
            start_lat=37.001, start_lng=-122.001, end_lat=37.002, end_lng=-122.000,
            distance_m=200, city="Zoneville",
        )
        activity = upload_activity(
            api, athlete["id"],
            sport_type="RUN", started_at="2026-09-01T10:00:00Z", duration_s=600, distance_m=1500,
            track_points=[
                {"lat": 37.001, "lng": -122.001, "t_offset_s": 0},
                {"lat": 37.002, "lng": -122.000, "t_offset_s": 300},
                {"lat": 37.001, "lng": -122.002, "t_offset_s": 600},
            ],
            start_lat=37.001, start_lng=-122.001, end_lat=37.001, end_lng=-122.002,
            idempotency_key="obf3-in",
            effort_hints=[{"segment_id": segment["id"], "elapsed_time_s": 60, "elevation_gain_m": 0}],
        )
        assert activity["status"] == "COMPLETED"
        efforts = validate_success(
            api.list_efforts(make_athlete_headers(athlete["id"]), params={"activity_id": activity["id"]}), 200
        )
        assert len(efforts) == 1
        view = validate_success(api.get_activity(activity["id"], make_athlete_headers(athlete["id"])), 200)
        assert view["obfuscated_track"] == []

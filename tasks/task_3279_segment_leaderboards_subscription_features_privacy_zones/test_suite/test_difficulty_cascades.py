"""Difficulty queue A: transitive cascades.

club_archive_three_hop_cascade covers the Club -> Challenge -> Participation
chain; flag_uphold_autohide_cascade covers Flag -> Effort -> Activity ->
safety-score auto-hide.
"""

from test_helpers import (
    create_active_challenge,
    create_active_segment,
    create_athlete,
    create_club,
    create_activity_with_effort,
    flag_effort,
    join_challenge,
    join_club,
    make_athlete_headers,
    upload_activity,
    uphold_flag,
    validate_success,
)


class TestClubArchiveThreeHopCascade:
    def _world(self, api, suffix):
        owner = create_athlete(api, email=f"ao_{suffix}@x.com", display_name=f"AO {suffix}")
        member = create_athlete(api, email=f"am_{suffix}@x.com", display_name=f"AM {suffix}")
        club = create_club(api, owner["id"], name=f"Cascade Club {suffix}", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], member["id"])
        challenge = create_active_challenge(
            api, club["id"], owner["id"],
            name=f"Cascade 50k {suffix}", goal_type="DISTANCE_M", goal_target=50000,
            start_date="2026-09-01", end_date="2026-09-30", join_mode="OPEN",
        )
        participation = join_challenge(api, challenge["id"], member["id"])
        upload_activity(
            api, member["id"],
            device_source="mobile-app", sport_type="RUN", started_at="2026-09-01T10:00:00Z",
            duration_s=3600, distance_m=12000,
            track_points=[
                {"lat": 39.00, "lng": -124.00, "t_offset_s": 0},
                {"lat": 39.10, "lng": -124.00, "t_offset_s": 3600},
            ],
            start_lat=39.00, start_lng=-124.00, end_lat=39.10, end_lng=-124.00,
            idempotency_key=f"cas-{suffix}-1",
        )
        return owner, member, club, challenge, participation

    def test_archive_cancels_challenge_and_withdraws_participation(self, api):
        """PRD 3.7: "all `DRAFT` or `ACTIVE` challenges of the club move to `CANCELLED`".
        PRD 3.7: "Cancellation — by a club admin, or by the club-archive cascade — moves a `DRAFT` or `ACTIVE` challenge to `CANCELLED` and withdraws every `JOINED` participation."

        Design: Difficulty/transitive_cascade/club_archive_three_hop_cascade
        """
        owner, member, club, challenge, participation = self._world(api, "cas1")
        archived = validate_success(api.archive_club(club["id"], make_athlete_headers(owner["id"])), 200)
        assert archived["status"] == "ARCHIVED"
        ch = validate_success(api.get_challenge(challenge["id"], make_athlete_headers(owner["id"])), 200)
        assert ch["status"] == "CANCELLED"
        part = validate_success(api.get_participation(participation["id"], make_athlete_headers(member["id"])), 200)
        assert part["status"] == "WITHDRAWN"

    def test_cascade_freezes_progress_value(self, api):
        """PRD 3.7: "for `DISTANCE_M` the activity's `distance_m` is added" — progress accumulated before the cascade remains recorded on the withdrawn participation.

        Design: Difficulty/transitive_cascade/club_archive_three_hop_cascade
        """
        owner, member, club, challenge, participation = self._world(api, "cas2")
        before = validate_success(api.get_participation(participation["id"], make_athlete_headers(member["id"])), 200)
        assert before["progress_value"] == 12000
        validate_success(api.archive_club(club["id"], make_athlete_headers(owner["id"])), 200)
        after = validate_success(api.get_participation(participation["id"], make_athlete_headers(member["id"])), 200)
        assert after["progress_value"] == 12000
        assert after["status"] == "WITHDRAWN"


class TestFlagUpholdAutohideCascade:
    def _violator_with_flagged_efforts(self, api, suffix, count):
        violator = create_athlete(api, email=f"v_{suffix}@x.com", display_name=f"V {suffix}")
        reporter = create_athlete(api, email=f"q_{suffix}@x.com", display_name=f"Q {suffix}")
        segment = create_active_segment(
            api, reporter["id"], name=f"Uphold Run 1k {suffix}", sport_type="RUN",
            start_lat=40.00, start_lng=-125.00, end_lat=40.01, end_lng=-125.00,
            distance_m=1000, city="Upholdton",
        )
        efforts = []
        for i in range(count):
            pair = create_activity_with_effort(
                api, segment, violator["id"], elapsed_time_s=100,
                started_at=f"2026-09-01T{6 + i:02d}:00:00Z", idempotency_key=f"up-{suffix}-{i}",
            )
            efforts.append(pair["effort"])
        flags = [flag_effort(api, e["id"], reporter["id"]) for e in efforts]
        return violator, reporter, segment, efforts, flags

    def test_five_upholds_drop_score_to_fifty_without_autohide(self, api):
        """PRD 3.6: "The `safety_score` starts at 100, loses 10 per upheld flag (never below zero), and gains 5 per rejected flag (never above 100)."
        PRD 3.6: "Its consequential threshold is 50: the moment an athlete's score falls below 50, every `COMPLETED` activity they own is marked `auto_hidden` true." — exactly 50 is not below 50.

        Design: Difficulty/transitive_cascade/flag_uphold_autohide_cascade
        """
        violator, reporter, segment, efforts, flags = self._violator_with_flagged_efforts(api, "up5", 5)
        for flag in flags:
            uphold_flag(api, flag["id"])
        athlete = validate_success(api.get_athlete(violator["id"], make_athlete_headers(violator["id"])), 200)
        assert athlete["safety_score"] == 50
        activity_id = efforts[0]["activity_id"]
        activity = validate_success(api.get_activity(activity_id, make_athlete_headers(violator["id"])), 200)
        assert activity["auto_hidden"] is False

    def test_sixth_uphold_crosses_below_fifty_and_hides_all_completed_activities(self, api):
        """PRD 3.6: "the moment an athlete's score falls below 50, every `COMPLETED` activity they own is marked `auto_hidden` true."
        PRD 3.6: "**Upholding** a flag moves it to `UPHELD` and triggers the confirmation cascade: the effort moves from `FLAGGED` to `EXCLUDED` with `exclusion_reason` `FLAG_UPHELD`, the host activity's `flag_status` moves from `FLAGGED` to `CONFIRMED` (the first upheld flag on the activity is enough), the athlete's `safety_score` drops by 10 with a floor of zero".

        Design: Difficulty/transitive_cascade/flag_uphold_autohide_cascade
        """
        violator, reporter, segment, efforts, flags = self._violator_with_flagged_efforts(api, "up6", 6)
        for flag in flags:
            uphold_flag(api, flag["id"])
        athlete = validate_success(api.get_athlete(violator["id"], make_athlete_headers(violator["id"])), 200)
        assert athlete["safety_score"] == 40
        for effort in efforts:
            activity = validate_success(api.get_activity(effort["activity_id"], make_athlete_headers(violator["id"])), 200)
            assert activity["auto_hidden"] is True
            assert activity["flag_status"] == "CONFIRMED"
            resolved = validate_success(api.get_effort(effort["id"], make_athlete_headers(violator["id"])), 200)
            assert resolved["flag_status"] == "EXCLUDED"
            assert resolved["exclusion_reason"] == "FLAG_UPHELD"

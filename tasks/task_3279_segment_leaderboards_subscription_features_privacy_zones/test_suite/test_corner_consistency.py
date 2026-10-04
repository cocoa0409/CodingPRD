"""Consistency-model corner claims: immediate visibility of upload side
effects and atomic erasure."""

from test_helpers import (
    create_active_challenge,
    create_active_segment,
    create_athlete,
    join_challenge,
    make_athlete_headers,
    setup_erasable_athlete,
    upload_activity,
    validate_success,
)


class TestUploadSideEffectsVisibleImmediately:
    def test_upload_matches_and_accumulates_atomically(self, api):
        """PRD 3.4: "When no duplicate is detected, the activity completes and the system runs four follow-on processes, in this order." — the completion and its side effects are part of one upload, with no deferred reconciliation.
        PRD 3.7: "For each `JOINED` participation whose challenge window covers the activity's `started_at` UTC date, the activity contributes if it is `COMPLETED`, not auto-hidden, and its `flag_status` is `NONE` or `CLEARED`; each activity contributes at most once per challenge. The contribution depends on the goal type: for `DISTANCE_M` the activity's `distance_m` is added".

        Design: Corner/consistency_model/upload_side_effects_visible_immediately
        """
        owner = create_athlete(api, email="ico@x.com", display_name="ICO")
        member = create_athlete(api, email="icm@x.com", display_name="ICM")
        segment = create_active_segment(
            api, owner["id"], name="Immediate Run", sport_type="RUN",
            start_lat=69.00, start_lng=-154.00, end_lat=69.01, end_lng=-154.00,
            distance_m=1000, city="Immedville",
        )
        from test_helpers import create_club, join_club

        club = create_club(api, owner["id"], name="Immediate Club", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], member["id"])
        challenge = create_active_challenge(
            api, club["id"], owner["id"], name="Immediate Challenge",
            goal_type="DISTANCE_M", goal_target=50000,
            start_date="2026-09-01", end_date="2026-09-30", join_mode="OPEN",
        )
        participation = join_challenge(api, challenge["id"], member["id"])
        activity = upload_activity(
            api, member["id"],
            sport_type="RUN", started_at="2026-09-01T06:00:00Z", duration_s=100, distance_m=1000,
            track_points=[
                {"lat": segment["start_lat"], "lng": segment["start_lng"], "t_offset_s": 0},
                {"lat": segment["end_lat"], "lng": segment["end_lng"], "t_offset_s": 100},
            ],
            start_lat=segment["start_lat"], start_lng=segment["start_lng"],
            end_lat=segment["end_lat"], end_lng=segment["end_lng"],
            idempotency_key="ic-1",
            effort_hints=[{"segment_id": segment["id"], "elapsed_time_s": 100, "elevation_gain_m": 0}],
        )
        assert activity["status"] == "COMPLETED"
        board = validate_success(api.get_leaderboard(segment["id"], make_athlete_headers(owner["id"])), 200)
        assert len(board) == 1
        assert board[0]["rank_snapshot"] == 1
        part = validate_success(api.get_participation(participation["id"], make_athlete_headers(member["id"])), 200)
        assert part["progress_value"] == 1000

    def test_upload_creates_effort_visible_in_flat_list(self, api):
        """PRD 3.4: "Second, the **segment match sweep**: for every `ACTIVE` segment with a `hazard_index` of zero whose `sport_type` matches the activity's effective category (the `corrected_sport_type` if one is set, otherwise the declared `sport_type`), a new effort is created."

        Design: Corner/consistency_model/upload_side_effects_visible_immediately
        """
        owner = create_athlete(api, email="ico2@x.com", display_name="ICO2")
        rider = create_athlete(api, email="icm2@x.com", display_name="ICM2")
        segment = create_active_segment(api, owner["id"], sport_type="RUN", distance_m=1000)
        from test_helpers import create_activity_with_effort

        pair = create_activity_with_effort(api, segment, rider["id"], elapsed_time_s=100)
        efforts = validate_success(
            api.list_efforts(make_athlete_headers(rider["id"]), params={"activity_id": pair["activity"]["id"]}), 200
        )
        assert len(efforts) == 1
        assert efforts[0]["segment_id"] == segment["id"]
        assert efforts[0]["flag_status"] == "ELIGIBLE"


class TestAccountDeletionErasureAtomicity:
    def test_delete_applies_full_erasure_cascade(self, api):
        """PRD 3.1: "Personal information is scrubbed in place — the `email` is overwritten to the literal address `deleted-{id}@erased.invalid` and the `display_name` is overwritten to the literal string `Deleted Athlete`."
        PRD 3.1: "Every effort the athlete has ever recorded is excluded, with its `exclusion_reason` left unchanged if one is already set and otherwise stamped `FLAG_UPHELD`."
        PRD 3.1: "Every `ACTIVE` club membership moves to `LEFT`."

        Design: Corner/consistency_model/account_deletion_erasure_atomicity
        """
        world = setup_erasable_athlete(api)
        athlete = world["athlete"]
        deleted = validate_success(api.delete_athlete(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        assert deleted["status"] == "DELETED"
        assert deleted["email"] == f"deleted-{athlete['id']}@erased.invalid"
        assert deleted["display_name"] == "Deleted Athlete"
        effort = validate_success(api.get_effort(world["effort"]["id"], make_athlete_headers(world["other"]["id"])), 200)
        assert effort["flag_status"] == "EXCLUDED"
        membership = validate_success(api.get_membership(world["membership"]["id"], make_athlete_headers(world["other"]["id"])), 200)
        assert membership["status"] == "LEFT"

    def test_delete_rejects_completed_activities_immediately(self, api):
        """PRD 3.1: "Every `COMPLETED` activity the athlete owns moves to `REJECTED` (activities already `DUPLICATE` or `REJECTED` are untouched)."

        Design: Corner/consistency_model/account_deletion_erasure_atomicity
        """
        world = setup_erasable_athlete(api)
        athlete = world["athlete"]
        validate_success(api.delete_athlete(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        # The deleted athlete's row is still readable by id (export/admin paths);
        # verify the activity status via the flat list filtered by athlete.
        activities = validate_success(
            api.list_activities(make_athlete_headers(world["other"]["id"]), params={"athlete_id": athlete["id"]}), 200
        )
        assert len(activities) == 1
        assert activities[0]["status"] == "REJECTED"

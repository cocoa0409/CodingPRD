"""Error corner claims: violation-to-error translations for the error catalog."""

from test_helpers import (
    ApiErrorId,
    create_active_challenge,
    create_active_segment,
    create_athlete,
    create_club,
    create_event,
    create_rsvp,
    flag_effort,
    join_challenge,
    join_club,
    make_athlete_headers,
    make_platform_admin_headers,
    setup_club_with_member,
    create_activity_with_effort,
    upload_activity,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_activity_payload


class TestStrictDuplicateError:
    def test_strict_duplicate_rejected_with_duplicate_activity(self, api):
        """PRD 3.4: "When `strict_duplicate` is true on the upload, the same detection instead rejects the request outright with `ERR_DUPLICATE_ACTIVITY` (HTTP 409)."

        Design: Corner/errors/strict_duplicate_returns_duplicate_error
        """
        athlete = create_athlete(api, email="sd_d@x.com", display_name="SD D")
        headers = make_athlete_headers(athlete["id"])
        payload = create_activity_payload(
            device_source="wahoo-elemnt", sport_type="RIDE", started_at="2026-09-01T06:00:00Z",
            duration_s=600, distance_m=2000,
            track_points=[{"lat": 61.00, "lng": -146.00, "t_offset_s": 0}, {"lat": 61.01, "lng": -146.00, "t_offset_s": 600}],
            start_lat=61.00, start_lng=-146.00, end_lat=61.01, end_lng=-146.00,
            idempotency_key="sd-1",
        )
        validate_success(api.upload_activity(athlete["id"], payload, headers), 201)
        strict = dict(payload)
        strict["strict_duplicate"] = True
        resp = api.upload_activity(athlete["id"], strict, headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVITY)

    def test_non_strict_duplicate_succeeds_as_duplicate(self, api):
        """PRD 3.4: "By default the duplicate completes with HTTP 201 in `DUPLICATE` status".

        Design: Corner/errors/strict_duplicate_returns_duplicate_error
        """
        athlete = create_athlete(api, email="sd_e@x.com", display_name="SD E")
        headers = make_athlete_headers(athlete["id"])
        payload = create_activity_payload(
            sport_type="RIDE", started_at="2026-09-01T06:00:00Z", duration_s=600, distance_m=2000,
            idempotency_key="sd-2",
        )
        validate_success(api.upload_activity(athlete["id"], payload, headers), 201)
        resp = api.upload_activity(athlete["id"], dict(payload), headers)
        dup = validate_success(resp, 201)
        assert dup["status"] == "DUPLICATE"


class TestVehicleAssistedAutoFlag:
    def test_ebike_effort_on_ride_segment_flagged_vehicle_assisted(self, api):
        """PRD 3.4: "Separately, an effort whose effective category is `EBikeRide` matched onto a `RIDE` segment is flagged `VEHICLE_ASSISTED` — it is not speed-checked against the bicycle limits, though the e-bike maximum of 45 km/h governs the speed half of its own evaluation."

        Design: Corner/errors/vehicle_assisted_ebike_effort_auto_flagged
        """
        creator = create_athlete(api, email="eb_e@x.com", display_name="EB E")
        rider = create_athlete(api, email="er_e@x.com", display_name="ER E")
        segment = create_active_segment(
            api, creator["id"], name="EBike Trap", sport_type="RIDE",
            start_lat=62.00, start_lng=-147.00, end_lat=62.01, end_lng=-147.00,
            distance_m=1000, city="Ebikeville",
        )
        pair = create_activity_with_effort(
            api, segment, rider["id"], elapsed_time_s=100, sport_type="EBikeRide",
            started_at="2026-09-01T06:00:00Z",
        )
        effort = pair["effort"]
        # 100s over 1000m passes the e-bike speed gate (threshold 56s) but is
        # vehicle-assisted on a RIDE segment.
        assert effort["flag_status"] == "FLAGGED"
        assert effort["exclusion_reason"] == "VEHICLE_ASSISTED"

    def test_ebike_flag_marks_host_activity_flagged(self, api):
        """PRD 3.4: "In either flagging case the effort moves from `ELIGIBLE` to `FLAGGED` with the corresponding `exclusion_reason`, and the host activity's `flag_status` moves from `NONE` to `FLAGGED` if it was still `NONE`."

        Design: Corner/errors/vehicle_assisted_ebike_effort_auto_flagged
        """
        creator = create_athlete(api, email="eb_f@x.com", display_name="EB F")
        rider = create_athlete(api, email="er_f@x.com", display_name="ER F")
        segment = create_active_segment(api, creator["id"], sport_type="RIDE", distance_m=1000)
        pair = create_activity_with_effort(api, segment, rider["id"], elapsed_time_s=100, sport_type="EBikeRide")
        activity = validate_success(api.get_activity(pair["activity"]["id"], make_athlete_headers(rider["id"])), 200)
        assert activity["flag_status"] == "FLAGGED"


class TestRsvpCapacityExceeded:
    def test_second_rsvp_on_capacity_one_event_rejected(self, api):
        """PRD 3.7: "Creating or rejoining is refused once the event is full — `rsvp_count` equal to `capacity` — with `ERR_CAPACITY_EXCEEDED`".

        Design: Corner/errors/rsvp_capacity_exceeded
        """
        owner = create_athlete(api, email="co_cap@x.com", display_name="CO Cap")
        member1 = create_athlete(api, email="cm1_cap@x.com", display_name="CM1 Cap")
        member2 = create_athlete(api, email="cm2_cap@x.com", display_name="CM2 Cap")
        segment = create_active_segment(api, owner["id"], name="Capacity Sprint", sport_type="RIDE", start_lat=63.00, start_lng=-148.00, end_lat=63.01, end_lng=-148.00, distance_m=1000, city="Capville")
        club = create_club(api, owner["id"], name="Capacity Club", sport_type="RIDE", join_policy="OPEN")
        join_club(api, club["id"], member1["id"])
        join_club(api, club["id"], member2["id"])
        event = create_event(api, club["id"], owner["id"], segment["id"], name="Tiny Race", scheduled_at="2026-09-06T09:00:00Z", capacity=1)
        create_rsvp(api, event["id"], member1["id"])
        resp = api.create_rsvp(event["id"], {"athlete_id": member2["id"]}, make_athlete_headers(member2["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_capacity_two_event_accepts_two_rsvps(self, api):
        """PRD 3.7: "refused once the event is full — `rsvp_count` equal to `capacity`"; below capacity the RSVP succeeds.

        Design: Corner/errors/rsvp_capacity_exceeded
        """
        owner = create_athlete(api, email="co_cp2@x.com", display_name="CO Cp2")
        member1 = create_athlete(api, email="cm1_cp2@x.com", display_name="CM1 Cp2")
        member2 = create_athlete(api, email="cm2_cp2@x.com", display_name="CM2 Cp2")
        segment = create_active_segment(api, owner["id"], sport_type="RIDE")
        club = create_club(api, owner["id"], sport_type="RIDE", join_policy="OPEN")
        join_club(api, club["id"], member1["id"])
        join_club(api, club["id"], member2["id"])
        event = create_event(api, club["id"], owner["id"], segment["id"], capacity=2)
        create_rsvp(api, event["id"], member1["id"])
        second = validate_success(api.create_rsvp(event["id"], {"athlete_id": member2["id"]}, make_athlete_headers(member2["id"])), 201)
        assert second["status"] == "GOING"


class TestArchivedClubRejectsJoin:
    def test_join_archived_club_rejected(self, api):
        """PRD 3.7: "Once a club is archived, club-scoped writes — joining, creating, starting, or cancelling challenges, and creating or cancelling events — are rejected with `ERR_CLUB_ARCHIVED`."

        Design: Corner/errors/archived_club_rejects_join
        """
        owner = create_athlete(api, email="ac_a@x.com", display_name="AC A")
        joiner = create_athlete(api, email="aj_a@x.com", display_name="AJ A")
        club = create_club(api, owner["id"], name="Doomed Club", sport_type="RUN", join_policy="OPEN")
        validate_success(api.archive_club(club["id"], make_athlete_headers(owner["id"])), 200)
        resp = api.join_club(club["id"], {"athlete_id": joiner["id"]}, make_athlete_headers(joiner["id"]))
        validate_error(resp, ApiErrorId.ERR_CLUB_ARCHIVED)

    def test_challenge_create_on_archived_club_rejected(self, api):
        """PRD 3.7: "Once a club is archived, club-scoped writes — joining, creating, starting, or cancelling challenges, and creating or cancelling events — are rejected with `ERR_CLUB_ARCHIVED`."

        Design: Corner/errors/archived_club_rejects_join
        """
        from test_helpers.factories import create_challenge_payload

        owner = create_athlete(api, email="ac_b@x.com", display_name="AC B")
        club = create_club(api, owner["id"], name="Doomed Challenge Club", sport_type="RUN", join_policy="OPEN")
        validate_success(api.archive_club(club["id"], make_athlete_headers(owner["id"])), 200)
        # The caller must pass authorization for the archived gate (PRD 2.5
        # priority: authorization precedes the club-archived gate) to be the
        # first failing check — a PlatformAdmin always passes role checks.
        resp = api.create_challenge(club["id"], create_challenge_payload(), make_platform_admin_headers())
        validate_error(resp, ApiErrorId.ERR_CLUB_ARCHIVED)


class TestSelfFlagRejected:
    def test_flagging_own_effort_rejected(self, api):
        """PRD 3.6: "the reporter must differ from the activity's owner — flagging one's own effort is rejected with `ERR_FLAG_SELF`".

        Design: Corner/errors/self_flag_rejected
        """
        athlete = create_athlete(api, email="sf_f@x.com", display_name="SF F")
        segment = create_active_segment(api, athlete["id"], name="Self Flag Run", sport_type="RUN", start_lat=64.00, start_lng=-149.00, end_lat=64.01, end_lng=-149.00, distance_m=1000, city="Selfville")
        pair = create_activity_with_effort(api, segment, athlete["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        resp = api.create_flag(
            pair["effort"]["id"],
            {"reporter_id": athlete["id"], "reason": "IMPOSSIBLE_TIME"},
            make_athlete_headers(athlete["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLAG_SELF)


class TestInconsistentReferenceOnCorrectCategory:
    def test_same_category_correction_rejected(self, api):
        """PRD 3.4: "a `corrected_sport_type`, which must be one of the six valid categories and must differ from the activity's current effective category — a correction equal to the existing category, or an invalid value, is rejected with `ERR_INCONSISTENT_REFERENCE`".

        Design: Corner/errors/inconsistent_reference_on_correct_category
        """
        athlete = create_athlete(api, email="cr_c@x.com", display_name="CR C")
        activity = upload_activity(api, athlete["id"], sport_type="RUN", idempotency_key="cr-1")
        resp = api.correct_activity_category(activity["id"], "RUN", make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_INCONSISTENT_REFERENCE)

    def test_invalid_category_correction_rejected(self, api):
        """PRD 3.4: "a correction equal to the existing category, or an invalid value, is rejected with `ERR_INCONSISTENT_REFERENCE`".

        Design: Corner/errors/inconsistent_reference_on_correct_category
        """
        athlete = create_athlete(api, email="cr_d@x.com", display_name="CR D")
        activity = upload_activity(api, athlete["id"], sport_type="RUN", idempotency_key="cr-2")
        resp = api.correct_activity_category(activity["id"], "UNICYCLE", make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_INCONSISTENT_REFERENCE)


class TestDuplicateChallengeJoinRejected:
    def test_second_join_same_challenge_rejected(self, api):
        """PRD 3.7: "an athlete who already holds a `JOINED` or `COMPLETED` participation is rejected with `ERR_ALREADY_JOINED`".

        Design: Corner/errors/duplicate_challenge_join_rejected
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        challenge = create_active_challenge(api, world["club"]["id"], world["owner"]["id"], name="Dupe Challenge")
        join_challenge(api, challenge["id"], world["member"]["id"])
        resp = api.join_challenge(challenge["id"], {"athlete_id": world["member"]["id"]}, make_athlete_headers(world["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_JOINED)

    def test_owner_can_join_own_challenge_once(self, api):
        """PRD 3.7: "under `OPEN`, any `ACTIVE` club member may join" — the founder's automatic ACTIVE membership qualifies.

        Design: Corner/errors/duplicate_challenge_join_rejected
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        challenge = create_active_challenge(api, world["club"]["id"], world["owner"]["id"], name="Owner Join Challenge")
        part = join_challenge(api, challenge["id"], world["owner"]["id"])
        assert part["status"] == "JOINED"
        resp = api.join_challenge(challenge["id"], {"athlete_id": world["owner"]["id"]}, make_athlete_headers(world["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_JOINED)


class TestDuplicateClubMembershipRejected:
    def test_second_membership_same_club_rejected(self, api):
        """PRD 3.7: "An athlete who already holds a `PENDING` or `ACTIVE` membership in the club is rejected with `ERR_DUPLICATE_MEMBERSHIP`."

        Design: Corner/errors/duplicate_club_membership_rejected
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        resp = api.join_club(world["club"]["id"], {"athlete_id": world["member"]["id"]}, make_athlete_headers(world["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

    def test_pending_membership_blocks_second_join(self, api):
        """PRD 3.7: "An athlete who already holds a `PENDING` or `ACTIVE` membership in the club is rejected with `ERR_DUPLICATE_MEMBERSHIP`."

        Design: Corner/errors/duplicate_club_membership_rejected
        """
        world = setup_club_with_member(api, join_policy="APPROVAL")
        assert world["membership"]["status"] == "PENDING"
        resp = api.join_club(world["club"]["id"], {"athlete_id": world["member"]["id"]}, make_athlete_headers(world["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

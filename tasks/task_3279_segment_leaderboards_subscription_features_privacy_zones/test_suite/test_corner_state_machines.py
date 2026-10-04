"""State-machine corner claims: cyclic edges, terminal lockdowns, lazy flips,
duplicate reconciliation, and membership approval."""

from test_helpers import (
    ApiErrorId,
    create_active_challenge,
    create_active_segment,
    create_athlete,
    create_club,
    create_event,
    create_rsvp,
    create_safety_contact,
    create_subscription,
    join_challenge,
    join_club,
    make_athlete_headers,
    make_platform_admin_headers,
    set_clock,
    setup_club_with_member,
    setup_event_scenario,
    upload_activity,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_activity_payload, create_event_payload


class TestRsvpDeclineRejoinCycle:
    def test_decline_then_rejoin_restores_going(self, api):
        """PRD 3.7: "Declining is cyclic: a `DECLINED` RSVP may return to `GOING` — only by its owner, only while the event is still `PUBLISHED`, and only while the event is under capacity — incrementing `rsvp_count` again."

        Design: Corner/state_machines/rsvp_decline_then_rejoin_cycle
        """
        world = setup_event_scenario(api, capacity=3, scheduled_at="2026-09-06T09:00:00Z")
        member = world["member"]
        event = world["event"]
        rsvp = create_rsvp(api, event["id"], member["id"])
        declined = validate_success(
            api.decline_rsvp(event["id"], rsvp["id"], make_athlete_headers(member["id"])), 200
        )
        assert declined["status"] == "DECLINED"
        rejoined = validate_success(
            api.rejoin_rsvp(event["id"], rsvp["id"], make_athlete_headers(member["id"])), 200
        )
        assert rejoined["status"] == "GOING"

    def test_decline_rejoin_round_trip_twice(self, api):
        """PRD 3.7: "Declining is cyclic: a `DECLINED` RSVP may return to `GOING`".

        Design: Corner/state_machines/rsvp_decline_then_rejoin_cycle
        """
        world = setup_event_scenario(api, capacity=3, scheduled_at="2026-09-06T09:00:00Z")
        member = world["member"]
        event = world["event"]
        rsvp = create_rsvp(api, event["id"], member["id"])
        headers = make_athlete_headers(member["id"])
        for _ in range(2):
            d = validate_success(api.decline_rsvp(event["id"], rsvp["id"], headers), 200)
            assert d["status"] == "DECLINED"
            r = validate_success(api.rejoin_rsvp(event["id"], rsvp["id"], headers), 200)
            assert r["status"] == "GOING"


class TestTerminalEventLockdown:
    def test_rsvp_to_cancelled_event_rejected(self, api):
        """PRD 3.7: "refused after `scheduled_at` has passed or once the event has left `PUBLISHED`, with `ERR_WINDOW_VIOLATION` or `ERR_INVALID_STATE` respectively".

        Design: Corner/state_machines/terminal_event_lockdown
        """
        world = setup_event_scenario(api, capacity=3, scheduled_at="2026-09-06T09:00:00Z")
        owner = world["owner"]
        member = world["member"]
        event = world["event"]
        validate_success(
            api.cancel_event(world["club"]["id"], event["id"], make_athlete_headers(owner["id"])), 200
        )
        resp = api.create_rsvp(event["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejoin_rsvp_on_cancelled_event_rejected(self, api):
        """PRD 3.7: "Declining is cyclic: a `DECLINED` RSVP may return to `GOING` — only by its owner, only while the event is still `PUBLISHED`, and only while the event is under capacity".

        Design: Corner/state_machines/terminal_event_lockdown
        """
        world = setup_event_scenario(api, capacity=3, scheduled_at="2026-09-06T09:00:00Z")
        owner = world["owner"]
        member = world["member"]
        event = world["event"]
        rsvp = create_rsvp(api, event["id"], member["id"])
        validate_success(api.decline_rsvp(event["id"], rsvp["id"], make_athlete_headers(member["id"])), 200)
        validate_success(api.cancel_event(world["club"]["id"], event["id"], make_athlete_headers(owner["id"])), 200)
        resp = api.rejoin_rsvp(event["id"], rsvp["id"], make_athlete_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClosedChallengeRejectsJoin:
    def test_join_after_lazy_close_rejected(self, api):
        """PRD 2.6: "a challenge whose window end has passed flips from `ACTIVE` to `CLOSED` on the next read".
        PRD 3.7: "Joining a challenge that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/closed_challenge_rejects_join
        """
        owner = create_athlete(api, email="ko_k@x.com", display_name="KO K")
        member = create_athlete(api, email="km_k@x.com", display_name="KM K")
        club = create_club(api, owner["id"], name="Closing Club", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], member["id"])
        challenge = create_active_challenge(
            api, club["id"], owner["id"],
            name="Week One", goal_type="DISTANCE_M", goal_target=10000,
            start_date="2026-09-01", end_date="2026-09-07", join_mode="OPEN",
        )
        set_clock(api, "2026-09-08T00:00:00Z")
        got = validate_success(api.get_challenge(challenge["id"], make_athlete_headers(owner["id"])), 200)
        assert got["status"] == "CLOSED"
        resp = api.join_challenge(challenge["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_join_before_window_end_still_allowed(self, api):
        """PRD 3.7: "Joining a challenge that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`" — an ACTIVE challenge inside its window accepts joins.

        Design: Corner/state_machines/closed_challenge_rejects_join
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        challenge = create_active_challenge(
            api, world["club"]["id"], world["owner"]["id"],
            start_date="2026-09-01", end_date="2026-09-07", join_mode="OPEN",
        )
        part = join_challenge(api, challenge["id"], world["member"]["id"])
        assert part["status"] == "JOINED"


class TestLapsedSubscriptionBlocksGatedFeature:
    def test_lapsed_subscription_blocks_beacon_creation(self, api):
        """PRD 3.2: "A subscription that simply runs out of time moves from `ACTIVE` to `LAPSED` lazily: the flip happens on the first read or write that touches it after the logical clock reaches `expires_at`."
        PRD 3.8: "the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise)".

        Design: Corner/state_machines/lapsed_subscription_blocks_gated_feature
        """
        athlete = create_athlete(api, email="ls_s@x.com", display_name="LS S")
        create_subscription(api, athlete["id"], started_at="2026-08-01T00:00:00Z", expires_at="2026-09-02T00:00:00Z")
        create_safety_contact(api, athlete["id"], contact_email="sos_ls@x.com", label="SOS")
        set_clock(api, "2026-09-03T00:00:00Z")
        subs = validate_success(api.list_subscriptions(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        assert subs[0]["status"] == "LAPSED"
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)

    def test_active_subscription_permits_beacon_creation(self, api):
        """PRD 3.8: "Starting a beacon session is a subscription-gated safety feature with three guards: the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise), must have at least one safety contact (`ERR_SAFETY_VIOLATION` otherwise), and must not already have a `LIVE` session".

        Design: Corner/state_machines/lapsed_subscription_blocks_gated_feature
        """
        athlete = create_athlete(api, email="ls_ok@x.com", display_name="LS OK")
        create_subscription(api, athlete["id"], started_at="2026-08-01T00:00:00Z", expires_at="2027-09-02T00:00:00Z")
        create_safety_contact(api, athlete["id"], contact_email="sos_ok@x.com", label="SOS")
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        data = validate_success(resp, 201)
        assert data["status"] == "LIVE"


class TestDuplicateUploadReconciliation:
    def test_cross_device_duplicate_completes_as_duplicate(self, api):
        """PRD 3.4: "A candidate is a duplicate when another non-`REJECTED` activity of the same athlete exists with the same `idempotency_key`, **or** with the same `device_source` and a `started_at` within 120 seconds of the earlier activity's start and a `distance_m` within five percent of the earlier activity's distance". "By default the duplicate completes with HTTP 201 in `DUPLICATE` status, its `duplicate_of_id` pointing at the canonical candidate — the one with the earliest `created_at`".

        Design: Corner/state_machines/duplicate_upload_reconciliation
        """
        athlete = create_athlete(api, email="du_d@x.com", display_name="DU D")
        first = upload_activity(
            api, athlete["id"],
            device_source="garmin-edge", sport_type="RIDE", started_at="2026-09-01T06:00:00Z",
            duration_s=600, distance_m=2000,
            track_points=[{"lat": 52.00, "lng": -137.00, "t_offset_s": 0}, {"lat": 52.01, "lng": -137.00, "t_offset_s": 600}],
            start_lat=52.00, start_lng=-137.00, end_lat=52.01, end_lng=-137.00,
            idempotency_key="du-1",
        )
        assert first["status"] == "COMPLETED"
        resp = api.upload_activity(
            athlete["id"],
            create_activity_payload(
                device_source="garmin-edge", sport_type="RIDE", started_at="2026-09-01T06:01:00Z",
                duration_s=600, distance_m=2000,
                track_points=[{"lat": 52.00, "lng": -137.00, "t_offset_s": 0}, {"lat": 52.01, "lng": -137.00, "t_offset_s": 600}],
                start_lat=52.00, start_lng=-137.00, end_lat=52.01, end_lng=-137.00,
                idempotency_key="du-2",
            ),
            make_athlete_headers(athlete["id"]),
        )
        dup = validate_success(resp, 201)
        assert dup["status"] == "DUPLICATE"
        assert dup["duplicate_of_id"] == first["id"]

    def test_duplicate_runs_no_segment_sweep(self, api):
        """PRD 3.4: "By default the duplicate completes with HTTP 201 in `DUPLICATE` status, its `duplicate_of_id` pointing at the canonical candidate — the one with the earliest `created_at` — and no further processing: no segment sweep, no challenge accumulation, no heat map contribution."

        Design: Corner/state_machines/duplicate_upload_reconciliation
        """
        from test_helpers import create_active_segment

        athlete = create_athlete(api, email="du_ns@x.com", display_name="DU NS")
        owner = create_athlete(api, email="du_own@x.com", display_name="DU OWN")
        segment = create_active_segment(api, owner["id"], sport_type="RUN", distance_m=1000)
        headers = make_athlete_headers(athlete["id"])
        base_payload = create_activity_payload(
            sport_type="RUN", started_at="2026-09-01T06:00:00Z", duration_s=100, distance_m=1000,
            track_points=[
                {"lat": segment["start_lat"], "lng": segment["start_lng"], "t_offset_s": 0},
                {"lat": segment["end_lat"], "lng": segment["end_lng"], "t_offset_s": 100},
            ],
            start_lat=segment["start_lat"], start_lng=segment["start_lng"],
            end_lat=segment["end_lat"], end_lng=segment["end_lng"],
            idempotency_key="du-ns-1",
        )
        first = validate_success(api.upload_activity(athlete["id"], base_payload, headers), 201)
        assert first["status"] == "COMPLETED"
        dup_payload = dict(base_payload)
        dup_payload["idempotency_key"] = "du-ns-2"
        dup_payload["started_at"] = "2026-09-01T06:01:00Z"
        dup = validate_success(api.upload_activity(athlete["id"], dup_payload, headers), 201)
        assert dup["status"] == "DUPLICATE"
        efforts = validate_success(api.list_efforts(headers, params={"activity_id": dup["id"]}), 200)
        assert efforts == [], "A DUPLICATE upload must not create segment efforts"


class TestMembershipApprove:
    def test_pending_membership_approved_to_active(self, api):
        """PRD 3.7: "Under an `OPEN` policy the membership is immediately `ACTIVE`; under `APPROVAL` it parks in `PENDING` until an admin acts."
        PRD 3.7: "A club admin — meaning the caller holds an `ACTIVE` membership with `role` `ADMIN` in that same club — may approve a `PENDING` membership to `ACTIVE`, or remove a `PENDING` or `ACTIVE` membership to `REMOVED`; the club owner's own membership can never be removed."

        Design: Corner/state_machines/membership_pending_to_active_on_approve
        """
        owner = create_athlete(api, email="ao_m@x.com", display_name="AO M")
        member = create_athlete(api, email="am_m@x.com", display_name="AM M")
        club = create_club(api, owner["id"], name="Approval Gate Club", sport_type="RUN", join_policy="APPROVAL")
        membership = join_club(api, club["id"], member["id"])
        assert membership["status"] == "PENDING"
        approved = validate_success(
            api.approve_membership(club["id"], membership["id"], make_athlete_headers(owner["id"])), 200
        )
        assert approved["status"] == "ACTIVE"

    def test_open_policy_join_is_active_immediately(self, api):
        """PRD 3.7: "Under an `OPEN` policy the membership is immediately `ACTIVE`; under `APPROVAL` it parks in `PENDING` until an admin acts."

        Design: Corner/state_machines/membership_pending_to_active_on_approve
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        assert world["membership"]["status"] == "ACTIVE"

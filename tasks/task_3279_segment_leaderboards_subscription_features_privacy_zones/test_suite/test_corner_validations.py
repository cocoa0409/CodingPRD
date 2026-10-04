"""Validation corner claims: priority ordering and subscription gating."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_club,
    create_event,
    make_athlete_headers,
    create_activity_with_effort,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_event_payload


class TestExistenceBeatsState:
    def test_bogus_rsvp_id_on_cancelled_event_returns_not_found(self, api):
        """PRD 2.5: "Existence checks apply to athletes, zones, activities, segments, efforts, flags, clubs, memberships, challenges, participations, events, RSVPs, and beacon sessions alike."
        PRD 2.5: "then existence of path-referenced resources, then existence of body-referenced foreign-key targets (`creator_id`, `reporter_id`, `segment_id`, and `athlete_id` on joins — failures here surface as `ERR_VALIDATION`), then state-permission checks on the target resource, then the club-archived gate on club-scoped writes, then safety rules, then temporal-window rules, then overlap-conflict rules, then uniqueness and membership constraints, then duplicate-upload detection, then capacity checks, then subscription gating, and finally cross-entity referential consistency. When several of these checks could fail on the same request, the earlier check in this ordering wins and its error code is the one returned."

        Design: Corner/validations/existence_beats_state_on_cancelled_event_rejoin
        """
        owner = create_athlete(api, email="vo_v@x.com", display_name="VO V")
        segment = create_active_segment(
            api, owner["id"], name="Ghost Sprint", sport_type="RIDE",
            start_lat=56.00, start_lng=-141.00, end_lat=56.01, end_lng=-141.00,
            distance_m=1000, city="Ghostville",
        )
        club = create_club(api, owner["id"], name="Ghost Club", sport_type="RIDE", join_policy="OPEN")
        event = create_event(api, club["id"], owner["id"], segment["id"], name="Ghost Race", scheduled_at="2026-09-06T09:00:00Z", capacity=3)
        validate_success(api.cancel_event(club["id"], event["id"], make_athlete_headers(owner["id"])), 200)
        resp = api.rejoin_rsvp(event["id"], NON_EXISTENT_UUID, make_athlete_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_bogus_flag_id_on_uphold_returns_not_found(self, api):
        """PRD 2.5: "A request to a child resource under a nonexistent parent is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that fails to resolve".

        Design: Corner/validations/existence_beats_state_on_cancelled_event_rejoin
        """
        from test_helpers import make_moderator_headers

        resp = api.uphold_flag(NON_EXISTENT_UUID, make_moderator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSafetyBeatsFiscalOnBeaconCreate:
    def test_free_athlete_without_contacts_gets_safety_violation(self, api):
        """PRD 2.5: "then state-permission checks on the target resource, then the club-archived gate on club-scoped writes, then safety rules, then temporal-window rules, then overlap-conflict rules, then uniqueness and membership constraints, then duplicate-upload detection, then capacity checks, then subscription gating, and finally cross-entity referential consistency. When several of these checks could fail on the same request, the earlier check in this ordering wins and its error code is the one returned."
        PRD 3.8: "the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise), must have at least one safety contact (`ERR_SAFETY_VIOLATION` otherwise)".

        Design: Corner/validations/safety_beats_fiscal_on_beacon_create
        """
        athlete = create_athlete(api, email="bf_b@x.com", display_name="BF B")
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION)

    def test_subscribed_athlete_without_contacts_gets_safety_violation(self, api):
        """PRD 3.8: "must have at least one safety contact (`ERR_SAFETY_VIOLATION` otherwise)".

        Design: Corner/validations/safety_beats_fiscal_on_beacon_create
        """
        from test_helpers import create_subscription

        athlete = create_athlete(api, email="bf_c@x.com", display_name="BF C")
        create_subscription(api, athlete["id"])
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION)


class TestLeaderboardFreeTierGate:
    def test_limit_10_allowed_limit_11_gated(self, api):
        """PRD 2.9: "Reading a leaderboard with a `limit` greater than 10. Free-tier callers may only view the top 10 rows plus their own rank; asking for more is rejected with `ERR_SUBSCRIPTION_REQUIRED` (HTTP 402)."

        Design: Corner/validations/leaderboard_free_tier_gated_at_limit_11
        """
        owner = create_athlete(api, email="lg_l@x.com", display_name="LG L")
        rider = create_athlete(api, email="lh_l@x.com", display_name="LH L")
        segment = create_active_segment(
            api, owner["id"], name="Gated Run", sport_type="RUN",
            start_lat=57.00, start_lng=-142.00, end_lat=57.01, end_lng=-142.00,
            distance_m=1000, city="Gateville",
        )
        create_activity_with_effort(api, segment, rider["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        headers = make_athlete_headers(owner["id"])
        ok = api.get_leaderboard(segment["id"], headers, params={"limit": 10})
        validate_success(ok, 200)
        gated = api.get_leaderboard(segment["id"], headers, params={"limit": 11})
        validate_error(gated, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)

    def test_subscribed_athlete_may_read_beyond_limit_10(self, api):
        """PRD 2.9: "Reading a leaderboard with a `limit` greater than 10. Free-tier callers may only view the top 10 rows plus their own rank; asking for more is rejected with `ERR_SUBSCRIPTION_REQUIRED` (HTTP 402)." — the gate applies to free-tier callers.

        Design: Corner/validations/leaderboard_free_tier_gated_at_limit_11
        """
        from test_helpers import create_subscription

        owner = create_athlete(api, email="lg_s@x.com", display_name="LG S")
        create_subscription(api, owner["id"])
        segment = create_active_segment(api, owner["id"], sport_type="RUN", distance_m=1000)
        resp = api.get_leaderboard(segment["id"], make_athlete_headers(owner["id"]), params={"limit": 50})
        validate_success(resp, 200)

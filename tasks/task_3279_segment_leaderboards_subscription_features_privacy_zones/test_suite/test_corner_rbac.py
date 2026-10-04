"""RBAC corner claims: role-based denials."""

from test_helpers import (
    ApiErrorId,
    create_active_challenge,
    create_athlete,
    flag_effort,
    make_athlete_headers,
    make_moderator_headers,
    setup_club_with_member,
    create_active_segment,
    create_activity_with_effort,
    validate_error,
    validate_success,
)


class TestAthleteCannotUpholdFlag:
    def test_athlete_uphold_rejected_forbidden(self, api):
        """PRD 3.6: "Flags are adjudicated by `Moderator`s (and `PlatformAdmin`s)."
        PRD 2.1: "When a request is authenticated but the role is not permitted for the endpoint — including entity-backed ownership violations, such as an athlete acting on another athlete's resource or a club-administrative action attempted by someone without an `ACTIVE` admin membership in that club — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/athlete_cannot_uphold_flag
        """
        reporter = create_athlete(api, email="rb1@x.com", display_name="RB1")
        owner = create_athlete(api, email="rb2@x.com", display_name="RB2")
        segment = create_active_segment(api, reporter["id"], name="RBAC Run", sport_type="RUN", start_lat=66.00, start_lng=-151.00, end_lat=66.01, end_lng=-151.00, distance_m=1000, city="Rbacville")
        pair = create_activity_with_effort(api, segment, owner["id"], elapsed_time_s=100, started_at="2026-09-01T06:00:00Z")
        flag = flag_effort(api, pair["effort"]["id"], reporter["id"])
        resp = api.uphold_flag(flag["id"], make_athlete_headers(reporter["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_moderator_uphold_succeeds(self, api):
        """PRD 3.6: "Flags are adjudicated by `Moderator`s (and `PlatformAdmin`s)."

        Design: Corner/rbac/athlete_cannot_uphold_flag
        """
        reporter = create_athlete(api, email="rb3@x.com", display_name="RB3")
        owner = create_athlete(api, email="rb4@x.com", display_name="RB4")
        segment = create_active_segment(api, reporter["id"], sport_type="RUN", distance_m=1000)
        pair = create_activity_with_effort(api, segment, owner["id"], elapsed_time_s=100)
        flag = flag_effort(api, pair["effort"]["id"], reporter["id"])
        resolved = validate_success(api.uphold_flag(flag["id"], make_moderator_headers()), 200)
        assert resolved["status"] == "UPHELD"


class TestClockEndpointAdminOnly:
    def test_athlete_cannot_set_clock(self, api):
        """PRD 2.6: "A `PlatformAdmin`-only test-driving capability advances the clock to a supplied instant `to_iso8601`".
        PRD 2.1: "When a request is authenticated but the role is not permitted for the endpoint — including entity-backed ownership violations, such as an athlete acting on another athlete's resource or a club-administrative action attempted by someone without an `ACTIVE` admin membership in that club — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/clock_endpoint_admin_only
        """
        athlete = create_athlete(api, email="ck_c@x.com", display_name="CK C")
        resp = api.set_clock("2026-09-02T00:00:00Z", make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_moderator_cannot_set_clock(self, api):
        """PRD 2.6: "A `PlatformAdmin`-only test-driving capability advances the clock to a supplied instant `to_iso8601`".

        Design: Corner/rbac/clock_endpoint_admin_only
        """
        resp = api.set_clock("2026-09-02T00:00:00Z", make_moderator_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestNonAdminCannotStartChallenge:
    def test_plain_member_cannot_start_challenge(self, api):
        """PRD 3.7: "Starting it — a club-admin action requiring the club still be `ACTIVE` and the logical clock's date be no later than `end_date`".
        PRD 3.7: "A club admin — meaning the caller holds an `ACTIVE` membership with `role` `ADMIN` in that same club".

        Design: Corner/rbac/non_admin_cannot_start_challenge
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        from test_helpers import create_challenge

        challenge = create_challenge(api, world["club"]["id"], world["owner"]["id"], name="NoAdmin Challenge")
        resp = api.start_challenge(world["club"]["id"], challenge["id"], make_athlete_headers(world["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_admin_owner_starts_challenge(self, api):
        """PRD 3.7: "The club begins `ACTIVE`, and the founder automatically receives a membership with `role` `ADMIN` and `status` `ACTIVE`."
        PRD 3.7: "Starting it — a club-admin action".

        Design: Corner/rbac/non_admin_cannot_start_challenge
        """
        world = setup_club_with_member(api, join_policy="OPEN")
        challenge = create_active_challenge(api, world["club"]["id"], world["owner"]["id"], name="Admin Start Challenge")
        assert challenge["status"] == "ACTIVE"


class TestAthleteCannotDeleteOtherAthlete:
    def test_delete_other_athlete_forbidden(self, api):
        """PRD 3.1: "Account deletion is self-service only for athletes: the athlete identified in the path must equal the caller's `X-User-ID`, otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/athlete_cannot_delete_other_athlete
        """
        caller = create_athlete(api, email="del1@x.com", display_name="DEL1")
        target = create_athlete(api, email="del2@x.com", display_name="DEL2")
        resp = api.delete_athlete(target["id"], make_athlete_headers(caller["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        still = validate_success(api.get_athlete(target["id"], make_athlete_headers(target["id"])), 200)
        assert still["status"] == "ACTIVE"

    def test_self_delete_allowed(self, api):
        """PRD 3.1: "Account deletion is self-service only for athletes: the athlete identified in the path must equal the caller's `X-User-ID`, otherwise `ERR_FORBIDDEN`. Deletion moves the athlete from `ACTIVE` to `DELETED`".

        Design: Corner/rbac/athlete_cannot_delete_other_athlete
        """
        athlete = create_athlete(api, email="del3@x.com", display_name="DEL3")
        deleted = validate_success(api.delete_athlete(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        assert deleted["status"] == "DELETED"

"""Difficulty queue A: cross-entity state dependencies.

challenge_join_requires_club_membership: participation gated on membership.
beacon_requires_subscription_and_contact: beacon gated on two foreign states.
"""

from test_helpers import (
    ApiErrorId,
    create_active_challenge,
    create_athlete,
    create_club,
    create_safety_contact,
    create_subscription,
    join_club,
    make_athlete_headers,
    validate_error,
    validate_success,
)


class TestChallengeJoinRequiresClubMembership:
    def test_pending_membership_blocks_challenge_join(self, api):
        """PRD 2.1: "When a request is authenticated but the role is not permitted for the endpoint — including entity-backed ownership violations, such as an athlete acting on another athlete's resource or a club-administrative action attempted by someone without an `ACTIVE` admin membership in that club — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 3.7: "under `OPEN`, any `ACTIVE` club member may join".

        Design: Difficulty/cross_entity_state_dependency/challenge_join_requires_club_membership
        """
        owner = create_athlete(api, email="xo_dep@x.com", display_name="XO Dep")
        member = create_athlete(api, email="xm_dep@x.com", display_name="XM Dep")
        club = create_club(api, owner["id"], name="Approval Club", sport_type="RUN", join_policy="APPROVAL")
        membership = join_club(api, club["id"], member["id"])
        assert membership["status"] == "PENDING"
        challenge = create_active_challenge(
            api, club["id"], owner["id"], name="Members Only 10k",
            goal_type="DISTANCE_M", goal_target=10000,
            start_date="2026-09-01", end_date="2026-09-30", join_mode="OPEN",
        )
        resp = api.join_challenge(challenge["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        parts = validate_success(
            api.list_participations(make_athlete_headers(member["id"]), params={"challenge_id": challenge["id"], "athlete_id": member["id"]}),
            200,
        )
        assert parts == []

    def test_approved_membership_allows_challenge_join(self, api):
        """PRD 3.7: "under `OPEN`, any `ACTIVE` club member may join".

        Design: Difficulty/cross_entity_state_dependency/challenge_join_requires_club_membership
        """
        owner = create_athlete(api, email="xo_dep2@x.com", display_name="XO Dep2")
        member = create_athlete(api, email="xm_dep2@x.com", display_name="XM Dep2")
        club = create_club(api, owner["id"], name="Approval Club Two", sport_type="RUN", join_policy="APPROVAL")
        membership = join_club(api, club["id"], member["id"])
        validate_success(api.approve_membership(club["id"], membership["id"], make_athlete_headers(owner["id"])), 200)
        challenge = create_active_challenge(api, club["id"], owner["id"], name="Members Allowed 10k")
        part = validate_success(
            api.join_challenge(challenge["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"])), 201
        )
        assert part["status"] == "JOINED"


class TestBeaconRequiresSubscriptionAndContact:
    def test_cancelled_subscription_blocks_beacon(self, api):
        """PRD 3.8: "the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise)".
        PRD 2.9: "Feature gating flips immediately when a subscription is cancelled or lapses".

        Design: Difficulty/cross_entity_state_dependency/beacon_requires_subscription_and_contact
        """
        athlete = create_athlete(api, email="b_beac@x.com", display_name="B Beac")
        sub = create_subscription(api, athlete["id"], started_at="2026-08-01T00:00:00Z", expires_at="2026-12-01T00:00:00Z")
        from test_helpers import make_platform_admin_headers

        # A safety contact is required so that only the subscription gate can
        # fail: PRD 2.5's priority order places safety rules before
        # subscription gating, so without a contact ERR_SAFETY_VIOLATION would
        # pre-empt the subscription error this test targets.
        create_safety_contact(api, athlete["id"], contact_email="sos1@x.com", label="SOS")
        validate_success(api.cancel_subscription(sub["id"], {}, make_platform_admin_headers()), 200)
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)

    def test_active_subscription_without_contact_reports_safety_violation(self, api):
        """PRD 3.8: "Starting a beacon session is a subscription-gated safety feature with three guards: the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise), must have at least one safety contact (`ERR_SAFETY_VIOLATION` otherwise), and must not already have a `LIVE` session".

        Design: Difficulty/cross_entity_state_dependency/beacon_requires_subscription_and_contact
        """
        athlete = create_athlete(api, email="b_beac2@x.com", display_name="B Beac2")
        create_subscription(api, athlete["id"], plan="SUMMIT_ANNUAL", started_at="2026-09-01T00:00:00Z", expires_at="2027-09-01T00:00:00Z")
        resp = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION)
        create_safety_contact(api, athlete["id"], contact_email="sos2@x.com", label="SOS")
        ok = api.create_beacon_session(athlete["id"], make_athlete_headers(athlete["id"]))
        session = validate_success(ok, 201)
        assert session["status"] == "LIVE"

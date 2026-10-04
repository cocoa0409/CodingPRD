"""Difficulty queue A: compensating invariants.

rsvp_count_invariant: count(GOING RSVPs) == rsvp_count across create/decline/
rejoin.
safety_score_invariant: pinned per-outcome arithmetic (-10 per upheld, +5 per
rejected) clamped to [0, 100].
"""

from test_helpers import (
    create_active_segment,
    create_athlete,
    create_activity_with_effort,
    create_rsvp,
    flag_effort,
    make_athlete_headers,
    reject_flag,
    setup_event_scenario,
    uphold_flag,
    validate_success,
)


class TestRsvpCountInvariant:
    def test_create_decline_rejoin_nets_to_zero(self, api):
        """PRD 3.7: "An `ACTIVE` club member responds to an event by creating an RSVP for an `athlete_id`, which begins `GOING` and increments the event's `rsvp_count` by one."
        PRD 3.7: "The responder may later decline, moving their RSVP from `GOING` to `DECLINED` and decrementing `rsvp_count` by one."
        PRD 3.7: "Declining is cyclic: a `DECLINED` RSVP may return to `GOING` — only by its owner, only while the event is still `PUBLISHED`, and only while the event is under capacity — incrementing `rsvp_count` again."

        Design: Difficulty/compensating_invariant/rsvp_count_invariant
        """
        world = setup_event_scenario(api, capacity=5, scheduled_at="2026-09-06T09:00:00Z")
        member = world["member"]
        event = world["event"]
        reader = make_athlete_headers(world["owner"]["id"])
        member_headers = make_athlete_headers(member["id"])
        before = validate_success(api.get_event(event["id"], reader), 200)
        assert before["rsvp_count"] == 0
        rsvp = create_rsvp(api, event["id"], member["id"])
        after_create = validate_success(api.get_event(event["id"], reader), 200)
        assert after_create["rsvp_count"] == 1
        validate_success(api.decline_rsvp(event["id"], rsvp["id"], member_headers), 200)
        after_decline = validate_success(api.get_event(event["id"], reader), 200)
        assert after_decline["rsvp_count"] == 0
        rejoined = validate_success(api.rejoin_rsvp(event["id"], rsvp["id"], member_headers), 200)
        assert rejoined["status"] == "GOING"
        after_rejoin = validate_success(api.get_event(event["id"], reader), 200)
        assert after_rejoin["rsvp_count"] == 1

    def test_rsvp_count_matches_going_rows(self, api):
        """PRD 3.7: "An `ACTIVE` club member responds to an event by creating an RSVP for an `athlete_id`, which begins `GOING` and increments the event's `rsvp_count` by one."

        Design: Difficulty/compensating_invariant/rsvp_count_invariant
        """
        world = setup_event_scenario(api, capacity=5, scheduled_at="2026-09-06T09:00:00Z")
        extra = create_athlete(api, email="im_inv2@x.com", display_name="IM Inv2")
        from test_helpers import join_club

        join_club(api, world["club"]["id"], extra["id"])
        event = world["event"]
        rsvp1 = create_rsvp(api, event["id"], world["member"]["id"])
        rsvp2 = create_rsvp(api, event["id"], extra["id"])
        reader = make_athlete_headers(world["owner"]["id"])
        state = validate_success(api.get_event(event["id"], reader), 200)
        assert state["rsvp_count"] == 2
        validate_success(api.decline_rsvp(event["id"], rsvp1["id"], make_athlete_headers(world["member"]["id"])), 200)
        state = validate_success(api.get_event(event["id"], reader), 200)
        assert state["rsvp_count"] == 1
        going = validate_success(api.list_event_rsvps(event["id"], reader, params={"status": "GOING"}), 200)
        assert len(going) == 1
        assert going[0]["id"] == rsvp2["id"]


class TestSafetyScoreInvariant:
    def _two_flagged_efforts(self, api, suffix):
        owner = create_athlete(api, email=f"t_{suffix}@x.com", display_name=f"T {suffix}")
        reporter = create_athlete(api, email=f"w_{suffix}@x.com", display_name=f"W {suffix}")
        segment = create_active_segment(
            api, reporter["id"], name=f"Score Run 1k {suffix}", sport_type="RUN",
            start_lat=46.00, start_lng=-131.00, end_lat=46.01, end_lng=-131.00,
            distance_m=1000, city="Scoreville",
        )
        pairs = [
            create_activity_with_effort(
                api, segment, owner["id"], elapsed_time_s=100,
                started_at=f"2026-09-01T0{6 + i}:00:00Z", idempotency_key=f"sc-{suffix}-{i}",
            )
            for i in range(2)
        ]
        flags = [
            flag_effort(api, pairs[0]["effort"]["id"], reporter["id"], reason="IMPOSSIBLE_TIME"),
            flag_effort(api, pairs[1]["effort"]["id"], reporter["id"], reason="VEHICLE_ASSISTED"),
        ]
        return owner, reporter, pairs, flags

    def test_uphold_minus_ten_reject_plus_five_nets_minus_five(self, api):
        """PRD 3.6: "The `safety_score` starts at 100, loses 10 per upheld flag (never below zero), and gains 5 per rejected flag (never above 100)."

        Design: Difficulty/compensating_invariant/safety_score_invariant
        """
        owner, _, pairs, flags = self._two_flagged_efforts(api, "inv1")
        uphold_flag(api, flags[0]["id"])
        mid = validate_success(api.get_athlete(owner["id"], make_athlete_headers(owner["id"])), 200)
        assert mid["safety_score"] == 90
        reject_flag(api, flags[1]["id"])
        end = validate_success(api.get_athlete(owner["id"], make_athlete_headers(owner["id"])), 200)
        assert end["safety_score"] == 95

    def test_upheld_effort_excluded_rejected_effort_restored(self, api):
        """PRD 3.6: "**Upholding** a flag moves it to `UPHELD` and triggers the confirmation cascade: the effort moves from `FLAGGED` to `EXCLUDED` with `exclusion_reason` `FLAG_UPHELD`".
        PRD 3.6: "**Rejecting** a flag moves it to `REJECTED`; when the rejected flag was the last `OPEN` flag on its activity, the effort moves back from `FLAGGED` to `ELIGIBLE` with `exclusion_reason` cleared to null".

        Design: Difficulty/compensating_invariant/safety_score_invariant
        """
        owner, _, pairs, flags = self._two_flagged_efforts(api, "inv2")
        uphold_flag(api, flags[0]["id"])
        reject_flag(api, flags[1]["id"])
        headers = make_athlete_headers(owner["id"])
        excluded = validate_success(api.get_effort(pairs[0]["effort"]["id"], headers), 200)
        assert excluded["flag_status"] == "EXCLUDED"
        assert excluded["exclusion_reason"] == "FLAG_UPHELD"
        restored = validate_success(api.get_effort(pairs[1]["effort"]["id"], headers), 200)
        assert restored["flag_status"] == "ELIGIBLE"
        assert restored["exclusion_reason"] is None

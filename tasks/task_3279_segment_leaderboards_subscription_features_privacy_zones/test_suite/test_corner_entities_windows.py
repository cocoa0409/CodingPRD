"""Entity corner claims (continued): temporal window validations on creation."""

from test_helpers import (
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_club,
    make_athlete_headers,
    validate_error,
)
from test_helpers.factories import create_challenge_payload, create_event_payload


class TestEventFutureScheduling:
    def test_event_scheduled_in_the_past_rejected(self, api):
        """PRD 3.7: "A club admin creates an event with a `name` of 3 to 80 characters, a `segment_id`, a `scheduled_at` instant that must be strictly in the future relative to the logical clock (otherwise `ERR_WINDOW_VIOLATION`)".

        Design: Corner/entities/event_future_scheduling_enforced
        """
        owner = create_athlete(api, email="eo_w@x.com", display_name="EO W")
        segment = create_active_segment(
            api, owner["id"], name="Window Sprint", sport_type="RIDE",
            start_lat=49.00, start_lng=-134.00, end_lat=49.01, end_lng=-134.00,
            distance_m=1000, city="Winville",
        )
        club = create_club(api, owner["id"], name="Window Club", sport_type="RIDE", join_policy="OPEN")
        resp = api.create_event(
            club["id"],
            create_event_payload(segment["id"], name="Past Race", scheduled_at="2026-08-01T09:00:00Z", capacity=10),
            make_athlete_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)

    def test_event_scheduled_at_exactly_now_rejected(self, api):
        """PRD 3.7: "a `scheduled_at` instant that must be strictly in the future relative to the logical clock (otherwise `ERR_WINDOW_VIOLATION`)"; at startup "the logical clock reads exactly 2026-09-01T00:00:00Z" (PRD 2.6).

        Design: Corner/entities/event_future_scheduling_enforced
        """
        owner = create_athlete(api, email="eo_now@x.com", display_name="EO Now")
        segment = create_active_segment(api, owner["id"], sport_type="RIDE")
        club = create_club(api, owner["id"], sport_type="RIDE", join_policy="OPEN")
        resp = api.create_event(
            club["id"],
            create_event_payload(segment["id"], name="Now Race", scheduled_at="2026-09-01T00:00:00Z", capacity=10),
            make_athlete_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)


class TestChallengeWindowOrdering:
    def test_challenge_end_before_start_rejected(self, api):
        """PRD 3.7: "an inclusive window from `start_date` to `end_date` (both YYYY-MM-DD, with `end_date` no earlier than `start_date` — otherwise `ERR_WINDOW_VIOLATION`)".

        Design: Corner/entities/challenge_window_end_before_start_rejected
        """
        owner = create_athlete(api, email="co_ch@x.com", display_name="CO Ch")
        club = create_club(api, owner["id"], name="Window Challenge Club", sport_type="RUN", join_policy="OPEN")
        resp = api.create_challenge(
            club["id"],
            create_challenge_payload(
                name="Backwards", goal_type="DISTANCE_M", goal_target=1000,
                start_date="2026-09-10", end_date="2026-09-01", join_mode="OPEN",
            ),
            make_athlete_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)

    def test_challenge_same_day_window_accepted(self, api):
        """PRD 3.7: "an inclusive window from `start_date` to `end_date` (both YYYY-MM-DD, with `end_date` no earlier than `start_date` — otherwise `ERR_WINDOW_VIOLATION`)" — equal dates satisfy "no earlier than".

        Design: Corner/entities/challenge_window_end_before_start_rejected
        """
        from test_helpers import validate_success, assert_challenge

        owner = create_athlete(api, email="co_eq@x.com", display_name="CO Eq")
        club = create_club(api, owner["id"], name="Same Day Club", sport_type="RUN", join_policy="OPEN")
        resp = api.create_challenge(
            club["id"],
            create_challenge_payload(
                name="Same Day", goal_type="DISTANCE_M", goal_target=1000,
                start_date="2026-09-10", end_date="2026-09-10", join_mode="OPEN",
            ),
            make_athlete_headers(owner["id"]),
        )
        data = validate_success(resp, 201)
        assert_challenge(data)
        assert data["status"] == "DRAFT"

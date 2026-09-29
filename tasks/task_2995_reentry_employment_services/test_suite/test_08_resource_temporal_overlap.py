"""
Intervals compared against other intervals.

Three different overlap rules meet here: a shift against a training session, where
a commute buffer inflates the shift and the comparison is closed; a coach against
their own diary, where the comparison is half-open; and a shift against every
other shift of the same participant, where it is half-open again but reaches
across placements. Each rule is exercised at its touching boundary and then just
past it.
"""

from test_helpers.api_errors import (
    ERR_COACH_DOUBLE_BOOKED,
    ERR_SHIFT_CONFLICTS_SESSION,
    ERR_SHIFT_OVERLAP,
)
from test_helpers.assertions import (
    assert_int_field,
    assert_money_cents,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    ENROLLMENT_ENROLLED,
    SESSION_SCHEDULED,
    SESSION_TYPE_DISCLOSURE_COACHING,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    SESSION_TYPE_RESUME_LAB,
    SHIFT_SCHEDULED,
)
from test_helpers import factories as f
from test_helpers.test_users import CASE_MANAGER, EMPLOYER_LIAISON, FUNDER_ANALYST

COACH = "coach-1"


def _active_placement_with_an_evening_session(api, build):
    """A live placement whose participant is enrolled in a 17:30 session."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    build.case_authorized(participant["id"])
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])

    session = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        coach_user_id=COACH,
        starts_at="2026-08-03T17:30:00.000Z",
        ends_at="2026-08-03T19:00:00.000Z",
    )
    enrollment = build.enrollment(session["id"], participant["id"])
    assert enrollment["status"] == ENROLLMENT_ENROLLED
    return grant, placement, session, enrollment


def test_a_shift_ending_forty_five_minutes_before_a_session_collides_with_it(
    api, build
):
    """
    The buffered shift interval reaches exactly the session's start instant, and the
    closed comparison counts that shared instant as a collision.

    PRD section 3.7: "Adjacency is a conflict here, unlike the shift-versus-shift
    rule: a session ending at 09:00:00.000Z and a shift starting at 09:45:00.000Z
    collide, because the buffered shift interval begins at exactly 09:00:00.000Z and
    the closed comparison counts that shared instant."

    Design: Difficulty/resource_temporal_overlap/shift_versus_enrolled_session_closed_interval_with_commute_buffer
    """
    grant, placement, session, enrollment = _active_placement_with_an_evening_session(
        api, build
    )

    refused = api.create_work_shift(
        placement["id"],
        f.work_shift_payload("2026-08-03T09:00:00.000Z", "2026-08-03T16:45:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_SHIFT_CONFLICTS_SESSION, 409)

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0

    unchanged = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(unchanged, "projected_subsidy_cents", 0)


def test_a_shift_ending_a_quarter_hour_earlier_clears_the_commute_buffer(api, build):
    """
    Fifteen minutes earlier the inflated interval stops short of the session, so the
    shift is accepted and priced on the first subsidy tier.

    PRD section 3.7: "Inflate the proposed shift's interval by forty-five minutes of
    commute buffer on **both** sides and treat the inflated interval as closed —
    including both of its endpoints."

    Seven and a half hours at 1850 cents an hour sits wholly inside the fifty
    percent tier, which is 6,938 cents after the single half-up rounding.

    Design: Difficulty/resource_temporal_overlap/shift_versus_enrolled_session_closed_interval_with_commute_buffer
    """
    grant, placement, session, enrollment = _active_placement_with_an_evening_session(
        api, build
    )

    accepted = validate_unpaginated(
        api.create_work_shift(
            placement["id"],
            f.work_shift_payload("2026-08-03T09:00:00.000Z", "2026-08-03T16:30:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == SHIFT_SCHEDULED
    assert accepted["scheduled_hours"] == 7.5
    assert accepted["conflict_reason"] is None

    settled = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(settled, "projected_subsidy_cents", 6938)
    assert_money_cents(settled, "actual_subsidy_cents", 0)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 6938)

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]

    still_enrolled = validate_unpaginated(api.get_enrollment(enrollment["id"], CASE_MANAGER))
    assert still_enrolled["status"] == ENROLLMENT_ENROLLED


def _two_back_to_back_sessions_for_one_coach(api, build):
    """One coach's diary with two touching bookings in it."""
    first = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        coach_user_id=COACH,
        starts_at="2026-08-03T13:00:00.000Z",
        ends_at="2026-08-03T15:00:00.000Z",
        seat_capacity=3,
    )
    second = validate_unpaginated(
        api.create_readiness_session(
            f.readiness_session_payload(
                COACH,
                "2026-08-03T15:00:00.000Z",
                "2026-08-03T16:30:00.000Z",
                session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
                seat_capacity=3,
            ),
            CASE_MANAGER,
        ),
        201,
    )
    return first, second


def test_two_sessions_touching_at_fifteen_hundred_are_both_accepted(api, build):
    """
    Back-to-back bookings share only an endpoint, and the half-open comparison lets
    both stand with their seats intact.

    PRD section 3.5: "No buffer is applied and no padding is added, so a session
    ending at 12:00:00.000Z and another beginning at exactly 12:00:00.000Z with the
    same coach are both accepted: back-to-back sessions are legitimate."

    Design: Difficulty/resource_temporal_overlap/coach_double_booking_half_open_adjacency_allowed
    """
    first, second = _two_back_to_back_sessions_for_one_coach(api, build)

    for session in (first, second):
        assert session["status"] == SESSION_SCHEDULED
        assert session["coach_user_id"] == COACH
        assert_int_field(session, "enrolled_count", 0)
        assert_int_field(session, "remaining_seats", 3)
        assert_session_seat_identity(session)
    assert first["session_type"] == SESSION_TYPE_DISCLOSURE_COACHING
    assert second["session_type"] == SESSION_TYPE_INTERVIEW_PRACTICE


def test_a_third_session_straddling_both_double_books_the_coach(api, build):
    """
    A booking that genuinely overlaps one of the two is refused, and the coach's
    diary still holds exactly the two accepted sessions.

    PRD section 3.5: "Booking is refused with `ERR_COACH_DOUBLE_BOOKED` when the
    proposed interval, treated as half-open — including its start instant and
    excluding its end instant — intersects the interval of another session whose
    `status` is `SCHEDULED` and whose `coach_user_id` is the same."

    Design: Difficulty/resource_temporal_overlap/coach_double_booking_half_open_adjacency_allowed
    """
    first, second = _two_back_to_back_sessions_for_one_coach(api, build)

    refused = api.create_readiness_session(
        f.readiness_session_payload(
            COACH,
            "2026-08-03T14:30:00.000Z",
            "2026-08-03T16:00:00.000Z",
            session_type=SESSION_TYPE_RESUME_LAB,
            seat_capacity=3,
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_COACH_DOUBLE_BOOKED, 409)

    rows, meta = validate_paginated(
        api.list_readiness_sessions(CASE_MANAGER, f.page_params(coach_user_id=COACH))
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def _one_participant_on_two_placements(api, build):
    """The same participant working two openings at one employer, morning and afternoon."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    build.case_authorized(participant["id"])
    partnership = build.partnership_active(max_concurrent_placements=2)
    morning_opening = build.job_opening(partnership["id"], openings_count=1)
    afternoon_opening = build.job_opening(
        partnership["id"], title="Yard Attendant", openings_count=1
    )
    morning = build.placement_active(participant["id"], morning_opening["id"], grant["id"])
    afternoon = build.placement_active(
        participant["id"], afternoon_opening["id"], grant["id"]
    )
    morning_shift = build.work_shift(
        morning["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T13:00:00.000Z"
    )
    assert morning_shift["scheduled_hours"] == 4.0
    return grant, partnership, morning, afternoon, morning_shift


def test_a_shift_touching_another_placements_shift_is_accepted(api, build):
    """
    The half-open rule reaches across placements but forgives the shared 13:00
    endpoint, and each placement walks its own cumulative tier ladder from zero.

    PRD section 3.7: "Touching endpoints do not intersect, so a shift ending at
    17:00:00.000Z and another beginning at exactly 17:00:00.000Z are both accepted."

    Design: Difficulty/resource_temporal_overlap/shift_versus_shift_half_open_overlap_across_two_placements
    """
    grant, partnership, morning, afternoon, morning_shift = _one_participant_on_two_placements(
        api, build
    )

    accepted = validate_unpaginated(
        api.create_work_shift(
            afternoon["id"],
            f.work_shift_payload("2026-08-03T13:00:00.000Z", "2026-08-03T17:00:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == SHIFT_SCHEDULED
    assert accepted["scheduled_hours"] == 4.0

    for placement in (morning, afternoon):
        stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
        assert_money_cents(stored, "projected_subsidy_cents", 3700)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 7400)

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(stored_partnership, "active_placement_count", 2)


def test_a_shift_overlapping_another_placements_shift_is_refused(api, build):
    """
    A genuine intersection with the other placement's shift is refused even though
    the two shifts belong to different placements.

    PRD section 3.7: "Treating each interval as half-open — including its start
    instant and excluding its end instant — the proposed interval must not intersect
    the interval of any other work shift whose `status` is `SCHEDULED`,
    `CONFLICTED`, or `WORKED` and which belongs to any placement of the same
    participant, not merely to the same placement."

    Design: Difficulty/resource_temporal_overlap/shift_versus_shift_half_open_overlap_across_two_placements
    """
    grant, partnership, morning, afternoon, morning_shift = _one_participant_on_two_placements(
        api, build
    )
    validate_unpaginated(
        api.create_work_shift(
            afternoon["id"],
            f.work_shift_payload("2026-08-03T13:00:00.000Z", "2026-08-03T17:00:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )

    refused = api.create_work_shift(
        afternoon["id"],
        f.work_shift_payload("2026-08-03T12:00:00.000Z", "2026-08-03T16:00:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_SHIFT_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_work_shifts(CASE_MANAGER, f.page_params(placement_id=afternoon["id"]))
    )
    assert meta["total_count"] == 1

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 7400)

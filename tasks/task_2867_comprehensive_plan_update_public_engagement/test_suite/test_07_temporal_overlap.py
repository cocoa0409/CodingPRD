"""Interval semantics for the three shared calendars: venues, the plan's
environmental circulation window and the plan's hearing calendar.

The three resources deliberately disagree. A venue interval is half-open and
widened symmetrically by the room's turnover buffer, so adjacency is legal at a
zero buffer and illegal at any positive one. A circulation window and a hearing
slot are both closed, so touching endpoints collide. On top of the hearing
interval sits a per-body daily cap, and the whole hearing calendar is scoped per
`body_type`.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COMMISSION_RECOMMENDATION_REQUIRED,
    ERR_HEARING_DAILY_CAP_EXCEEDED,
    ERR_HEARING_SLOT_CONFLICT,
    ERR_REVIEW_WINDOW_OVERLAP,
    ERR_VENUE_TIME_CONFLICT,
)
from test_helpers.test_users import CLERK, CONSULTANT, STAFF
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

# One evening on a venue calendar. The clock stays at its 2026-08-01T00:00:00Z
# startup value throughout the venue tests, so nothing here has happened yet.
EVENING_START = "2026-08-20T18:00:00.000Z"
EVENING_END = "2026-08-20T20:00:00.000Z"
LATE_START = "2026-08-20T20:00:00.000Z"
LATE_END = "2026-08-20T22:00:00.000Z"
AFTER_BUFFER_START = "2026-08-20T20:30:00.000Z"
AFTER_BUFFER_END = "2026-08-20T22:30:00.000Z"
EARLY_START = "2026-08-20T19:00:00.000Z"
EARLY_END = "2026-08-20T20:00:00.000Z"


def _venue_with_workshop(api, plan_id, buffer_minutes, name):
    """A venue holding one scheduled 18:00-20:00 workshop."""
    venue = fx.create_venue(
        api,
        name=name,
        seated_capacity=120,
        turnover_buffer_minutes=buffer_minutes,
        ada_accessible=True,
        transit_served=True,
    )
    activity = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Evening Workshop",
        venue_id=venue["id"],
        start_at=EVENING_START,
        end_at=EVENING_END,
    )
    return venue, activity


# --------------------------------------------------------------------------
# Venue occupancy: half-open, symmetric buffer
# --------------------------------------------------------------------------
def test_back_to_back_booking_is_accepted_at_a_zero_buffer_venue(api):
    """A second workshop starting at the exact instant the first ended is booked.

    "The consequence of the strict comparisons is worth spelling out: at a venue
    whose `turnover_buffer_minutes` is 0, an activity starting at the exact instant
    an earlier one ended is allowed, because neither comparison is satisfied at the
    boundary; at a venue with any positive buffer, that same back-to-back pair
    conflicts."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_at_zero_buffer_and_blocked_by_buffer
    """
    plan = fx.create_plan(api)
    venue, incumbent = _venue_with_workshop(api, plan["id"], 0, "Eastside Community Room")
    assert venue["turnover_buffer_minutes"] == 0

    later = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Eastside Late Workshop",
                venue_id=venue["id"],
                start_at=LATE_START,
                end_at=LATE_END,
            ),
            STAFF,
        ),
        201,
    )

    assert later["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert later["start_at"] == incumbent["end_at"]
    rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {incumbent["id"], later["id"]}


def test_the_same_back_to_back_booking_is_refused_at_a_thirty_minute_buffer(api):
    """The identical wall-clock adjacency collides once the room needs turnover time.

    "The proposed activity conflicts with an existing activity at the same venue
    whose status is `SCHEDULED` or `COMPLETED` when the proposed `start_at` moved
    earlier by the buffer falls strictly before the existing activity's `end_at`, and
    at the same time the proposed `end_at` moved later by the buffer falls strictly
    after the existing activity's `start_at`."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_at_zero_buffer_and_blocked_by_buffer
    """
    plan = fx.create_plan(api)
    venue, _ = _venue_with_workshop(api, plan["id"], 30, "Civic Auditorium")
    assert venue["turnover_buffer_minutes"] == 30

    response = api.create_engagement_activity(
        f.engagement_activity_payload(
            plan["id"],
            activity_type=C.ACTIVITY_WORKSHOP,
            title="Auditorium Late Workshop",
            venue_id=venue["id"],
            start_at=LATE_START,
            end_at=LATE_END,
        ),
        STAFF,
    )

    validate_error(response, ERR_VENUE_TIME_CONFLICT)
    _, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 1


def test_a_buffered_room_frees_up_exactly_one_buffer_after_the_incumbent_ends(api):
    """Starting 30 minutes later puts the shifted start on the boundary, where the
    strict comparison no longer holds.

    "Both conditions must hold for a conflict, which is reported as
    `ERR_VENUE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_at_zero_buffer_and_blocked_by_buffer
    """
    plan = fx.create_plan(api)
    venue, _ = _venue_with_workshop(api, plan["id"], 30, "Civic Auditorium")

    accepted = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Auditorium Late Workshop",
                venue_id=venue["id"],
                start_at=AFTER_BUFFER_START,
                end_at=AFTER_BUFFER_END,
            ),
            STAFF,
        ),
        201,
    )

    assert accepted["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert accepted["start_at"] == AFTER_BUFFER_START


def test_cancelling_a_booking_frees_the_interval_it_held(api):
    """The 19:00-20:00 slot is unbookable while the incumbent stands and bookable
    once it is cancelled.

    "Activities in `CANCELLED` release their interval entirely and never conflict
    with anything."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_at_zero_buffer_and_blocked_by_buffer
    """
    plan = fx.create_plan(api)
    venue, incumbent = _venue_with_workshop(api, plan["id"], 30, "Civic Auditorium")
    later = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Auditorium Late Workshop",
        venue_id=venue["id"],
        start_at=AFTER_BUFFER_START,
        end_at=AFTER_BUFFER_END,
    )

    early_payload = f.engagement_activity_payload(
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Auditorium Early Workshop",
        venue_id=venue["id"],
        start_at=EARLY_START,
        end_at=EARLY_END,
    )
    validate_error(
        api.create_engagement_activity(early_payload, STAFF), ERR_VENUE_TIME_CONFLICT
    )

    cancelled = fx.cancel_activity(
        api, incumbent["id"], reason="Consolidated into the later session."
    )
    assert cancelled["status"] == C.ACTIVITY_STATUS_CANCELLED

    early = validate_success(api.create_engagement_activity(early_payload, STAFF), 201)
    assert early["status"] == C.ACTIVITY_STATUS_SCHEDULED

    rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 3
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[incumbent["id"]] == C.ACTIVITY_STATUS_CANCELLED
    assert by_id[later["id"]] == C.ACTIVITY_STATUS_SCHEDULED
    assert by_id[early["id"]] == C.ACTIVITY_STATUS_SCHEDULED
    assert fx.read_plan(api, plan["id"])["participation_weight_total"] == 0.0


# --------------------------------------------------------------------------
# Environmental circulation window: closed interval, derived from the clock
# --------------------------------------------------------------------------
CLOCK_SECOND_ATTEMPT = "2026-09-15T00:00:00.000Z"
CLOCK_THIRD_ATTEMPT = "2026-09-16T00:00:00.000Z"
SECOND_WINDOW_END = "2026-10-31T00:00:00.000Z"


def _two_draft_eirs(api):
    """One plan carrying two circulation-ready EIRs."""
    plan = fx.create_plan(api)
    first = fx.create_review(api, plan["id"], C.DOC_EIR, title="Horizon 2045 Draft EIR")
    second = fx.create_review(
        api, plan["id"], C.DOC_EIR, title="Horizon 2045 Recirculated EIR"
    )
    for review in (first, second):
        for spec in fx.DEFAULT_ALTERNATIVES:
            fx.add_alternative(api, review["id"], **spec)
    return plan, first, second


def test_the_first_eir_window_is_taken_from_the_clock_and_the_statutory_period(api):
    """Circulating at the startup instant stamps a 45-day window ending 2026-09-15.

    "`comment_period_days` is stamped with the statutory period — 45 days for an
    `EIR` and 30 days for a `NEGATIVE_DECLARATION` — `comment_period_ends_at` is
    computed as `circulated_at` advanced by that many days"

    Design: Difficulty/resource_temporal_overlap/review_circulation_window_closed_interval_touching_endpoint_conflict
    """
    _, first, _ = _two_draft_eirs(api)

    circulated = fx.circulate_review(api, first["id"])

    assert circulated["status"] == C.REVIEW_STATUS_CIRCULATED
    assert circulated["circulated_at"] == C.CLOCK_STARTUP
    assert circulated["comment_period_days"] == C.COMMENT_PERIOD_DAYS[C.DOC_EIR]
    assert circulated["comment_period_ends_at"] == CLOCK_SECOND_ATTEMPT


def test_a_second_window_opening_on_the_first_windows_last_instant_is_refused(api):
    """The windows touch at 2026-09-15 and touching is enough, because the interval
    is closed on both ends.

    "An overlap exists when the new window's start is not later than the other
    window's end and the new window's end is not earlier than the other window's
    start; the rejection is `ERR_REVIEW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/review_circulation_window_closed_interval_touching_endpoint_conflict
    """
    _, first, second = _two_draft_eirs(api)
    fx.circulate_review(api, first["id"])
    fx.set_clock(api, CLOCK_SECOND_ATTEMPT)

    response = api.circulate_environmental_review(second["id"], {}, CONSULTANT)

    validate_error(response, ERR_REVIEW_WINDOW_OVERLAP)
    untouched = validate_success(api.get_environmental_review(second["id"], CONSULTANT))
    assert untouched["status"] == C.REVIEW_STATUS_DRAFT
    assert untouched["circulated_at"] is None
    assert untouched["comment_period_ends_at"] is None


def test_one_day_later_the_second_window_clears_the_first_and_circulates(api):
    """Moved one calendar day on, the new window starts after the incumbent's last
    instant and both reviews stand circulated with disjoint windows.

    "it is compared as a closed interval against the window of every other review of
    the same plan whose status is `CIRCULATED` or `CERTIFIED`"

    Design: Difficulty/resource_temporal_overlap/review_circulation_window_closed_interval_touching_endpoint_conflict
    """
    plan, first, second = _two_draft_eirs(api)
    fx.circulate_review(api, first["id"])
    fx.set_clock(api, CLOCK_SECOND_ATTEMPT)
    validate_error(
        api.circulate_environmental_review(second["id"], {}, CONSULTANT),
        ERR_REVIEW_WINDOW_OVERLAP,
    )

    fx.set_clock(api, CLOCK_THIRD_ATTEMPT)
    circulated = fx.circulate_review(api, second["id"])

    assert circulated["status"] == C.REVIEW_STATUS_CIRCULATED
    assert circulated["circulated_at"] == CLOCK_THIRD_ATTEMPT
    assert circulated["comment_period_ends_at"] == SECOND_WINDOW_END
    incumbent = validate_success(api.get_environmental_review(first["id"], CONSULTANT))
    assert incumbent["status"] == C.REVIEW_STATUS_CIRCULATED
    assert fx.read_plan(api, plan["id"])["compliance_posture"] == C.POSTURE_CAPACITY_HOLD


# --------------------------------------------------------------------------
# Hearing calendar: closed interval, no buffer, scoped and capped per body
# --------------------------------------------------------------------------
INCUMBENT_START = "2026-09-25T18:00:00.000Z"
INCUMBENT_END = "2026-09-25T21:00:00.000Z"
TOUCHING_START = "2026-09-25T21:00:00.000Z"
TOUCHING_END = "2026-09-25T23:00:00.000Z"
CLEAR_START = "2026-09-25T21:00:00.001Z"
MORNING_START = "2026-09-25T09:00:00.000Z"
MORNING_END = "2026-09-25T11:00:00.000Z"
NEXT_DATE_START = "2026-09-26T18:00:00.000Z"
NEXT_DATE_END = "2026-09-26T21:00:00.000Z"
NOTICE = "2026-09-15T00:00:00.000Z"


def _certified_plan_with_one_hearing(api):
    """A STATE_CERTIFIED plan whose commission calendar holds one 18:00-21:00 slot."""
    ctx = fx.state_certified_plan(api)
    incumbent = fx.create_hearing(
        api,
        ctx["plan_id"],
        body_type=C.BODY_COMMISSION,
        scheduled_start=INCUMBENT_START,
        scheduled_end=INCUMBENT_END,
        notice_published_at=NOTICE,
    )
    return ctx, incumbent


def test_a_commission_slot_starting_when_the_incumbent_ends_conflicts(api):
    """Hearing slots touch at 21:00 and that is a conflict, the mirror image of the
    venue rule.

    "Touching endpoints *are* a conflict here — the exact opposite of the venue rule
    in section 3.6, where a zero buffer makes adjacency legal — and hearings of the
    other body never conflict with each other."

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_closed_interval_and_daily_cap_per_body
    """
    ctx, incumbent = _certified_plan_with_one_hearing(api)
    assert ctx["plan"]["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert incumbent["status"] == C.HEARING_STATUS_SCHEDULED
    assert incumbent["notice_published_at"] == NOTICE

    response = api.create_hearing(
        f.hearing_payload(
            ctx["plan_id"],
            body_type=C.BODY_COMMISSION,
            scheduled_start=TOUCHING_START,
            scheduled_end=TOUCHING_END,
            notice_published_at=NOTICE,
        ),
        CLERK,
    )

    validate_error(response, ERR_HEARING_SLOT_CONFLICT)
    _, meta = validate_paginated(
        api.list_plan_hearings(ctx["plan_id"], CLERK, params={"body_type": C.BODY_COMMISSION})
    )
    assert meta["total_count"] == 1


def test_one_millisecond_past_the_incumbents_end_is_a_clean_slot(api):
    """Moving the start a single millisecond later makes the closed intervals
    disjoint.

    "the new hearing conflicts with an existing hearing of the same `plan_update_id`
    and the same `body_type` whose status is `SCHEDULED`, `BLOCKED` or `OPEN` when the
    new `scheduled_start` is not later than the existing `scheduled_end` and the new
    `scheduled_end` is not earlier than the existing `scheduled_start`."

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_closed_interval_and_daily_cap_per_body
    """
    ctx, _ = _certified_plan_with_one_hearing(api)

    accepted = validate_success(
        api.create_hearing(
            f.hearing_payload(
                ctx["plan_id"],
                body_type=C.BODY_COMMISSION,
                scheduled_start=CLEAR_START,
                scheduled_end=TOUCHING_END,
                notice_published_at=NOTICE,
            ),
            CLERK,
        ),
        201,
    )

    assert accepted["status"] == C.HEARING_STATUS_SCHEDULED
    assert accepted["scheduled_start"] == CLEAR_START
    assert accepted["amendment_count"] == 0


def test_the_third_commission_slot_of_a_date_is_capped_but_the_next_date_is_free(api):
    """Two commission hearings exhaust the date even for a slot that overlaps
    nothing, while the following UTC date starts a fresh count.

    "at most two hearings of the same plan and the same body may have their
    `scheduled_start` fall on the same UTC calendar date, and that count includes
    hearings in every status"

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_closed_interval_and_daily_cap_per_body
    """
    ctx, _ = _certified_plan_with_one_hearing(api)
    fx.create_hearing(
        api,
        ctx["plan_id"],
        body_type=C.BODY_COMMISSION,
        scheduled_start=CLEAR_START,
        scheduled_end=TOUCHING_END,
        notice_published_at=NOTICE,
    )

    capped = api.create_hearing(
        f.hearing_payload(
            ctx["plan_id"],
            body_type=C.BODY_COMMISSION,
            scheduled_start=MORNING_START,
            scheduled_end=MORNING_END,
            notice_published_at=NOTICE,
        ),
        CLERK,
    )
    validate_error(capped, ERR_HEARING_DAILY_CAP_EXCEEDED)

    next_day = validate_success(
        api.create_hearing(
            f.hearing_payload(
                ctx["plan_id"],
                body_type=C.BODY_COMMISSION,
                scheduled_start=NEXT_DATE_START,
                scheduled_end=NEXT_DATE_END,
                notice_published_at=NOTICE,
            ),
            CLERK,
        ),
        201,
    )
    assert next_day["status"] == C.HEARING_STATUS_SCHEDULED

    _, meta = validate_paginated(
        api.list_plan_hearings(ctx["plan_id"], CLERK, params={"body_type": C.BODY_COMMISSION})
    )
    assert meta["total_count"] == 3


def test_a_council_slot_duplicating_the_commission_slot_needs_the_recommendation(api):
    """A council booking never meets the commission calendar, so it is answered by
    the prerequisite on the plan's own progress and no council row appears.

    "a `COUNCIL` hearing may only be scheduled once the plan has reached
    `COMMISSION_RECOMMENDED`, and an earlier attempt is refused with
    `ERR_COMMISSION_RECOMMENDATION_REQUIRED`"

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_closed_interval_and_daily_cap_per_body
    """
    ctx, _ = _certified_plan_with_one_hearing(api)

    response = api.create_hearing(
        f.hearing_payload(
            ctx["plan_id"],
            body_type=C.BODY_COUNCIL,
            scheduled_start=INCUMBENT_START,
            scheduled_end=INCUMBENT_END,
            notice_published_at=NOTICE,
        ),
        CLERK,
    )

    validate_error(response, ERR_COMMISSION_RECOMMENDATION_REQUIRED)
    _, council = validate_paginated(
        api.list_plan_hearings(ctx["plan_id"], CLERK, params={"body_type": C.BODY_COUNCIL})
    )
    assert council["total_count"] == 0
    _, commission = validate_paginated(
        api.list_plan_hearings(ctx["plan_id"], CLERK, params={"body_type": C.BODY_COMMISSION})
    )
    assert commission["total_count"] == 1

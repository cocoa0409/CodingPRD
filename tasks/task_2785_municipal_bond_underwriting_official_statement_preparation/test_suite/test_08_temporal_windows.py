"""Two contended resources with two different interval conventions.

An order period occupies the **half-open** interval ``[opens_at, closes_at)`` on
its deal's order book with no buffer at all, so abutting windows are legal. A
rating presentation occupies a **closed** interval expanded by sixty minutes at
each end, scoped to one agency, so an exactly-sixty-minute gap is legal, a
fifty-nine-minute gap is not, and two agencies may sit on the very same instant.

Every test here translates one instance of the DIFFICULTY design index; the
``Design:`` line of each docstring names it.
"""

from datetime import timedelta

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_common_fields, assert_pagination, ids_of
from test_helpers.constants import (
    ATTENDEE_COUNT_MAX,
    CLOCK_EPOCH,
    PRESENTATION_BUFFER_MINUTES,
    iso_utc,
    parse_iso,
    plus_days,
    plus_hours,
    plus_minutes,
)
from test_helpers.types import (
    OrderPeriodStatus,
    PeriodType,
    PresentationStatus,
    PriorityPolicy,
    RatingAgency,
)


# ---------------------------------------------------------------------------
# The order book's half-open windows (PRD section 3.7)
# ---------------------------------------------------------------------------
# The design index works its order-period case on 2026-08-05, four days after
# the logical clock's epoch. Scheduling never reads the clock, so the clock is
# left at its default throughout.
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
WINDOW_A_OPENS = plus_hours(BOOK_DAY, 13)
WINDOW_A_CLOSES = plus_hours(BOOK_DAY, 17)
WINDOW_B_CLOSES = plus_hours(BOOK_DAY, 21)
WINDOW_C_CLOSES = plus_hours(BOOK_DAY, 22)


def _one_second_before(instant):
    """The instant one second earlier, in the API's ISO 8601 UTC shape.

    ``test_helpers.constants`` exposes minute, hour and day arithmetic; a
    one-second intrusion into an existing window needs finer granularity than
    that, so it is built from the same ``parse_iso``/``iso_utc`` pair.
    """
    return iso_utc(parse_iso(instant) - timedelta(seconds=1))


def _institutional_window(opens_at, closes_at):
    """An INSTITUTIONAL order period payload under the default priority policy."""
    return f.order_period_payload(
        opens_at,
        closes_at,
        PeriodType.INSTITUTIONAL,
        priority_policy=PriorityPolicy.STANDARD_PRIORITY,
    )


def _schedule_window(ctx, opens_at, closes_at):
    """Schedule one institutional window as the deal's municipal advisor."""
    return ctx.client.create_order_period(
        ctx.deal_id, _institutional_window(opens_at, closes_at), ctx.advisor_headers
    )


def _assert_fresh_scheduled_period(period, label):
    """PRD section 3.7: a new period is SCHEDULED with allotment_run_count zero."""
    assert_common_fields(period, label)
    assert period["status"] == OrderPeriodStatus.SCHEDULED, (
        f"{label}.status: expected {OrderPeriodStatus.SCHEDULED}, "
        f"got {period['status']!r}"
    )
    assert period["allotment_run_count"] == 0, (
        f"{label}.allotment_run_count: expected 0, "
        f"got {period['allotment_run_count']!r}"
    )


# ---------------------------------------------------------------------------
# The per-agency presentation buffer (PRD section 3.5)
# ---------------------------------------------------------------------------
# The design index works its presentation case on 2026-08-10, nine days after
# the epoch, so nothing on the calendar is promoted to HELD.
AGENCY_DAY = plus_days(CLOCK_EPOCH, 9)
HELD_SLOT_STARTS = plus_hours(AGENCY_DAY, 14)
HELD_SLOT_ENDS = plus_hours(AGENCY_DAY, 16)
# Exactly PRESENTATION_BUFFER_MINUTES after the existing slot's ends_at.
LATER_SLOT_STARTS = plus_minutes(HELD_SLOT_ENDS, PRESENTATION_BUFFER_MINUTES)
LATER_SLOT_ENDS = plus_hours(LATER_SLOT_STARTS, 2)
# Exactly PRESENTATION_BUFFER_MINUTES before the existing slot's starts_at.
EARLIER_SLOT_STARTS = plus_hours(AGENCY_DAY, 12)
EARLIER_SLOT_ENDS = plus_minutes(HELD_SLOT_STARTS, -PRESENTATION_BUFFER_MINUTES)
# One minute later leaves a gap of only fifty-nine minutes.
TOO_LATE_SLOT_ENDS = plus_minutes(EARLIER_SLOT_ENDS, 1)
# A second agency's slot lying wholly inside the first agency's window.
OTHER_AGENCY_STARTS = plus_minutes(HELD_SLOT_STARTS, 30)
OTHER_AGENCY_ENDS = plus_minutes(OTHER_AGENCY_STARTS, 60)


def _two_agency_engagements(ctx):
    """A MOODYS and an SP engagement, the MOODYS one already carrying a slot.

    Returns ``(moodys_engagement_id, sp_engagement_id, existing_presentation)``,
    where the existing presentation runs from 14:00 to 16:00 UTC and is
    SCHEDULED, because the clock still stands at its epoch.
    """
    moodys = fx.request_rating(
        ctx.client, ctx.deal_id, ctx.advisor_headers, RatingAgency.MOODYS
    )
    sp = fx.request_rating(
        ctx.client, ctx.deal_id, ctx.advisor_headers, RatingAgency.SP
    )
    existing = fx.schedule_presentation(
        ctx.client,
        moodys["id"],
        ctx.advisor_headers,
        HELD_SLOT_STARTS,
        HELD_SLOT_ENDS,
    )
    return moodys["id"], sp["id"], existing


def _assert_fresh_scheduled_presentation(presentation, label):
    """PRD section 3.5: a new presentation is SCHEDULED with no cancellation."""
    assert_common_fields(presentation, label)
    assert presentation["status"] == PresentationStatus.SCHEDULED, (
        f"{label}.status: expected {PresentationStatus.SCHEDULED}, "
        f"got {presentation['status']!r}"
    )
    assert presentation["cancellation_reason"] is None, (
        f"{label}.cancellation_reason: expected null, "
        f"got {presentation['cancellation_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Order periods: the half-open interval admits abutting windows
# ---------------------------------------------------------------------------
def test_abutting_order_periods_are_both_permitted(client, draft_deal):
    """PRD 3.7: "Because the interval is half-open, **abutting** windows do not
    overlap: a retail period closing at a given instant and an institutional
    period opening at exactly that same instant are both permitted, and this is
    the normal way to run a retail order period immediately ahead of the
    institutional book."

    Design: Difficulty/resource_temporal_overlap/order_period_half_open_adjacency_allowed
    """
    ctx = draft_deal

    first = validate_success(
        _schedule_window(ctx, WINDOW_A_OPENS, WINDOW_A_CLOSES), 201
    )
    # Opens at exactly the first window's closes_at: abutting, not overlapping.
    second = validate_success(
        _schedule_window(ctx, WINDOW_A_CLOSES, WINDOW_B_CLOSES), 201
    )
    # Abutting the second window on its far side, by the same convention.
    third = validate_success(
        _schedule_window(ctx, WINDOW_B_CLOSES, WINDOW_C_CLOSES), 201
    )

    rows, meta = validate_paginated(
        client.list_deal_order_periods(ctx.deal_id, ctx.compliance_headers)
    )
    assert_pagination(meta, total_count=3)
    assert set(ids_of(rows)) == {first["id"], second["id"], third["id"]}, (
        "the three accepted windows should be exactly the deal's order periods"
    )

    for period, label in (
        (first, "period[13:00-17:00]"),
        (second, "period[17:00-21:00]"),
        (third, "period[21:00-22:00]"),
    ):
        _assert_fresh_scheduled_period(period, label)


def test_one_second_intrusion_into_an_existing_window_is_refused(client, draft_deal):
    """PRD 3.7: "Each period occupies the half-open interval from `opens_at`
    inclusive to `closes_at` exclusive, and a new period's interval must not
    overlap the interval of any existing period of the same deal that is not
    `CANCELLED`; a violation is refused with `ERR_ORDER_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/order_period_half_open_adjacency_allowed
    """
    ctx = draft_deal
    validate_success(_schedule_window(ctx, WINDOW_A_OPENS, WINDOW_A_CLOSES), 201)
    validate_success(_schedule_window(ctx, WINDOW_A_CLOSES, WINDOW_B_CLOSES), 201)

    # One second earlier than the abutting instant, so the new window contains
    # the final second of the 17:00-21:00 period.
    intruder = _schedule_window(
        ctx, _one_second_before(WINDOW_B_CLOSES), WINDOW_C_CLOSES
    )
    validate_error(intruder, err.ERR_ORDER_PERIOD_OVERLAP)

    _, meta = validate_paginated(
        client.list_deal_order_periods(ctx.deal_id, ctx.compliance_headers)
    )
    assert_pagination(meta, total_count=2)


# ---------------------------------------------------------------------------
# Presentations: the closed interval expanded by a clear hour at each end
# ---------------------------------------------------------------------------
def test_presentation_gap_of_exactly_sixty_minutes_is_permitted(client, draft_deal):
    """PRD 3.5: "The boundary is exact: a gap of precisely sixty minutes between
    one presentation's `ends_at` and the next presentation's `starts_at` is
    permitted, while a gap of fifty-nine minutes is not."

    Design: Difficulty/resource_temporal_overlap/rating_presentation_closed_interval_sixty_minute_buffer
    """
    ctx = draft_deal
    moodys_id, _sp_id, existing = _two_agency_engagements(ctx)

    # Exactly PRESENTATION_BUFFER_MINUTES after the existing slot's ends_at.
    later = validate_success(
        client.create_presentation(
            moodys_id,
            f.presentation_payload(LATER_SLOT_STARTS, LATER_SLOT_ENDS),
            ctx.advisor_headers,
        ),
        201,
    )
    # Exactly PRESENTATION_BUFFER_MINUTES before the existing slot's starts_at.
    earlier = validate_success(
        client.create_presentation(
            moodys_id,
            f.presentation_payload(EARLIER_SLOT_STARTS, EARLIER_SLOT_ENDS),
            ctx.advisor_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        client.list_engagement_presentations(moodys_id, ctx.compliance_headers)
    )
    assert_pagination(meta, total_count=3)
    assert set(ids_of(rows)) == {existing["id"], later["id"], earlier["id"]}, (
        "the agency's calendar should hold exactly the three accepted slots"
    )

    for presentation, label in (
        (existing, "presentation[14:00-16:00]"),
        (later, "presentation[17:00-19:00]"),
        (earlier, "presentation[12:00-13:00]"),
    ):
        _assert_fresh_scheduled_presentation(presentation, label)


def test_presentation_gap_of_fifty_nine_minutes_is_refused(client, draft_deal):
    """PRD 3.5: "Take the new presentation's closed interval from `starts_at`
    through `ends_at` and expand it by sixty minutes at each end. If that
    expanded interval contains any instant belonging to an existing presentation
    that is not `CANCELLED` and that belongs to a rating engagement of the *same*
    deal with the *same* `agency`, the request is refused with
    `ERR_PRESENTATION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rating_presentation_closed_interval_sixty_minute_buffer
    """
    ctx = draft_deal
    moodys_id, _sp_id, _existing = _two_agency_engagements(ctx)

    # One minute longer than the permitted slot, so only fifty-nine minutes of
    # clear time separate it from the existing 14:00 start.
    conflicting = client.create_presentation(
        moodys_id,
        f.presentation_payload(EARLIER_SLOT_STARTS, TOO_LATE_SLOT_ENDS),
        ctx.advisor_headers,
    )
    validate_error(conflicting, err.ERR_PRESENTATION_BUFFER_CONFLICT)

    _, meta = validate_paginated(
        client.list_engagement_presentations(moodys_id, ctx.compliance_headers)
    )
    assert_pagination(meta, total_count=1)


def test_different_agencies_may_occupy_the_same_instant(client, draft_deal):
    """PRD 3.5: "Presentations for *different* agencies on the same deal are free
    to overlap without restriction, since each agency sits in its own room."

    Design: Difficulty/resource_temporal_overlap/rating_presentation_closed_interval_sixty_minute_buffer
    """
    ctx = draft_deal
    moodys_id, sp_id, _existing = _two_agency_engagements(ctx)

    # Wholly inside the MOODYS window, which the buffer would forbid outright
    # were the two engagements for the same agency.
    other_agency = validate_success(
        client.create_presentation(
            sp_id,
            f.presentation_payload(
                OTHER_AGENCY_STARTS, OTHER_AGENCY_ENDS, attendee_count=8
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    _assert_fresh_scheduled_presentation(other_agency, "presentation[SP 14:30-15:30]")
    assert other_agency["rating_engagement_id"] == sp_id, (
        "presentation[SP 14:30-15:30].rating_engagement_id: expected the SP "
        f"engagement {sp_id!r}, got {other_agency['rating_engagement_id']!r}"
    )
    assert other_agency["attendee_count"] == 8, (
        "presentation[SP 14:30-15:30].attendee_count: expected 8, "
        f"got {other_agency['attendee_count']!r}"
    )

    _, sp_meta = validate_paginated(
        client.list_engagement_presentations(sp_id, ctx.compliance_headers)
    )
    assert_pagination(sp_meta, total_count=1)
    # The other agency's calendar is untouched by the overlapping slot.
    _, moodys_meta = validate_paginated(
        client.list_engagement_presentations(moodys_id, ctx.compliance_headers)
    )
    assert_pagination(moodys_meta, total_count=1)


def test_attendee_count_above_the_maximum_is_refused(client, draft_deal):
    """PRD 3.5: "A presentation records the engagement it belongs to in its
    `rating_engagement_id` and supplies `starts_at` and `ends_at` as ISO 8601 UTC
    instants with three fractional digits, and an `attendee_count` of issuer and
    advisor attendees that must be at least 1 and at most 25."

    Design: Difficulty/resource_temporal_overlap/rating_presentation_closed_interval_sixty_minute_buffer
    """
    ctx = draft_deal
    _moodys_id, sp_id, _existing = _two_agency_engagements(ctx)

    # The slot itself is free for this agency, so the only defect is the count.
    overcrowded = client.create_presentation(
        sp_id,
        f.presentation_payload(
            OTHER_AGENCY_STARTS,
            OTHER_AGENCY_ENDS,
            attendee_count=ATTENDEE_COUNT_MAX + 1,
        ),
        ctx.advisor_headers,
    )
    validate_error(overcrowded, err.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        client.list_engagement_presentations(sp_id, ctx.compliance_headers)
    )
    assert_pagination(meta, total_count=0)

"""Temporal-overlap geometry: half-open line-review submission windows
(adjacency allowed, one day of overlap rejected, CANCELLED frees the window)
and closed-with-buffer slot occupancy per shelf position (exactly 14 days of
reset gap allowed, 13 rejected, strictly-inside rejected).
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_line_review,
    create_line_review_payload,
    create_partner,
    create_planogram_slot_payload,
    create_slot,
    read_line_review,
    set_clock,
    setup_open_review_with_slot,
    transition_line_review,
    validate_error,
    validate_paginated,
)

_PLANNER = TEST_USERS["retail_planner_headers"]


def test_half_open_windows_allow_adjacency_and_reject_overlap(api):
    """PRD §3.7: "The window is a half-open interval — it includes the start
    instant and excludes the end instant — and the dates must be internally
    valid: the window end must be later than the start, and the review date
    must fall on or after the window end, else creation is rejected with
    `ERR_INVALID_DATE_RANGE`." PRD §3.7: "Across one partner's
    reviews, the submission windows of all reviews not in `CANCELLED` must not
    overlap, though adjacency — one window's start equal to another's end — is
    allowed; an overlapping schedule is rejected with `ERR_WINDOW_OVERLAP`."
    [10-01, 10-15) then [10-15, 11-01) both schedule; [10-14, 10-28) overlaps
    the first by one day and is rejected.

    Design: Difficulty/resource_temporal_overlap/line_review_windows_half_open_adjacency_allowed
    """
    set_clock()
    partner = create_partner()

    w1 = create_line_review(partner["id"])
    w2 = create_line_review(
        partner["id"],
        season="2027-SP",
        submission_window_start="2026-10-15T00:00:00Z",
        submission_window_end="2026-11-01T00:00:00Z",
        review_date="2026-11-05T00:00:00Z",
    )
    assert w1["status"] == "SCHEDULED"
    assert w2["status"] == "SCHEDULED"

    response = api.create_line_review(
        create_line_review_payload(
            retail_partner_id=partner["id"],
            season="2027-SU",
            submission_window_start="2026-10-14T00:00:00Z",
            submission_window_end="2026-10-28T00:00:00Z",
            review_date="2026-10-28T00:00:00Z",
        ),
        _PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_cancelled_review_frees_its_window_for_reuse(api):
    """PRD §3.7: "Across one partner's reviews, the submission windows of all
    reviews not in `CANCELLED` must not overlap, though adjacency — one
    window's start equal to another's end — is allowed; an overlapping
    schedule is rejected with `ERR_WINDOW_OVERLAP`."
    After the [10-15, 11-01) review is cancelled, a new review reusing
    [10-15, 10-20) schedules; the partner's list then holds the live first
    review, the cancelled second, and the new fourth.

    Design: Difficulty/resource_temporal_overlap/line_review_windows_half_open_adjacency_allowed
    """
    set_clock()
    partner = create_partner()
    w1 = create_line_review(partner["id"])
    w2 = create_line_review(
        partner["id"],
        season="2027-SP",
        submission_window_start="2026-10-15T00:00:00Z",
        submission_window_end="2026-11-01T00:00:00Z",
        review_date="2026-11-05T00:00:00Z",
    )

    transition_line_review(w2["id"], "CANCELLED")
    w4 = create_line_review(
        partner["id"],
        season="2027-SP-B",
        submission_window_start="2026-10-15T00:00:00Z",
        submission_window_end="2026-10-20T00:00:00Z",
        review_date="2026-10-22T00:00:00Z",
    )
    assert w4["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_line_reviews(headers=_PLANNER, params={"retail_partner_id": partner["id"]})
    )
    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[w1["id"]]["status"] == "SCHEDULED"
    assert by_id[w2["id"]]["status"] == "CANCELLED"
    assert by_id[w4["id"]]["status"] == "SCHEDULED"


def _slot_payload(ctx, occupancy_start, occupancy_end):
    return create_planogram_slot_payload(
        line_review_id=ctx["line_review"]["id"],
        product_id=ctx["product"]["id"],
        facings=2,
        occupancy_start=occupancy_start,
        occupancy_end=occupancy_end,
        expected_line_review_version=read_line_review(ctx["line_review"]["id"])["version"],
    )


def test_occupancy_allows_exactly_14_day_gap_and_rejects_13(api):
    """PRD §3.7: "Two slots colliding on the same position are detected per
    partner, category, and `position_code`: among slots in `PROPOSED`,
    `COMMITTED`, or `ACTIVE`, a new occupancy must begin strictly more than
    fourteen days after the existing occupancy's end, or end strictly more
    than fourteen days before the existing occupancy's start; a reset gap of
    exactly fourteen days is allowed. A collision is rejected with
    `ERR_OCCUPANCY_CONFLICT`."
    Position EYES-A1 holds [2026-11-01, 2027-01-31]: 2027-02-14 (gap exactly
    14 days) schedules; 2027-02-13 (gap 13) collides.

    Design: Difficulty/resource_temporal_overlap/slot_occupancy_closed_interval_requires_14day_buffer
    """
    ctx = setup_open_review_with_slot()

    ok = create_slot(
        ctx["line_review"]["id"],
        ctx["product"]["id"],
        facings=2,
        occupancy_start="2027-02-14T00:00:00Z",
        occupancy_end="2027-03-31T00:00:00Z",
    )
    assert ok["status"] == "PROPOSED"

    response = api.create_planogram_slot(
        _slot_payload(ctx, "2027-02-13T00:00:00Z", "2027-03-31T00:00:00Z"), _PLANNER
    )

    validate_error(response, ApiErrorId.ERR_OCCUPANCY_CONFLICT.value)


def test_occupancy_strictly_inside_conflicts_and_failed_creates_do_not_bump_version(api):
    """PRD §3.7: "The occupancy interval is closed — it includes both its
    start and its end — and the end must not precede the start, else
    `ERR_INVALID_DATE_RANGE`." PRD §3.7: "Two slots colliding on the same
    position are detected per partner, category, and `position_code`: among
    slots in `PROPOSED`, `COMMITTED`, or `ACTIVE`, a new occupancy must begin
    strictly more than fourteen days after the existing occupancy's end, or
    end strictly more than fourteen days before the existing occupancy's
    start; a reset gap of exactly fourteen days is allowed. A collision is
    rejected with `ERR_OCCUPANCY_CONFLICT`."
    An interval strictly inside the existing [2026-11-01, 2027-01-31]
    collides; both rejections leave the review's version untouched (the same
    expected version is accepted for the second attempt) and the review holds
    exactly its two successful slots.

    Design: Difficulty/resource_temporal_overlap/slot_occupancy_closed_interval_requires_14day_buffer
    """
    ctx = setup_open_review_with_slot()
    create_slot(
        ctx["line_review"]["id"],
        ctx["product"]["id"],
        facings=2,
        occupancy_start="2027-02-14T00:00:00Z",
        occupancy_end="2027-03-31T00:00:00Z",
    )
    version_after_success = read_line_review(ctx["line_review"]["id"])["version"]

    validate_error(
        api.create_planogram_slot(
            create_planogram_slot_payload(
                line_review_id=ctx["line_review"]["id"],
                product_id=ctx["product"]["id"],
                facings=2,
                occupancy_start="2027-02-13T00:00:00Z",
                occupancy_end="2027-03-31T00:00:00Z",
                expected_line_review_version=version_after_success,
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_OCCUPANCY_CONFLICT.value,
    )
    validate_error(
        api.create_planogram_slot(
            create_planogram_slot_payload(
                line_review_id=ctx["line_review"]["id"],
                product_id=ctx["product"]["id"],
                facings=2,
                occupancy_start="2026-12-01T00:00:00Z",
                occupancy_end="2026-12-15T00:00:00Z",
                expected_line_review_version=version_after_success,
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_OCCUPANCY_CONFLICT.value,
    )

    assert read_line_review(ctx["line_review"]["id"])["version"] == version_after_success
    rows, meta = validate_paginated(
        api.list_planogram_slots(
            headers=_PLANNER, params={"line_review_id": ctx["line_review"]["id"]}
        )
    )
    assert meta["total_count"] == 2

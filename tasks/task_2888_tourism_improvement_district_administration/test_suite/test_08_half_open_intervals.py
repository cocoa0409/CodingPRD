"""Intervals that touch, intervals that overlap, and the scope each is checked in.

Two collections in this system reserve a stretch of time: a room-night claim
reserves a stay against one program-and-property pair, and an assessment period
reserves an occupancy window against one district.  Both are half-open, so an
interval that begins exactly where another ends is admitted while any genuine
overlap is refused.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CLAIM_STAY_OVERLAP, ERR_PERIOD_OVERLAP
from test_helpers.assertions import assert_fields, assert_ordered_by
from test_helpers.test_users import ADMIN, DMO_LIAISON


# --------------------------------------------------------------------------
# Claim stays, scoped to one program and one property
# --------------------------------------------------------------------------
def _running_program_with_two_adjacent_claims(api):
    """Claim two back-to-back weeks for the core full-service property, the second
    starting exactly where the first ends."""
    ctx = fx.running_program(api)
    fx.set_clock(api, "2026-09-25T00:00:00Z")
    fx.submit_claim(
        api,
        ctx,
        business_key="b1_id",
        key="rnc_week1",
        stay_start="2026-09-01T00:00:00Z",
        stay_end="2026-09-08T00:00:00Z",
        room_nights=7,
    )
    fx.submit_claim(
        api,
        ctx,
        business_key="b1_id",
        key="rnc_week2",
        stay_start="2026-09-08T00:00:00Z",
        stay_end="2026-09-15T00:00:00Z",
        room_nights=7,
    )
    return ctx


def _claim_payload(business_id, start, end, nights):
    return f.room_night_claim_payload(
        business_id, stay_start=start, stay_end=end, room_nights=nights
    )


def test_a_stay_beginning_where_another_ends_is_accepted(api):
    """Two adjacent weeks for the same property on the same program are both
    admitted, because the intervals are half-open and merely touch.

    PRD 3.8: "Stay intervals of the same program-and-property pair, treated as
    half-open, must not overlap. An interval starting exactly where another ends is
    accepted."

    Design: Difficulty/resource_temporal_overlap/room_night_claim_stays_are_half_open_per_program_and_property
    """
    ctx = _running_program_with_two_adjacent_claims(api)

    for key in ("rnc_week1", "rnc_week2"):
        claim = validate_success(api.get_room_night_claim(ctx[key], headers=ADMIN))
        assert_fields(claim, status="SUBMITTED", room_nights=7, rejection_reason="NONE")


def test_a_stay_genuinely_overlapping_another_is_refused(api):
    """A stay starting inside the second week overlaps it and is refused, while a
    stay over the same nights for a different property is accepted, which shows the
    rule is scoped to the program-and-property pair.

    PRD 3.8: "Stay intervals of the same program-and-property pair, treated as
    half-open, must not overlap."  "An overlap is refused with
    ERR_CLAIM_STAY_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/room_night_claim_stays_are_half_open_per_program_and_property
    """
    ctx = _running_program_with_two_adjacent_claims(api)

    response = api.create_room_night_claim(
        ctx.mp_id,
        _claim_payload(ctx.b1_id, "2026-09-14T00:00:00Z", "2026-09-20T00:00:00Z", 6),
        headers=DMO_LIAISON,
    )
    validate_error(response, ERR_CLAIM_STAY_OVERLAP, expected_status=409)

    other = validate_success(
        api.create_room_night_claim(
            ctx.mp_id,
            _claim_payload(ctx.b2_id, "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z", 7),
            headers=DMO_LIAISON,
        ),
        expected_status=201,
    )
    assert_fields(other, status="SUBMITTED", lodging_business_id=ctx.b2_id)


def test_a_rejected_claim_frees_its_nights_for_a_fresh_claim(api):
    """A third week is claimed and then rejected, after which an identical claim
    over the very same nights is admitted, because only SUBMITTED and VERIFIED
    claims occupy an interval.

    PRD 3.8: "Only claims whose status is SUBMITTED or VERIFIED occupy an
    interval; a REJECTED claim frees it for a new claim over the same nights."

    Design: Difficulty/resource_temporal_overlap/room_night_claim_stays_are_half_open_per_program_and_property
    """
    ctx = _running_program_with_two_adjacent_claims(api)
    validate_error(
        api.create_room_night_claim(
            ctx.mp_id,
            _claim_payload(ctx.b1_id, "2026-09-14T00:00:00Z", "2026-09-20T00:00:00Z", 6),
            headers=DMO_LIAISON,
        ),
        ERR_CLAIM_STAY_OVERLAP,
        expected_status=409,
    )
    validate_success(
        api.create_room_night_claim(
            ctx.mp_id,
            _claim_payload(ctx.b2_id, "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z", 7),
            headers=DMO_LIAISON,
        ),
        expected_status=201,
    )

    fx.submit_claim(
        api,
        ctx,
        business_key="b1_id",
        key="rnc_week3",
        stay_start="2026-09-20T00:00:00Z",
        stay_end="2026-09-27T00:00:00Z",
        room_nights=7,
    )
    fx.verify_claim(
        api, ctx, claim_key="rnc_week3", decision="REJECT", rejection_reason="DUPLICATE_STAY"
    )

    replacement = validate_success(
        api.create_room_night_claim(
            ctx.mp_id,
            _claim_payload(ctx.b1_id, "2026-09-20T00:00:00Z", "2026-09-27T00:00:00Z", 7),
            headers=DMO_LIAISON,
        ),
        expected_status=201,
    )
    assert_fields(replacement, status="SUBMITTED", lodging_business_id=ctx.b1_id)

    rows, meta = validate_paginated(api.list_program_room_night_claims(ctx.mp_id, headers=ADMIN))
    assert meta["total_count"] == 5, f"expected the five stored claims: {meta}"
    submitted, submitted_meta = validate_paginated(
        api.list_program_room_night_claims(
            ctx.mp_id, headers=ADMIN, params={"status": "SUBMITTED"}
        )
    )
    assert submitted_meta["total_count"] == 4, (
        f"expected four claims still occupying an interval: {submitted_meta}"
    )


# --------------------------------------------------------------------------
# Assessment period windows, scoped to one district
# --------------------------------------------------------------------------
Q2 = dict(
    period_label="FY2027-Q2",
    period_start="2026-11-01T00:00:00Z",
    period_end="2027-02-01T00:00:00Z",
    due_date="2027-02-15T00:00:00Z",
)
OVERLAPPING = dict(
    period_label="FY2027-XX",
    period_start="2026-10-15T00:00:00Z",
    period_end="2026-12-15T00:00:00Z",
    due_date="2026-12-31T00:00:00Z",
)
Q3 = dict(
    period_label="FY2027-Q3",
    period_start="2027-02-01T00:00:00Z",
    period_end="2027-05-01T00:00:00Z",
    due_date="2027-05-15T00:00:00Z",
)


def _district_with_the_first_quarter_open(api):
    """An ACTIVE district holding one period over [2026-08-01, 2026-11-01)."""
    ctx = fx.active_district(api)
    fx.open_period(api, ctx)
    return ctx


def test_a_period_starting_on_another_period_end_is_accepted(api):
    """The second quarter begins exactly where the first ends, which the half-open
    treatment admits.

    PRD 3.3: "Periods of one district are treated as half-open intervals and may
    not overlap; a new period starting exactly on an existing period's period_end
    is accepted, while any genuine overlap is refused with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/assessment_period_windows_are_half_open_within_one_district
    """
    ctx = _district_with_the_first_quarter_open(api)

    period = validate_success(
        api.create_assessment_period(f.assessment_period_payload(ctx.d_id, **Q2), headers=ADMIN),
        expected_status=201,
    )
    assert_fields(
        period,
        status="OPEN",
        period_label="FY2027-Q2",
        statement_count=0,
        billed_total_cents=0,
        collected_total_cents=0,
    )


def test_a_period_genuinely_overlapping_two_others_is_refused(api):
    """A window running from mid-October to mid-December straddles the boundary
    between the two quarters and is refused.

    PRD 3.3: "any genuine overlap is refused with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/assessment_period_windows_are_half_open_within_one_district
    """
    ctx = _district_with_the_first_quarter_open(api)
    validate_success(
        api.create_assessment_period(f.assessment_period_payload(ctx.d_id, **Q2), headers=ADMIN),
        expected_status=201,
    )

    response = api.create_assessment_period(
        f.assessment_period_payload(ctx.d_id, **OVERLAPPING), headers=ADMIN
    )
    validate_error(response, ERR_PERIOD_OVERLAP, expected_status=409)

    rows, meta = validate_paginated(api.list_district_assessment_periods(ctx.d_id, headers=ADMIN))
    assert meta["total_count"] == 2, f"expected the refused period not to be stored: {meta}"


def test_a_third_touching_period_is_accepted_and_the_list_is_period_start_ordered(api):
    """A third quarter beginning on the second's period_end is admitted, leaving
    three periods listed in period_start ascending order.

    PRD 4: "GET /districts/{id}/assessment-periods — Assessment periods of the
    district in period_start ascending order."

    Design: Difficulty/resource_temporal_overlap/assessment_period_windows_are_half_open_within_one_district
    """
    ctx = _district_with_the_first_quarter_open(api)
    validate_success(
        api.create_assessment_period(f.assessment_period_payload(ctx.d_id, **Q2), headers=ADMIN),
        expected_status=201,
    )
    validate_error(
        api.create_assessment_period(
            f.assessment_period_payload(ctx.d_id, **OVERLAPPING), headers=ADMIN
        ),
        ERR_PERIOD_OVERLAP,
        expected_status=409,
    )
    validate_success(
        api.create_assessment_period(f.assessment_period_payload(ctx.d_id, **Q3), headers=ADMIN),
        expected_status=201,
    )

    rows, meta = validate_paginated(api.list_district_assessment_periods(ctx.d_id, headers=ADMIN))
    assert meta["total_count"] == 3, f"expected exactly three periods: {meta}"
    assert [row["period_label"] for row in rows] == [
        "FY2027-Q1",
        "FY2027-Q2",
        "FY2027-Q3",
    ], f"unexpected period order: {[row['period_label'] for row in rows]}"
    assert_ordered_by(rows, "period_start")

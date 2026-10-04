"""Boundary precision at the programme's numeric and temporal thresholds."""
from test_helpers import (
    COMPLIANCE,
    FLEET,
    agreement_version,
    api_client,
    create_enrollment_payload,
    enroll_driver,
    get_agreement,
    get_success_data,
    open_week,
    platform_credit_for,
    register_driver,
    set_clock,
    setup_active_agreement,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_activity_floor_is_inclusive_at_fifty(api):
    """PRD §3.1: "a driver whose platform activity score sits below the
    programme's activity floor of 50 points is refused with
    ERR_PLATFORM_ACTIVITY_INSUFFICIENT (HTTP 422)."
    PRD §3.2: "A driver whose activity score is below the programme floor of 50
    points earns nothing at all. A driver at 50 points through 74 points earns 10
    cents for each point from 50 up to and including their score - so the band
    credits a point sitting exactly at 50, and a score of 60 yields 110 cents."

    Design: Difficulty/boundary_precision_check/activity_band_boundary_at_fifty_and_seventy_five
    """
    below = register_driver(platform_activity_score=49, driving_record_points=2)
    at_floor = register_driver(platform_activity_score=50, driving_record_points=2)

    refused = api_client.enroll_driver(create_enrollment_payload(below["id"]), COMPLIANCE)
    validate_error(refused, ApiErrorId.ERR_PLATFORM_ACTIVITY_INSUFFICIENT, 422)

    accepted = enroll_driver(at_floor["id"])
    assert accepted["activity_snapshot"] == 50
    assert accepted["eligibility_score"] == 90


def test_credit_band_pays_zero_at_forty_nine_and_ten_cents_at_fifty(api):
    """PRD §3.2: "A driver whose activity score is below the programme floor of 50
    points earns nothing at all. A driver at 50 points through 74 points earns 10
    cents for each point from 50 up to and including their score - so the band
    credits a point sitting exactly at 50, and a score of 60 yields 110 cents."

    Design: Difficulty/boundary_precision_check/activity_band_boundary_at_fifty_and_seventy_five
    """
    assert platform_credit_for(49) == 0, "below the floor nothing is earned"
    assert platform_credit_for(50) == 10, "the band is inclusive at 50"
    assert platform_credit_for(60) == 110
    assert platform_credit_for(74) == 250

    ctx = setup_active_agreement(activity_score=50, unlimited=True)
    week = open_week(ctx.agreement["id"])
    settled = get_success_data(api_client.settle_week(week["id"], COMPLIANCE))
    assert settled["platform_credit_cents"] == 10
    assert settled["amount_due_cents"] == 35_000 + 4_000 - 10


def test_escalated_band_starts_at_seventy_five(api):
    """PRD §3.2: "A driver at 75 points or above earns the full 50-to-74 band,
    which is 25 qualifying points at 10 cents each for 250 cents, plus 10 cents
    multiplied by three halves for each point from 75 up to and including their
    score, with the multiplication floored to a whole number of cents as it is
    applied. A score of exactly 75 therefore adds one point's worth of the
    escalated band for 15 cents, bringing the running total to 265 cents, and a
    score of 100 adds the full 26-point escalated band for 390 cents, bringing
    the raw total to 640 cents."

    Design: Difficulty/boundary_precision_check/activity_band_boundary_at_fifty_and_seventy_five
    """
    assert platform_credit_for(74) == 250, "the flat band ends at 250 cents"
    assert platform_credit_for(75) == 265, "one escalated point at three halves"
    assert platform_credit_for(100) == 600, "640 raw cents is trimmed to the 600-cent cap"

    ctx = setup_active_agreement(activity_score=75, unlimited=True)
    week = open_week(ctx.agreement["id"])
    settled = get_success_data(api_client.settle_week(week["id"], COMPLIANCE))
    assert settled["platform_credit_cents"] == 265


def test_weekly_period_ending_exactly_on_the_agreement_term_is_accepted(api):
    """PRD §3.4: "the seven-day period that would be opened, running from the
    logical clock instant, must not extend past the agreement's period_end, or the
    request is rejected with ERR_WEEK_OUTSIDE_AGREEMENT_TERM (HTTP 422)."

    Design: Difficulty/boundary_precision_check/agreement_term_boundary_on_week_opening
    """
    ctx = setup_active_agreement(
        unlimited=True, period_start="2026-09-01T00:00:00Z",
        period_end="2027-08-31T00:00:00Z",
    )
    set_clock("2027-08-24T00:00:00Z")

    last = open_week(ctx.agreement["id"])
    assert last["period_start"] == "2027-08-24T00:00:00Z"
    assert last["period_end"] == "2027-08-31T00:00:00Z", (
        "the period ends exactly on the agreement's contractual term"
    )
    assert get_agreement(ctx.agreement["id"])["current_week_number"] == 1


def test_one_day_past_the_term_is_refused(api):
    """PRD §3.4: "the seven-day period that would be opened, running from the
    logical clock instant, must not extend past the agreement's period_end, or the
    request is rejected with ERR_WEEK_OUTSIDE_AGREEMENT_TERM (HTTP 422)."

    Design: Difficulty/boundary_precision_check/agreement_term_boundary_on_week_opening
    """
    ctx = setup_active_agreement(
        unlimited=True, period_start="2026-09-01T00:00:00Z",
        period_end="2027-08-31T00:00:00Z",
    )
    set_clock("2027-08-25T00:00:00Z")

    response = api_client.open_week(
        {
            "agreement_id": ctx.agreement["id"],
            "expected_agreement_version": agreement_version(ctx.agreement["id"]),
        },
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_WEEK_OUTSIDE_AGREEMENT_TERM, 422)
    assert get_agreement(ctx.agreement["id"])["current_week_number"] == 0, (
        "the refused request leaves the counter untouched"
    )


def test_the_term_edge_is_measured_against_the_agreement_not_the_week_row(api):
    """PRD §3.4: "An agreement's contractual bounds are its agreed period_start
    and period_end, and the interval they describe is the occupancy interval
    reserved on the unit."
    PRD §3.4: "Its start instant is the logical clock instant and its end instant
    is exactly seven days later."

    Design: Difficulty/boundary_precision_check/agreement_term_boundary_on_week_opening
    """
    ctx = setup_active_agreement(
        unlimited=True, period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
    )
    first = open_week(ctx.agreement["id"])
    assert first["period_end"] == "2026-09-08T00:00:00Z"

    second = open_week(ctx.agreement["id"])
    assert second["period_start"] == "2026-09-01T00:00:00Z"
    assert second["period_end"] == "2026-09-08T00:00:00Z"

    set_clock("2026-09-08T00:00:00Z")
    third = open_week(ctx.agreement["id"])
    assert third["period_end"] == "2026-09-15T00:00:00Z", (
        "a period ending exactly on period_end is still inside the term"
    )
    assert get_agreement(ctx.agreement["id"])["current_week_number"] == 3
"""Derived figures and read-only views of the Preschool Child Find API.

Covers the referral compliance view's two deadline anchors and its AT_RISK boundary,
the floor-bounded effective capacity of a screening event, the anniversary convention
behind a child's third birthday and kindergarten eligibility date, and the ordering of
the child's derived status ladder.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.assertions import assert_date_equals, assert_version_unchanged  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    AT_RISK_DAYS,
    EVAL_WINDOW_DAYS,
    anniversary,
    expected_kindergarten_eligibility_date,
    plus_days_date,
    ts,
)
from test_helpers.test_users import TEST_USERS  # noqa: E402

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]

# The date the logical clock reads before any test moves it.
CLOCK_DATE = "2026-08-01"

# A birth date whose third birthday falls on the very day the referral is received,
# so the third-birthday cap sits far earlier than the 60-day deadline.
CHILD_DOB_36_MONTHS = "2023-08-01"

# The 60-day deadline both anchors land on for a referral received and consented to
# on the initial clock date.
DUE_DATE = plus_days_date(CLOCK_DATE, EVAL_WINDOW_DAYS)


def _authorized_referral_with_case(api):
    """A referral at EVALUATION_AUTHORIZED whose evaluation case is still in flight."""
    child = fx.register_child(api, date_of_birth=CHILD_DOB_36_MONTHS)
    return fx.setup_case(api, child["id"])


# ------------------------------------------- the referral compliance view (§3.3)
def test_referral_timeline_reports_both_anchors_and_the_uncapped_pinned_date(api):
    """Both readings and the cap sit side by side, and the pinned date is uncapped.

    PRD §3.3: "The pinned rule — the consent-anchored reading — takes the calendar date
    of `consent_granted_at` and adds 60 calendar days, weekends and holidays included."
    PRD §3.3: "For a referral on the `STANDARD_60_DAY` pathway the consent-anchored
    date stands uncapped."
    PRD §3.3: "Alongside it the system can compute, but never persists on the referral,
    the receipt-anchored reading: the calendar date of `received_at` plus the same 60
    calendar days, with **no** third-birthday cap."
    PRD §3.3: "Both readings are laid out side by side on the referral's compliance
    view, a read-only endpoint that returns `referral_id`, the referral's
    `eligibility_pathway`, its `received_date` and `consent_granted_date` as plain
    calendar dates, the `receipt_anchored_due_date` and `consent_anchored_due_date` as
    computed above, the `third_birthday_cap_date` that the Part C pathway would apply,
    the pinned `evaluation_due_date` actually in force, the `days_remaining` until it,
    and the `timeline_compliance` posture of §3.5."

    Design: Corner/calculations/referral_timeline_reports_both_anchors_and_crosses_the_at_risk_boundary
    """
    context = _authorized_referral_with_case(api)
    referral = context["referral"]

    timeline = fx.read_timeline(api, referral["id"])

    assert timeline["referral_id"] == referral["id"]
    assert timeline["eligibility_pathway"] == "STANDARD_60_DAY"
    assert_date_equals(timeline["received_date"], CLOCK_DATE, "received_date")
    assert_date_equals(timeline["consent_granted_date"], CLOCK_DATE, "consent_granted_date")
    assert_date_equals(
        timeline["receipt_anchored_due_date"], DUE_DATE, "receipt_anchored_due_date"
    )
    assert_date_equals(
        timeline["consent_anchored_due_date"], DUE_DATE, "consent_anchored_due_date"
    )
    assert_date_equals(
        timeline["third_birthday_cap_date"],
        anniversary(CHILD_DOB_36_MONTHS, 3),
        "third_birthday_cap_date",
    )
    assert_date_equals(timeline["evaluation_due_date"], DUE_DATE, "evaluation_due_date")
    assert timeline["days_remaining"] == EVAL_WINDOW_DAYS
    assert timeline["timeline_compliance"] == "ON_TIME"

    assert_date_equals(
        fx.read_referral(api, referral["id"])["evaluation_due_date"],
        DUE_DATE,
        "referral.evaluation_due_date",
    )


def test_referral_timeline_crosses_the_at_risk_boundary_as_the_clock_moves(api):
    """Eleven days remaining still reads ON_TIME; ten reads AT_RISK; past due, OVERDUE.

    PRD §3.5: "For a case still in flight — that is, in any of the five non-terminal
    statuses — the system takes the whole number of calendar days from the logical
    clock's current date to `due_date`: a negative number means the deadline has passed
    and the posture is `OVERDUE`; a number of 10 or fewer means `AT_RISK`; anything
    larger means `ON_TIME`."
    PRD §3.5: "Ten days remaining is therefore `AT_RISK` while eleven is `ON_TIME`, and
    a case due today, with zero days remaining, is `AT_RISK`, while one day past due is
    `OVERDUE`."
    PRD §3.5: "Because the posture reads the logical clock, moving the clock re-derives
    it for every case on the next read."

    Design: Corner/calculations/referral_timeline_reports_both_anchors_and_crosses_the_at_risk_boundary
    """
    context = _authorized_referral_with_case(api)
    referral_id = context["referral"]["id"]

    fx.set_clock(api, ts(plus_days_date(DUE_DATE, -(AT_RISK_DAYS + 1)) + "T00:00:00Z"))
    on_time = fx.read_timeline(api, referral_id)
    assert on_time["days_remaining"] == AT_RISK_DAYS + 1
    assert on_time["timeline_compliance"] == "ON_TIME"

    fx.set_clock(api, ts(plus_days_date(DUE_DATE, -AT_RISK_DAYS) + "T00:00:00Z"))
    at_risk = fx.read_timeline(api, referral_id)
    assert at_risk["days_remaining"] == AT_RISK_DAYS
    assert at_risk["timeline_compliance"] == "AT_RISK"

    fx.set_clock(api, ts(plus_days_date(DUE_DATE, 1) + "T00:00:00Z"))
    overdue = fx.read_timeline(api, referral_id)
    assert overdue["days_remaining"] == -1
    assert overdue["timeline_compliance"] == "OVERDUE"

    assert_date_equals(overdue["evaluation_due_date"], DUE_DATE, "evaluation_due_date")


# --------------------------------------------- effective screening capacity (§3.2)
def test_effective_slot_capacity_is_the_floor_bounded_minimum(api):
    """The window truncates the declaration, and the declaration caps the window.

    PRD §3.2: "On creation the system computes `effective_slot_capacity` as the lesser
    of the declared `slot_capacity` and the number of whole appointments the window can
    physically hold — that is, the whole number of minutes between `window_start_utc`
    and `window_end_utc` divided by `slot_length_minutes` and truncated downward, never
    rounded up."

    Design: Corner/calculations/effective_slot_capacity_is_the_floor_bounded_minimum
    """
    site = fx.register_site(api)

    window_bound = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
        slot_capacity=10,
        slot_length_minutes=60,
    )
    assert window_bound["slot_capacity"] == 10
    assert window_bound["effective_slot_capacity"] == 3
    assert window_bound["booked_slot_count"] == 0

    declaration_bound = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-21T09:00:00Z"),
        window_end_utc=ts("2026-08-21T12:00:00Z"),
        slot_capacity=2,
        slot_length_minutes=30,
    )
    assert declaration_bound["slot_capacity"] == 2
    assert declaration_bound["effective_slot_capacity"] == 2

    ragged_window = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-22T09:00:00Z"),
        window_end_utc=ts("2026-08-22T11:50:00Z"),
        slot_capacity=10,
        slot_length_minutes=60,
    )
    assert ragged_window["slot_capacity"] == 10
    assert ragged_window["effective_slot_capacity"] == 2


# ------------------------------------------------ anniversary conventions (§2.8)
def test_leap_day_birthdays_map_to_march_first_for_both_derived_dates(api):
    """A February 29 birth date lands on March 1 three years on, and on the cutoff.

    PRD §2.8: "Adding a whole number of years to a date lands on the same month and day
    of the later year, except that a February 29 birth date maps to March 1."
    PRD §3.1: "`third_birthday` is the child's date of birth advanced by three years
    under the anniversary convention of §2.8, and it is the anchor of the Part B
    deadline cap."
    PRD §3.1: "`kindergarten_eligibility_date` is computed by first advancing the date
    of birth by five years to obtain the fifth birthday, then taking September 1 of the
    year in which that fifth birthday falls: if the fifth birthday is on or before that
    September 1, the eligibility date is that same September 1; otherwise it is
    September 1 of the following year."

    Design: Corner/calculations/leap_day_birthdays_map_to_march_first_for_both_derived_dates
    """
    child = fx.register_child(api, date_of_birth="2024-02-29")

    assert_date_equals(child["third_birthday"], "2027-03-01", "third_birthday")
    assert_date_equals(
        child["third_birthday"], anniversary("2024-02-29", 3), "third_birthday"
    )
    assert_date_equals(
        child["kindergarten_eligibility_date"], "2029-09-01", "kindergarten_eligibility_date"
    )
    assert_date_equals(
        child["kindergarten_eligibility_date"],
        expected_kindergarten_eligibility_date("2024-02-29"),
        "kindergarten_eligibility_date",
    )


@pytest.mark.parametrize(
    "date_of_birth,expected_third_birthday,expected_eligibility_date",
    [
        ("2023-09-01", "2026-09-01", "2028-09-01"),
        ("2023-09-02", "2026-09-02", "2029-09-01"),
    ],
)
def test_the_kindergarten_cutoff_includes_a_fifth_birthday_of_september_first(
    api, date_of_birth, expected_third_birthday, expected_eligibility_date
):
    """September 1 keeps the same school year; September 2 pushes to the next one.

    PRD §3.1: "A fifth birthday landing exactly on September 1 therefore uses that same
    September 1, while September 2 pushes the child to the next school year."
    PRD §3.1: "`third_birthday` is the child's date of birth advanced by three years
    under the anniversary convention of §2.8, and it is the anchor of the Part B
    deadline cap."

    Design: Corner/calculations/leap_day_birthdays_map_to_march_first_for_both_derived_dates
    """
    child = fx.register_child(api, date_of_birth=date_of_birth)

    assert_date_equals(child["third_birthday"], expected_third_birthday, "third_birthday")
    assert_date_equals(
        child["kindergarten_eligibility_date"],
        expected_eligibility_date,
        "kindergarten_eligibility_date",
    )
    assert_date_equals(
        child["kindergarten_eligibility_date"],
        expected_kindergarten_eligibility_date(date_of_birth),
        "kindergarten_eligibility_date",
    )


# ------------------------------------------------ the derived status ladder (§3.9)
def test_child_status_ladder_prefers_the_active_plan_over_a_fresh_referral(api):
    """A served child stays SERVED when a brand-new referral arrives for them.

    PRD §3.9: "Otherwise, if the child has any plan at `ACTIVE`, the status is
    `SERVED`."
    PRD §3.9: "The ladder is ordered by finality of outcome rather than by recency, so a
    child holding both an `ACTIVE` plan and a freshly `RECEIVED` referral reads
    `SERVED`, not `REFERRED`."
    PRD §3.3: "every earlier referral of that same child whose `intake_status` is
    `RECEIVED`, `CONSENT_PENDING` or `EVALUATION_AUTHORIZED` is moved to `SUPERSEDED`,
    with `superseded_by_referral_id` set to the new referral's identifier and its
    `version` incremented."
    PRD §3.3: "Displacing one from `EVALUATION_AUTHORIZED` additionally cancels that
    referral's evaluation case, provided that case has not already reached
    `ELIGIBILITY_DETERMINED` or `CANCELLED`, which in turn triggers the assessment and
    provider-rollup chain described in §3.5."

    Design: Corner/calculations/child_status_ladder_prefers_the_active_plan_over_a_fresh_referral
    """
    site = fx.register_site(api)
    context = fx.setup_active_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
    )
    child_id = context["child"]["id"]
    plan = context["plan"]
    first_referral = context["referral"]
    case = context["case"]

    assert plan["status"] == "ACTIVE"
    assert fx.read_child(api, child_id)["status"] == "SERVED"

    fresh_referral = fx.create_referral(api, child_id, source="SCHOOL")
    assert fresh_referral["intake_status"] == "RECEIVED"
    assert fresh_referral["consent_status"] == "NOT_REQUESTED"

    displaced = fx.read_referral(api, first_referral["id"])
    assert displaced["intake_status"] == "SUPERSEDED"
    assert displaced["superseded_by_referral_id"] == fresh_referral["id"]

    assert fx.read_case(api, case["id"])["status"] == "ELIGIBILITY_DETERMINED"

    settled_plan = fx.read_plan(api, plan["id"])
    assert settled_plan["status"] == "ACTIVE"
    assert_version_unchanged(plan, settled_plan)

    assert fx.read_child(api, child_id)["status"] == "SERVED"

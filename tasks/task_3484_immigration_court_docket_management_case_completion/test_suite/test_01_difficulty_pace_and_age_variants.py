"""Difficulty probes: dual-variant calculations on the docket.

Court completion pace is measured two ways (calendar-day and hearing-day
pro-rata), and case age is measured two ways (calendar days and court days).
Each pair shares inputs but diverges across weekends or denominators, and the
PRD pins which variant is official.
"""

from test_helpers import (
    assert_docket_review,
    create_case,
    create_court,
    read_case,
    run_docket_review,
    same_instant,
    set_clock,
    setup_completed_case,
)

# Pace ratios are reported to exactly 4 decimal places round-half-up, so the
# frozen snapshot value must equal the derived 4-decimal value outright; the
# tolerance only absorbs JSON float rendering noise (a different 4-decimal
# answer sits 1e-4 away, far outside it).
PACE_TOLERANCE = 1e-9


def test_court_pace_calendar_variant_official_and_snapshot_fields():
    """PRD §3.8: "The official pace test reads only the calendar variant: `is_on_pace` is true exactly when `pace_ratio_calendar` is at least 1.0."
    PRD §3.8: "The two variants genuinely differ: a court with an `annual_completion_goal` of 100 and a single completion, checkpointed on 2026-10-05 — 277 elapsed calendar days, 197 elapsed hearing days — shows 0.0132 under both variants, while the same court checkpointed on 2026-09-10 — 252 elapsed calendar days, 180 elapsed hearing days — splits to 0.0145 on the calendar variant against 0.0144 on the hearing-day variant."
    PRD §3.8: "Each run freezes an immutable `DocketReview` snapshot carrying the `court_id` under review, a per-court `run_index` that starts at 1 on the court's first run and increments by 1 with every subsequent run for that court, and `computed_at` set to the clock at run time."

    Design: Difficulty/dual_variant_calc/court_pace_calendar_vs_hearing_day_variants
    """
    # Court goal 100 (factory default); exactly one case completed by appeal
    # affirmation at 2026-09-04T12:00Z, so completions_ytd is 1 and nothing is
    # pending when the checkpoint runs at 2026-09-10.
    ctx = setup_completed_case()
    set_clock("2026-09-10T00:00:00Z")
    review = run_docket_review(ctx["court"]["id"])
    assert_docket_review(review)
    assert review["run_index"] == 1, "first checkpoint for the court must carry run_index 1"
    assert review["completions_ytd"] == 1
    assert review["pending_case_count"] == 0
    # 1 / (100 * 252 / 365) = 0.014484... -> 0.0145 round-half-up at 4 places.
    assert abs(review["pace_ratio_calendar"] - 0.0145) < PACE_TOLERANCE, (
        "calendar-variant pace must be 0.0145, got {0}".format(review["pace_ratio_calendar"])
    )
    assert review["is_on_pace"] is False, "0.0145 < 1.0, so the court is not on pace"
    assert review["is_backlog_critical"] is False
    # The one completion came from an appeal affirmation, not from the lapse
    # sweep, so this run finalized nothing.
    assert review["cases_finalized_by_lapse"] == 0


def test_court_pace_hearing_day_variant_reported_alongside():
    """PRD §3.8: "The reporting variant, `pace_ratio_hearing_day`, pro-rates over hearing days instead: the elapsed count is the number of Monday-through-Friday dates strictly after January 1 and up to and including the clock date, likewise never below 1, and the expectation divides by 260 hearing days per year instead of 365."
    PRD §3.8: "while the same court checkpointed on 2026-09-10 — 252 elapsed calendar days, 180 elapsed hearing days — splits to 0.0145 on the calendar variant against 0.0144 on the hearing-day variant."

    Design: Difficulty/dual_variant_calc/court_pace_calendar_vs_hearing_day_variants
    """
    ctx = setup_completed_case()
    set_clock("2026-09-10T00:00:00Z")
    review = run_docket_review(ctx["court"]["id"])
    assert_docket_review(review)
    # 1 / (100 * 180 / 260) = 0.014444... -> 0.0144 round-half-up at 4 places.
    assert abs(review["pace_ratio_hearing_day"] - 0.0144) < PACE_TOLERANCE, (
        "hearing-day-variant pace must be 0.0144, got {0}".format(review["pace_ratio_hearing_day"])
    )
    assert abs(review["pace_ratio_calendar"] - 0.0145) < PACE_TOLERANCE
    # Identical inputs (goal 100, one completion, same clock) yield two
    # different ratios under the two pro-rata algorithms.
    assert review["pace_ratio_calendar"] != review["pace_ratio_hearing_day"]
    assert review["is_on_pace"] is False


def test_case_age_calendar_variant_drives_past_goal_and_target():
    """PRD §3.2: "The two diverge across any span containing a weekend — a case filed on Tuesday 2026-09-01 and read on Friday 2026-09-11 shows a calendar age of 10 but a court-day age of 8."
    PRD §3.2: "The calendar variant alone drives the case's past-goal posture: `is_past_goal` is true only when `days_pending_calendar` strictly exceeds the custody-specific target."
    PRD §3.2: "Custody status fixes the case's completion horizon: `target_completion_date` is `filed_at` plus 60 days for a `DETAINED` case and plus 365 days for a `NON_DETAINED` case."

    Design: Difficulty/dual_variant_calc/case_age_calendar_vs_court_days_variants
    """
    court = create_court()
    case = create_case(court["id"], custody_status="NON_DETAINED")
    set_clock("2026-09-11T00:00:00Z")
    case = read_case(case["id"])
    assert same_instant(case["filed_at"], "2026-09-01T00:00:00Z")
    assert case["days_pending_calendar"] == 10
    # 10 calendar days is strictly below the 365-day non-detained target.
    assert case["is_past_goal"] is False
    assert same_instant(case["target_completion_date"], "2027-09-01T00:00:00Z")


def test_case_age_court_days_variant_drops_weekends():
    """PRD §3.2: "The reporting variant, `days_pending_court`, counts only Monday-through-Friday dates strictly after the filing date, up to and including the clock date."
    PRD §3.2: "The two diverge across any span containing a weekend — a case filed on Tuesday 2026-09-01 and read on Friday 2026-09-11 shows a calendar age of 10 but a court-day age of 8."

    Design: Difficulty/dual_variant_calc/case_age_calendar_vs_court_days_variants
    """
    court = create_court()
    case = create_case(court["id"], custody_status="NON_DETAINED")
    set_clock("2026-09-11T00:00:00Z")
    case = read_case(case["id"])
    # Mon-Fri dates strictly after 2026-09-01 through 2026-09-11: 09-02, 03,
    # 04, 07, 08, 09, 10, 11 — the weekend of 2026-09-05/06 is excluded.
    assert case["days_pending_court"] == 8
    assert case["days_pending_calendar"] == 10
    assert case["days_pending_court"] != case["days_pending_calendar"]

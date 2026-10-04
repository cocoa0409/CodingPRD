"""Temporal windows: when a window admits or refuses a write."""
from test_helpers import (
    api_client, fire_event, get_learner, get_streak, get_success_data,
    grant_gems, make_learner_headers, register_learner, scene_certification_ready,
    set_clock, submit_exam_score, validate_error,
)


def _broken_streak_with_gems(gems=40):
    """Ada holds a BROKEN streak with ``focus_date`` 2026-09-01 and a gem balance."""
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    grant_gems(learner["id"], gems)
    set_clock("2026-09-01T12:00:00Z")
    fire_event("STREAK_DAY_CLOSE")
    set_clock("2026-09-02T12:00:00Z")
    fire_event("STREAK_DAY_CLOSE")
    return learner, get_streak(learner["id"])


def test_repair_is_admitted_while_the_clock_is_inside_the_window(api):
    """PRD §3.3: "It must be made before the clock has moved past the `focus_date`
    plus the repair window of `REPAIR_WINDOW_DAYS`; a late purchase is refused with
    `ERR_REPAIR_WINDOW_EXPIRED` at HTTP 422."
    PRD §3.3: "A permitted repair debits `gems_balance` by the computed price,
    restores `current_length` to the length that was active immediately before the
    break"

    Design: Difficulty/resource_temporal_overlap/streak_repair_window_closed_interval
    """
    learner, streak = _broken_streak_with_gems(gems=40)
    assert streak["status"] == "BROKEN"

    repaired = get_success_data(api_client.repair_streak(
        streak["id"],
        {"expected_streak_version": streak["version"]},
        make_learner_headers(learner["id"]),
    ))

    assert repaired["status"] == "REPAIRED", (
        "the clock sits half a day inside the window anchored on focus_date, so "
        f"the purchase is admitted, got {repaired['status']}"
    )
    assert repaired["repair_cost_gems"] == 1, (
        "a break at length 0 takes the first tier rate of 1 gem with no length "
        f"bonus, got {repaired['repair_cost_gems']}"
    )
    assert repaired["repair_purchases_this_month"] == 1


def test_repair_is_refused_once_the_clock_has_passed_the_window(api):
    """PRD §3.3: "It must be made before the clock has moved past the `focus_date`
    plus the repair window of `REPAIR_WINDOW_DAYS`; a late purchase is refused with
    `ERR_REPAIR_WINDOW_EXPIRED` at HTTP 422."

    Design: Difficulty/resource_temporal_overlap/streak_repair_window_closed_interval
    """
    learner, streak = _broken_streak_with_gems(gems=40)
    assert streak["status"] == "BROKEN"

    # Move the clock well past focus_date plus the repair window without firing a
    # day-close sweep, so the row stays BROKEN with its focus_date unchanged and
    # only the temporal check can refuse the purchase.
    set_clock("2026-10-15T12:00:00Z")

    late = api_client.repair_streak(
        streak["id"],
        {"expected_streak_version": streak["version"]},
        make_learner_headers(learner["id"]),
    )
    validate_error(late, "ERR_REPAIR_WINDOW_EXPIRED")

    assert get_learner(learner["id"])["gems_balance"] == 40, (
        "a refused repair debits none of the learner's gems"
    )


def test_exam_submission_is_admitted_exactly_at_the_proctor_window_edge(api):
    """PRD §3.8: "it is admitted only while the clock is at or before
    `proctor_started_at` plus the proctoring window of `PROCTOR_WINDOW_HOURS`"
    PRD §2.9: "Threshold comparisons expressed as "at least" or "at or below"
    include the boundary value itself."

    Design: Difficulty/resource_temporal_overlap/proctor_window_half_open_on_later_exam
    """
    scene = scene_certification_ready(proctor_window_hours=24)
    exam_id = scene["exam"]["id"]
    learner_id = scene["learner"]["id"]

    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import proctor_exam

    proctor_exam(exam_id, proctor_user_id="proctor-1")

    set_clock("2026-09-02T00:00:00Z")
    admitted = get_success_data(submit_exam_score(exam_id, learner_id, 80))
    assert admitted["status"] == "SUBMITTED", (
        "the submission at exactly proctor_started_at plus the window is "
        f"admitted, got {admitted['status']}"
    )


def test_exam_submission_is_refused_once_the_proctor_window_closes(api):
    """PRD §3.8: "submitting after that window closes is refused with
    `ERR_PROCTOR_WINDOW_EXPIRED` at HTTP 422"
    PRD §3.8: "Submitting against an exam that is not `PROCTORING` is refused with
    `ERR_EXAM_NOT_PROCTORING` at HTTP 409."

    Design: Difficulty/resource_temporal_overlap/proctor_window_half_open_on_later_exam
    """
    scene = scene_certification_ready(proctor_window_hours=24)
    exam_id = scene["exam"]["id"]
    learner_id = scene["learner"]["id"]

    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import proctor_exam

    proctor_exam(exam_id, proctor_user_id="proctor-1")
    set_clock("2026-09-02T01:00:00Z")

    late = submit_exam_score(exam_id, learner_id, 80)
    validate_error(late, "ERR_PROCTOR_WINDOW_EXPIRED")
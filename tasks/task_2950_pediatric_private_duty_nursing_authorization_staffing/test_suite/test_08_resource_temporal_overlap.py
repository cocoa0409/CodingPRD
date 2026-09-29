"""Two contended resources, two different interval semantics.

The nurse is guarded by a 60-minute proximity buffer, so adjacency collides. The
patient's home is guarded by strict overlap against `concurrent_nurse_limit`, so
adjacency is fine. The same 16:00-abuts-16:00 pattern therefore gets opposite
verdicts depending on which resource is being protected.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NURSE_SHIFT_OVERLAP, ERR_PATIENT_CONCURRENCY_EXCEEDED
from test_helpers.assertions import assert_hours
from test_helpers.test_users import SCHEDULER
from test_helpers.types import AssignmentStatus, StaffingStatus


def _one_covered_day_shift_for_the_nurse(api):
    """N1 works 08:00-16:00; shift P abuts that end instant and shift Q starts
    exactly 60 minutes after it."""
    base = fx.setup_baseline(api)
    covered = fx.publish_shift(
        api, base.case_id, "2026-08-03T08:00:00Z", "2026-08-03T16:00:00Z"
    )
    fx.assign_nurse(api, covered["id"], base.nurse_id)

    shift_p = fx.publish_shift(
        api, base.case_id, "2026-08-03T16:00:00Z", "2026-08-03T20:00:00Z"
    )
    shift_q = fx.publish_shift(
        api, base.case_id, "2026-08-03T17:00:00Z", "2026-08-03T21:00:00Z"
    )
    return base, shift_p, shift_q


def test_a_zero_minute_gap_falls_inside_the_nurse_rest_buffer(api):
    """A shift starting at the previous shift's exact end instant leaves a zero
    gap, which is less than the 60-minute buffer, so the assignment answers
    ERR_NURSE_SHIFT_OVERLAP - and not the patient rule, whose strict-overlap test
    16:00-20:00 against 08:00-16:00 does not trip.

    Design: Difficulty/resource_temporal_overlap/nurse_rest_buffer_rejects_adjacent_shift_but_allows_a_sixty_minute_gap
    """
    base, shift_p, _shift_q = _one_covered_day_shift_for_the_nurse(api)

    response = api.create_assignment(
        f.assignment_payload(shift_p["id"], base.nurse_id, shift_p["version"]), SCHEDULER
    )
    error = validate_error(response, ERR_NURSE_SHIFT_OVERLAP, 409)
    assert error["error_id"] != ERR_PATIENT_CONCURRENCY_EXCEEDED


def test_a_gap_of_exactly_sixty_minutes_clears_the_rest_buffer(api):
    """The buffer is inclusive at its edge: an hour of rest between 16:00 and 17:00
    is enough, so the second candidate is assigned and the assignment is ACTIVE.

    Design: Difficulty/resource_temporal_overlap/nurse_rest_buffer_rejects_adjacent_shift_but_allows_a_sixty_minute_gap
    """
    base, shift_p, shift_q = _one_covered_day_shift_for_the_nurse(api)
    api.create_assignment(
        f.assignment_payload(shift_p["id"], base.nurse_id, shift_p["version"]), SCHEDULER
    )

    assignment = validate_success(
        api.create_assignment(
            f.assignment_payload(shift_q["id"], base.nurse_id, shift_q["version"]), SCHEDULER
        ),
        201,
    )
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment


def test_only_the_accepted_assignment_adds_to_the_committed_totals(api):
    """480 minutes of covered work plus the 240-minute accepted shift make 720
    scheduled minutes and 12.00 committed hours; the refused shift P is still OPEN
    and contributed nothing.

    Design: Difficulty/resource_temporal_overlap/nurse_rest_buffer_rejects_adjacent_shift_but_allows_a_sixty_minute_gap
    """
    base, shift_p, shift_q = _one_covered_day_shift_for_the_nurse(api)
    api.create_assignment(
        f.assignment_payload(shift_p["id"], base.nurse_id, shift_p["version"]), SCHEDULER
    )
    fx.assign_nurse(api, shift_q["id"], base.nurse_id, shift_q["version"])

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 720
    reread = fx.refresh_shift(api, shift_p["id"])
    assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread
    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 12.00)


def _one_covered_day_shift_at_the_home(api):
    """N1 covers the home 08:00-16:00 under a concurrent_nurse_limit of 1; shift R
    overlaps that window by four hours and shift S abuts its end."""
    base = fx.setup_baseline(api, case_overrides={"concurrent_nurse_limit": 1})
    second_nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002"
    )

    covered = fx.publish_shift(
        api, base.case_id, "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"
    )
    fx.assign_nurse(api, covered["id"], base.nurse_id)

    shift_r = fx.publish_shift(
        api, base.case_id, "2026-08-05T12:00:00Z", "2026-08-05T20:00:00Z"
    )
    shift_s = fx.publish_shift(
        api, base.case_id, "2026-08-05T16:00:00Z", "2026-08-05T22:00:00Z"
    )
    return base, second_nurse, shift_r, shift_s


def test_a_second_nurse_overlapping_the_covered_window_breaches_the_home_limit(api):
    """12:00-20:00 strictly overlaps the covered 08:00-16:00 window, and the home
    admits one nurse at a time, so the second nurse's assignment answers
    ERR_PATIENT_CONCURRENCY_EXCEEDED.

    Design: Difficulty/resource_temporal_overlap/patient_home_concurrency_allows_adjacency_and_blocks_strict_overlap
    """
    _base, second_nurse, shift_r, _shift_s = _one_covered_day_shift_at_the_home(api)

    response = api.create_assignment(
        f.assignment_payload(shift_r["id"], second_nurse["id"], shift_r["version"]), SCHEDULER
    )
    validate_error(response, ERR_PATIENT_CONCURRENCY_EXCEEDED, 409)


def test_adjacency_at_the_home_is_allowed_because_the_test_is_strict_overlap(api):
    """16:00 is not strictly inside 08:00-16:00, so the handover shift is accepted -
    the exact adjacency pattern the nurse-side buffer rejected.

    Design: Difficulty/resource_temporal_overlap/patient_home_concurrency_allows_adjacency_and_blocks_strict_overlap
    """
    _base, second_nurse, shift_r, shift_s = _one_covered_day_shift_at_the_home(api)
    api.create_assignment(
        f.assignment_payload(shift_r["id"], second_nurse["id"], shift_r["version"]), SCHEDULER
    )

    assignment = validate_success(
        api.create_assignment(
            f.assignment_payload(shift_s["id"], second_nurse["id"], shift_s["version"]),
            SCHEDULER,
        ),
        201,
    )
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment


def test_the_home_scenario_leaves_one_unfilled_shift_and_fourteen_committed_hours(api):
    """The accepted handover contributes 360 minutes to the second nurse and nothing
    to the first, giving 14.00 committed and 26.00 remaining hours, while the refused
    overlapping shift stays OPEN and counts as the case's one unfilled shift.

    Design: Difficulty/resource_temporal_overlap/patient_home_concurrency_allows_adjacency_and_blocks_strict_overlap
    """
    base, second_nurse, shift_r, shift_s = _one_covered_day_shift_at_the_home(api)
    api.create_assignment(
        f.assignment_payload(shift_r["id"], second_nurse["id"], shift_r["version"]), SCHEDULER
    )
    fx.assign_nurse(api, shift_s["id"], second_nurse["id"], shift_s["version"])

    assert fx.refresh_nurse(api, second_nurse["id"])["scheduled_minutes_this_week"] == 360
    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 480

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 14.00)
    assert_hours(authorization, "hours_remaining_this_week", 26.00)

    reread = fx.refresh_shift(api, shift_r["id"])
    assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread
    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 1, case

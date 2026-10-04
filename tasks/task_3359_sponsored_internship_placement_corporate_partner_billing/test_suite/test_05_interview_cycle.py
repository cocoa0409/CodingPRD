"""The interview cycle — a placement can loop back to the matching pool.

A failed round with rounds remaining re-opens the placement for scheduling; a
failure on the final allowed round returns it to MATCHED (PRD §3.4).
"""
from test_helpers import (
    ApiErrorId,
    assert_interview_round,
    assert_placement,
    interview_payload,
    make_partner_headers,
    record_interview_outcome,
    schedule_interview_for,
    setup_matched_placement,
    staff_headers,
    validate_error,
    validate_success,
)

SECOND_SLOT = "2026-09-21T15:00:00Z"
THIRD_SLOT = "2026-09-22T15:00:00Z"


def test_failure_on_the_final_allowed_round_returns_placement_to_matching(api):
    """PRD §3.4: "the placement instead moves `INTERVIEW_SCHEDULED → MATCHED` and
    returns to the matching pool, retaining its `student_id` and `agreement_id` so it
    can be re-interviewed or terminated"

    Design: Difficulty/non_linear_state_machine/placement_interview_cycle_returns_to_matching_pool
    """
    scenario = setup_matched_placement(max_interview_rounds=1)
    interview = schedule_interview_for(scenario.placement["id"])

    round_data = validate_success(
        api.record_interview_outcome(
            interview["id"],
            {"outcome": "FAILED", "feedback": "Communication needs another round"},
            make_partner_headers(scenario.partner["id"]),
        ),
        200,
    )
    assert round_data["outcome"] == "FAILED", round_data["outcome"]
    assert_interview_round(round_data)

    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "MATCHED", placement["state"]
    assert placement["interview_attempt"] == 1, placement["interview_attempt"]
    assert placement["student_id"] == scenario.student["id"], placement["student_id"]
    assert placement["agreement_id"] == scenario.agreement["id"], placement["agreement_id"]
    assert_placement(placement)


def test_failure_with_rounds_remaining_reopens_scheduling(api):
    """PRD §3.4: "A `FAILED` round moves it `INTERVIEW_SCHEDULED → INTERVIEWED` while
    rounds remain"
    PRD §3.4: "The placement must currently be `MATCHED`, or be `INTERVIEWED` with its
    latest round's `outcome` at `FAILED` and rounds remaining"
    PRD §3.4: "A successful scheduling creates an interview round whose `outcome`
    starts at `PENDING`, whose `round_number` is the placement's current
    `interview_attempt` plus 1, and whose `feedback` is empty"

    Design: Difficulty/non_linear_state_machine/placement_interview_cycle_returns_to_matching_pool
    """
    scenario = setup_matched_placement()
    first = schedule_interview_for(scenario.placement["id"])
    record_interview_outcome(first["id"], scenario.partner["id"], outcome="FAILED")

    after_failure = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert after_failure["state"] == "INTERVIEWED", after_failure["state"]
    assert after_failure["interview_attempt"] == 1, after_failure["interview_attempt"]

    second = schedule_interview_for(scenario.placement["id"], scheduled_for=SECOND_SLOT)
    assert second["round_number"] == 2, second["round_number"]
    assert second["outcome"] == "PENDING", second["outcome"]

    record_interview_outcome(second["id"], scenario.partner["id"], outcome="PASSED")
    after_pass = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert after_pass["state"] == "INTERVIEWED", after_pass["state"]
    assert after_pass["interview_attempt"] == 2, after_pass["interview_attempt"]


def test_scheduling_past_the_round_ceiling_is_refused(api):
    """PRD §3.4: "A placement that has already used all of its allowed interview
    rounds cannot be booked again: once `interview_attempt` has reached
    `max_interview_rounds` the ordinary case is a placement that failed its final
    allowed round and has returned to `MATCHED`, and there the refusal is
    `ERR_INTERVIEW_ROUNDS_EXHAUSTED` (409)."

    Design: Difficulty/boundary_precision_check/interview_rounds_exhausted_after_last_allowed_round
    """
    scenario = setup_matched_placement(max_interview_rounds=2)
    first = schedule_interview_for(scenario.placement["id"])
    record_interview_outcome(first["id"], scenario.partner["id"], outcome="FAILED")
    second = schedule_interview_for(scenario.placement["id"], scheduled_for=SECOND_SLOT)
    record_interview_outcome(second["id"], scenario.partner["id"], outcome="FAILED")

    response = api.schedule_interview(
        scenario.placement["id"],
        interview_payload(scheduled_for=THIRD_SLOT),
        staff_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INTERVIEW_ROUNDS_EXHAUSTED)


def test_second_round_is_still_schedulable_at_attempt_one(api):
    """PRD §3.4: "A placement that has already used all of its allowed interview
    rounds cannot be booked again: once `interview_attempt` has reached
    `max_interview_rounds` the ordinary case is a placement that failed its final
    allowed round and has returned to `MATCHED`, and there the refusal is
    `ERR_INTERVIEW_ROUNDS_EXHAUSTED` (409)."

    The ceiling is an exact count: with `max_interview_rounds` 2 the second round
    is booked at attempt 1, and only the attempt that would cross the ceiling is
    refused.

    Design: Difficulty/boundary_precision_check/interview_rounds_exhausted_after_last_allowed_round
    """
    scenario = setup_matched_placement(max_interview_rounds=2)
    first = schedule_interview_for(scenario.placement["id"])
    record_interview_outcome(first["id"], scenario.partner["id"], outcome="FAILED")
    second = schedule_interview_for(scenario.placement["id"], scheduled_for=SECOND_SLOT)
    record_interview_outcome(second["id"], scenario.partner["id"], outcome="FAILED")

    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["interview_attempt"] == 2, placement["interview_attempt"]
    assert placement["max_interview_rounds"] == 2, placement["max_interview_rounds"]
    assert placement["state"] == "MATCHED", placement["state"]

    rounds = validate_success(
        api.list_interviews(scenario.placement["id"], staff_headers()), 200
    )
    assert len(rounds) == 2, f"expected the two booked rounds, got {len(rounds)}"

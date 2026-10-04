"""Conversion plan readiness recomputation on milestone completion."""
from test_helpers import (
    get_success_data,
    setup_agreement_with_plan,
    TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_milestone_completion_recomputes_done_count_and_ready(api):
    """PRD §3.3: "the plan is ready exactly when `milestones_done` equals the
    total number of milestones and the plan contains at least one milestone."
    PRD §3.3: "Each completion recomputes `milestones_done` and `ready`."

    Design: Corner/calculations/milestone_complete_recomputes_ready_flag
    """
    ctx = setup_agreement_with_plan(num_milestones=2)
    plan_id = ctx["plan"]["id"]

    after_first = get_success_data(
        api.complete_milestone(plan_id, {"sequence": 1}, OPS)
    )
    assert after_first["milestones_done"] == 1
    assert after_first["ready"] is False

    after_second = get_success_data(
        api.complete_milestone(plan_id, {"sequence": 2}, OPS)
    )
    assert after_second["milestones_done"] == 2
    assert after_second["ready"] is True

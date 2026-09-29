"""One engagement request that breaks both the milestone-state rule and the budget
rule, paired with the control that breaks only the budget rule."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONTRACTOR_BUDGET_EXCEEDED,
    ERR_MILESTONE_NOT_OPEN_FOR_OUTSOURCING,
)
from test_helpers.assertions import assert_budget_summary
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    DEFAULT_CRITERIA_2,
    accept_milestone,
    activate,
    add_milestone,
    draft_agreement,
    read_milestone,
    setup_registry,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}
OVERSIZED = 500000


def _two_glasswing_milestones(api):
    """One accepted milestone and one still in development, both budgeted 100000."""
    reg = setup_registry(api)
    agreement_a = draft_agreement(reg, "Glasswing A", 3600000, 2500, "2027-03-31",
                                  live_ops_quarterly_funding_cents=100000)
    milestone_a = add_milestone(reg, agreement_a["id"], 1, "Alpha A", "ALPHA",
                                3600000, 100000, DEFAULT_CRITERIA_2)
    activate(reg, agreement_a["id"])
    accept_milestone(reg, milestone_a["id"], 1, ALPHA_PASSING)
    assert read_milestone(reg, milestone_a["id"])["status"] == "ACCEPTED"

    agreement_b = draft_agreement(reg, "Glasswing B", 1000000, 2500, "2027-09-30",
                                  live_ops_quarterly_funding_cents=100000)
    milestone_b = add_milestone(reg, agreement_b["id"], 1, "Alpha B", "ALPHA",
                                1000000, 100000, DEFAULT_CRITERIA_1)
    activate(reg, agreement_b["id"])
    assert read_milestone(reg, milestone_b["id"])["status"] == "IN_DEVELOPMENT"
    return reg, milestone_a, milestone_b


def _oversized_engagement(milestone_id):
    return f.engagement_payload(
        milestone_id, "ART-QUILL", OVERSIZED, "2026-08-10", "2026-09-10",
        "Concept art overflow",
    )


def test_the_closed_milestone_reports_its_state_rather_than_the_budget(api):
    """PRD §3.8: "The milestone must be open for outsourcing, meaning its `status` is
    `DEFINED`, `IN_DEVELOPMENT` or `CURE_PENDING`; anything else is
    `ERR_MILESTONE_NOT_OPEN_FOR_OUTSOURCING`, and note that this state rule
    deliberately outranks the budget cap, so an over-budget engagement pointed at an
    already-accepted milestone reports the state problem and never the money problem."

    Design: Difficulty/priority_pair_validation_conflict/cp1_milestone_not_open_for_outsourcing_outranks_contractor_budget_exceeded
    """
    reg, milestone_a, _milestone_b = _two_glasswing_milestones(api)

    response = api.create_engagement(_oversized_engagement(milestone_a["id"]), reg.dev)
    validate_error(response, ERR_MILESTONE_NOT_OPEN_FOR_OUTSOURCING, 409)


def test_the_same_request_on_an_open_milestone_reports_the_budget(api):
    """PRD §3.8: "Admission requires that basis plus the new engagement's
    `committed_cents` to be no greater than the milestone's `contractor_budget_cents`;
    exceeding it is `ERR_CONTRACTOR_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/cp1_milestone_not_open_for_outsourcing_outranks_contractor_budget_exceeded
    """
    reg, _milestone_a, milestone_b = _two_glasswing_milestones(api)

    response = api.create_engagement(_oversized_engagement(milestone_b["id"]), reg.dev)
    validate_error(response, ERR_CONTRACTOR_BUDGET_EXCEEDED, 422)


def test_neither_refusal_reserved_any_outsourcing_budget(api):
    """PRD §3.8 defines the committed basis as "the sum of `committed_cents` over
    every engagement of that milestone whose `status` is `PROPOSED`, `ACTIVE`,
    `SUSPENDED` or `COMPLETED`"; a refused request never becomes such an engagement.

    Design: Difficulty/priority_pair_validation_conflict/cp1_milestone_not_open_for_outsourcing_outranks_contractor_budget_exceeded
    """
    reg, milestone_a, milestone_b = _two_glasswing_milestones(api)

    api.create_engagement(_oversized_engagement(milestone_a["id"]), reg.dev)
    api.create_engagement(_oversized_engagement(milestone_b["id"]), reg.dev)

    for milestone in (milestone_a, milestone_b):
        rows, meta = validate_paginated(
            api.list_engagements(reg.dev, {"milestone_id": milestone["id"]})
        )
        assert rows == [] and meta["total_count"] == 0

    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone_a["id"], reg.dev)),
        milestone_id=milestone_a["id"],
        budget=100000,
        committed_basis=0,
        incurred_basis=0,
        available_committed=100000,
        overrun=0,
    )

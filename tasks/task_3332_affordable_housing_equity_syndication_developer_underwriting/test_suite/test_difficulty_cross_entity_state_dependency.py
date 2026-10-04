"""Depth: one entity's state gating another entity's write.

A commit is gated by the standing of the project's fund, and a guarantee draw is
gated by the review standing of the project it covers.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    SCENARIO,
    add_allocation,
    add_guarantee,
    add_project,
    api_client,
    commit_project,
    draw_on_guarantee,
    finalize_underwriting,
    form_fund,
    get_success_data,
    onboard_investor,
    open_review,
    open_subscription,
    list_project_guarantees,
    read_developer,
    read_fund,
    read_project,
    resolve_review,
    set_logical_clock,
    setup_canonical_scenario,
    setup_guarantee_scenario,
    setup_project_in_compliance_period,
    validate_error,
    validate_success,
)

_JUNIPER = dict(SCENARIO["project_juniper"])
_CLOCK_AFTER_CLOSE = "2027-01-05T00:00:00Z"


def _committable_project(developer_id, fund_id, name, absorption=0.83, loan=700000000):
    project = add_project(
        developer_id,
        fund_id,
        project_name=name,
        construction_budget_cents=1234567890,
        construction_loan_cents=loan,
        operating_pro_forma_noi_cents=72000000,
        debt_service_cents=60000000,
        market_study_absorption_score=absorption,
        sponsor_experience_months=96,
    )
    add_allocation(project["id"])
    return finalize_underwriting(project)


def _find_guarantee(project_id, guarantee_id):
    for guarantee in list_project_guarantees(project_id):
        if guarantee["id"] == guarantee_id:
            return guarantee
    raise AssertionError(f"Guarantee {guarantee_id} not found under project {project_id}")


def _noncompliant(project_id, period_index, period_end):
    review = open_review(project_id, review_period_index=period_index, review_period_end=period_end)
    resolve_review(review["id"], outcome="ESCALATED")
    return resolve_review(review["id"], outcome="NONCOMPLIANT")


def test_commit_succeeds_while_the_fund_is_closed_and_moves_it_to_deploying():
    """PRD §3.4: "the project's fund must be in `CLOSING`, `CLOSED`, or
    `DEPLOYING` and its `posture` must be `OPEN`"
    PRD §3.3: "Once a fund has closed, it moves to `DEPLOYING` the moment its
    first allocation is placed into `COMMITTED` by a project commitment."

    Design: Difficulty/cross_entity_state_dependency/project_commit_guarded_by_fund_status_and_posture
    """
    scenario = setup_canonical_scenario(with_subscription=True, with_project=False)
    project = _committable_project(
        scenario.developer["id"], scenario.fund["id"], "Riverside Commons"
    )

    set_logical_clock(_CLOCK_AFTER_CLOSE)
    assert read_fund(scenario.fund["id"])["status"] == "CLOSED"

    committed = commit_project(project["id"])

    assert committed["status"] == "COMMITTED"
    assert read_fund(scenario.fund["id"])["status"] == "DEPLOYING"


def test_commit_is_refused_while_the_fund_posture_is_frozen():
    """PRD §3.8: "A fund whose posture is `FROZEN` refuses both project
    commitments and capital call creations for every one of its projects, and both
    are rejected with `ERR_FUND_POSTURE_FROZEN`."
    PRD §3.7: "if the project's `compliance_failure_count` reaches 2, the owning
    fund's posture becomes `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/project_commit_guarded_by_fund_status_and_posture
    """
    scenario = setup_project_in_compliance_period()
    project_id = scenario.project["id"]

    _noncompliant(project_id, 0, "2027-03-31T00:00:00Z")
    _noncompliant(project_id, 1, "2027-04-01T00:00:00Z")

    assert read_project(project_id)["compliance_failure_count"] == 2
    assert read_fund(scenario.fund["id"])["posture"] == "FROZEN"
    assert read_developer(scenario.developer["id"])["status"] == "ELIGIBLE"

    second = _committable_project(
        scenario.developer["id"], scenario.fund["id"], "Juniper Flats"
    )
    response = api_client.commit_project(
        second["id"], TEST_USERS["underwriter_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FUND_POSTURE_FROZEN)
    assert read_project(second["id"])["status"] == "UNDERWRITING"


def test_completion_draw_is_refused_before_the_project_review_is_escalated():
    """PRD §3.6: "a `COMPLETION` guarantee may be drawn only when the project has
    at least one review in status `ESCALATED`."

    The specific error id is not pinned by the PRD, so this test asserts only
    that the draw is refused and that it left the guarantee untouched.

    Design: Difficulty/cross_entity_state_dependency/guarantee_draw_guarded_by_project_review_state
    """
    scenario = setup_guarantee_scenario(
        guarantee_type="COMPLETION",
        guaranteed_amount_cents=120000000,
        with_escalated_review=False,
    )
    guarantee = scenario.guarantee
    review = open_review(scenario.project["id"], review_period_index=1)
    assert review["status"] == "PENDING"

    response = api_client.draw_guarantee(
        guarantee["id"], 30000000, TEST_USERS["asset_manager_headers"]
    )

    assert 400 <= response.status_code < 500, (
        "a COMPLETION draw is not permitted while no review is ESCALATED"
    )
    untouched = _find_guarantee(scenario.project["id"], guarantee["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["drawn_amount_cents"] == 0
    assert untouched["remaining_capacity_cents"] == 120000000


def test_completion_draw_succeeds_once_the_review_is_escalated():
    """PRD §3.6: "a `COMPLETION` guarantee may be drawn only when the project has
    at least one review in status `ESCALATED`."
    PRD §3.6: "A draw supplies `requested_amount_cents`, and moves the guarantee
    from `ACTIVE` to `DRAWN` when the draw is positive."

    Design: Difficulty/cross_entity_state_dependency/guarantee_draw_guarded_by_project_review_state
    """
    scenario = setup_guarantee_scenario(
        guarantee_type="COMPLETION",
        guaranteed_amount_cents=120000000,
        with_escalated_review=False,
    )
    guarantee = scenario.guarantee
    review = open_review(scenario.project["id"], review_period_index=1)
    resolve_review(review["id"], outcome="ESCALATED")

    drawn = draw_on_guarantee(guarantee["id"], 30000000)

    assert drawn["status"] == "DRAWN"
    assert drawn["drawn_amount_cents"] == 30000000
    assert drawn["remaining_capacity_cents"] == 90000000
    assert read_project(scenario.project["id"])["status"] == "DISTRESSED"

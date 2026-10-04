"""Breadth: transitions that must be refused from the wrong state."""

import pytest

from test_helpers import (
    TEST_USERS,
    make_investor_headers,
    api_client,
    commit_project,
    create_payin_payload,
    exercise_exit_action,
    get_success_data,
    list_project_allocations,
    open_review,
    plan_exit_event,
    read_fund,
    read_project,
    read_subscription,
    resolve_review,
    setup_committed_project,
    setup_defaulted_subscription,
    setup_exit_eligible_project,
    validate_error,
)


def test_committing_an_already_committed_project_is_refused():
    """PRD §3.4: "A commit attempted with `underwriting_stage` still at
    `PRELIMINARY`, or from a project status other than `UNDERWRITING`, or with no
    allocation in `RESERVED` or `AWARDED`, or with a `dscr` below 1.15, or with an
    absorption score below 0.60, or with `sponsor_experience_months` below 24, is
    rejected with `ERR_PROJECT_NOT_COMMITTABLE`."

    Design: Corner/state_machines/commit_from_an_already_committed_project_returns_project_not_committable
    """
    from test_helpers import ApiErrorId

    scenario = setup_committed_project()
    project_id = scenario.project["id"]

    response = api_client.commit_project(project_id, TEST_USERS["underwriter_headers"])

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_COMMITTABLE)
    assert response.status_code == 409
    assert read_project(project_id)["status"] == "COMMITTED"
    assert list_project_allocations(project_id)[0]["status"] == "COMMITTED"
    # The clock is still 2026-09-02, short of the fund's 2026-12-31
    # subscription_close_date, so the fund is CLOSING and never closed: the
    # commit leaves it there.  PRD §3.3 only moves a fund to DEPLOYING from
    # CLOSED ("Once a fund has closed, it moves to `DEPLOYING` the moment its
    # first allocation is placed into `COMMITTED`").
    assert read_fund(scenario.fund["id"])["status"] == "CLOSING"


def test_an_exit_event_walks_pending_through_decline_to_closed():
    """PRD §3.9: "The exit event moves through `PENDING → OPTION_NOTICE_ISSUED →
    ROFR_WINDOW → EXERCISED`, with a decline branch to `DECLINED` and a final
    `CLOSED`."
    PRD §3.9: "Closing is the `AssetManager`'s final act, moving the event from
    `EXERCISED` or `DECLINED` to `CLOSED` once the exit distribution has been
    recorded."

    Design: Corner/state_machines/exit_event_issue_notice_from_a_closed_event_returns_exit_event_not_pending
    """
    scenario = setup_exit_eligible_project()
    exit_event = plan_exit_event(scenario.project["id"])

    issued = exercise_exit_action(exit_event["id"], "ISSUE_NOTICE")
    assert issued["status"] == "OPTION_NOTICE_ISSUED"

    declined = exercise_exit_action(exit_event["id"], "DECLINE")
    assert declined["status"] == "DECLINED"

    closed = exercise_exit_action(exit_event["id"], "CLOSE")
    assert closed["status"] == "CLOSED"
    assert read_project(scenario.project["id"])["status"] == "COMPLIANCE_PERIOD"


def test_issuing_a_notice_from_a_closed_exit_event_is_refused():
    """PRD §3.9: "An exit action requested from a state that does not permit it is
    rejected with `ERR_EXIT_EVENT_NOT_PENDING`: issuing a notice from anything
    other than `PENDING`, exercising from anything other than `ROFR_WINDOW`, or
    closing from anything other than `EXERCISED` or `DECLINED`."

    Design: Corner/state_machines/exit_event_issue_notice_from_a_closed_event_returns_exit_event_not_pending
    """
    from test_helpers import ApiErrorId

    scenario = setup_exit_eligible_project()
    exit_event = plan_exit_event(scenario.project["id"])
    exercise_exit_action(exit_event["id"], "ISSUE_NOTICE")
    exercise_exit_action(exit_event["id"], "DECLINE")
    closed = exercise_exit_action(exit_event["id"], "CLOSE")
    assert closed["status"] == "CLOSED"
    price_after_close = closed["option_price_cents"]

    response = api_client.exercise_exit_event(
        exit_event["id"], "ISSUE_NOTICE", TEST_USERS["underwriter_headers"]
    )

    validate_error(response, ApiErrorId.ERR_EXIT_EVENT_NOT_PENDING)
    assert response.status_code == 409
    from test_helpers import list_project_exit_events

    stored = list_project_exit_events(scenario.project["id"])[0]
    assert stored["status"] == "CLOSED"
    assert stored["option_price_cents"] == price_after_close


def test_a_payin_against_a_defaulted_subscription_is_refused():
    """PRD §3.2: "A pay-in against a subscription that has already reached
    `DEFAULTED` is rejected with `ERR_SUBSCRIPTION_TERMINAL`, because default is
    terminal."

    Design: Corner/state_machines/payin_against_a_defaulted_subscription_returns_subscription_terminal
    """
    from test_helpers import ApiErrorId

    scenario = setup_defaulted_subscription()
    before = read_subscription(scenario.subscription["id"])
    fund_before = read_fund(scenario.fund["id"])
    assert before["status"] == "DEFAULTED"

    response = api_client.create_payin(
        before["id"],
        create_payin_payload(5000000),
        make_investor_headers(scenario.investor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_TERMINAL)
    assert response.status_code == 409
    after = read_subscription(before["id"])
    assert after["status"] == "DEFAULTED"
    assert after["paid_in_cents"] == before["paid_in_cents"]
    assert read_fund(scenario.fund["id"])["funded_equity_cents"] == (
        fund_before["funded_equity_cents"]
    )


def test_a_review_that_scores_below_seventy_resolves_compliant():
    """PRD §3.7: "a score below 70 resolves the review from `PENDING` to
    `COMPLIANT`; a score of at least 70 and below 85 resolves it from `PENDING` to
    `WATCH`, making it visible on the project's watch list; a score of 85 or above
    resolves it from `PENDING` to `ESCALATED`."

    Occupancy 0.95, DSCR 1.4 and a 60000000 reserve score 33 + 28 + 0 = 61.

    Design: Corner/state_machines/review_resolve_from_a_compliant_review_returns_review_not_escalated
    """
    scenario = setup_committed_project()
    review = open_review(
        scenario.project["id"],
        review_period_index=1,
        review_period_end="2026-06-30T00:00:00Z",
        occupancy_pct=0.95,
        dscr_observed=1.4,
        reserve_balance_cents=60000000,
    )
    assert review["risk_score"] == 61

    resolved = resolve_review(review["id"], headers=TEST_USERS["asset_manager_headers"])

    assert resolved["status"] == "COMPLIANT"


def test_a_noncompliant_finding_on_a_never_escalated_review_is_refused():
    """PRD §3.7: "A `NONCOMPLIANT` or `CURED` outcome requested on a review that
    never reached `ESCALATED` or `NONCOMPLIANT` is rejected with
    `ERR_REVIEW_NOT_ESCALATED`."

    Design: Corner/state_machines/review_resolve_from_a_compliant_review_returns_review_not_escalated
    """
    from test_helpers import ApiErrorId

    scenario = setup_committed_project()
    review = open_review(
        scenario.project["id"],
        review_period_index=1,
        review_period_end="2026-06-30T00:00:00Z",
        occupancy_pct=0.95,
        dscr_observed=1.4,
        reserve_balance_cents=60000000,
    )
    resolved = resolve_review(review["id"], headers=TEST_USERS["asset_manager_headers"])
    assert resolved["status"] == "COMPLIANT"

    response = api_client.resolve_review(
        review["id"],
        TEST_USERS["compliance_officer_headers"],
        outcome="NONCOMPLIANT",
    )

    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_ESCALATED)
    assert response.status_code == 409
    assert read_project(scenario.project["id"])["compliance_failure_count"] == 0

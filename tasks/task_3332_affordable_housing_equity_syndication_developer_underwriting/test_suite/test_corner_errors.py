"""Breadth: each conflict and bucket error fired by its own trigger.

The credit-shortfall-waterfall corner instance is not translated: the PRD never
declares a response field that carries the per-subscription share the waterfall
computes, and the DISTRIBUTE action accepts no amount, so neither the pinned
order nor ERR_DISTRIBUTION_EXCEEDS_DELIVERED has a reachable observable.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    add_guarantee,
    api_client,
    create_payin_payload,
    create_subscription_payload,
    draw_on_guarantee,
    find_capital_call,
    form_fund,
    get_success_data,
    list_project_capital_calls,
    list_project_guarantees,
    make_investor_headers,
    onboard_investor,
    open_review,
    open_subscription,
    read_developer,
    read_fund,
    read_project,
    read_subscription,
    resolve_review,
    schedule_capital_call,
    set_logical_clock,
    setup_committed_project,
    setup_canonical_scenario,
    setup_guarantee_scenario,
    validate_error,
)

_AGENCY = "Oregon Housing and Community Services"


def test_a_second_call_on_the_same_milestone_is_a_duplicate_conflict():
    """PRD §3.5: "No other capital call of the same project may carry the same
    `milestone` in any status at all, else the request is rejected with
    `ERR_DUPLICATE_CALL_MILESTONE`."

    The first call is left SCHEDULED, so the duplicate check cannot be limited to
    issued calls. The PRD states the rule on the issue path, so this test accepts
    a refusal at either point while pinning the error id.

    Design: Corner/errors/duplicate_call_milestone_blocks_the_second_call_regardless_of_status
    """
    from test_helpers import ApiErrorId

    scenario = setup_committed_project()
    project_id = scenario.project["id"]
    first = schedule_capital_call(project_id, "CONSTRUCTION_START")
    assert first["status"] == "SCHEDULED"

    set_logical_clock("2026-10-05T00:00:00Z")
    from test_helpers import create_capital_call_payload

    second_response = api_client.create_capital_call(
        project_id,
        create_capital_call_payload(
            milestone="CONSTRUCTION_START",
            expected_project_version=read_project(project_id)["version"],
            scheduled_date="2026-10-02T00:00:00Z",
            due_date="2026-11-01T00:00:00Z",
        ),
        TEST_USERS["asset_manager_headers"],
    )

    if second_response.status_code >= 400:
        validate_error(second_response, ApiErrorId.ERR_DUPLICATE_CALL_MILESTONE)
    else:
        second = get_success_data(second_response)
        validate_error(
            api_client.issue_capital_call(
                second["id"], TEST_USERS["asset_manager_headers"]
            ),
            ApiErrorId.ERR_DUPLICATE_CALL_MILESTONE,
        )
        # The rule is stated on the issue path (PRD §3.5: "No other capital call
        # of the same project may carry the same `milestone` in any status at
        # all"), so a refused issue leaves the duplicate row SCHEDULED rather
        # than removing it.
        stored = find_capital_call(project_id, second["id"])
        assert stored["status"] == "SCHEDULED"


def test_a_second_rofr_window_overlapping_the_first_is_rejected():
    """PRD §3.9: "a second exit notice for the same project whose window would
    overlap an already-open window is rejected with `ERR_ROFR_WINDOW_OVERLAP`."

    Design: Corner/errors/rofr_window_overlap_rejects_a_second_open_window_on_the_same_project
    """
    from test_helpers import ApiErrorId, exercise_exit_action, plan_exit_event
    from test_helpers import setup_exit_eligible_project

    scenario = setup_exit_eligible_project()
    project_id = scenario.project["id"]
    first = plan_exit_event(
        project_id,
        rofr_notice_date="2031-01-01T00:00:00Z",
        rofr_window_days=90,
        exercise_deadline="2031-06-30T00:00:00Z",
    )
    second = plan_exit_event(
        project_id,
        rofr_notice_date="2031-02-01T00:00:00Z",
        rofr_window_days=90,
        exercise_deadline="2031-07-31T00:00:00Z",
    )
    exercise_exit_action(first["id"], "ISSUE_NOTICE")
    exercise_exit_action(first["id"], "OPEN_ROFR")
    exercise_exit_action(second["id"], "ISSUE_NOTICE")

    response = api_client.exercise_exit_event(
        second["id"], "OPEN_ROFR", TEST_USERS["asset_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROFR_WINDOW_OVERLAP)
    assert response.status_code == 409


def test_a_second_guarantee_of_the_same_type_may_not_overlap():
    """PRD §3.6: "a guarantee of the same project and same `guarantee_type` may
    not cover an interval that overlaps a non-`RELEASED` guarantee already on the
    books; an overlap is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`."

    Design: Corner/errors/coverage_window_overlap_rejects_a_second_guarantee_of_the_same_type
    """
    from test_helpers import ApiErrorId, create_guarantee_payload

    scenario = setup_committed_project()
    project_id = scenario.project["id"]
    first = add_guarantee(
        project_id,
        guarantee_type="RECAPTURE",
        guaranteed_amount_cents=90000000,
        recapture_pct=0.125,
        coverage_start_date="2027-01-01T00:00:00Z",
        coverage_end_date="2032-01-01T00:00:00Z",
    )

    response = api_client.create_guarantee(
        project_id,
        create_guarantee_payload(
            guarantee_type="RECAPTURE",
            guaranteed_amount_cents=50000000,
            recapture_pct=0.125,
            coverage_start_date="2031-12-31T00:00:00Z",
            coverage_end_date="2033-01-01T00:00:00Z",
        ),
        TEST_USERS["asset_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP)
    assert len(list_project_guarantees(project_id)) == 1
    assert list_project_guarantees(project_id)[0]["remaining_capacity_cents"] == 90000000
    assert read_developer(scenario.developer["id"])["guarantee_exposure_cents"] == 90000000


def test_an_overdrawn_guarantee_is_clamped_to_its_capacity():
    """PRD §3.6: "The amount drawn increases by the lesser of the requested amount
    and the guarantee's remaining capacity, so a draw larger than the capacity
    simply consumes the capacity rather than being rejected."

    Design: Corner/errors/overdrawn_guarantee_is_clamped_not_rejected
    """
    scenario = setup_guarantee_scenario(
        guarantee_type="COMPLETION",
        guaranteed_amount_cents=90000000,
        with_escalated_review=True,
    )

    drawn = draw_on_guarantee(scenario.guarantee["id"], 200000000)

    assert drawn["drawn_amount_cents"] == 90000000
    assert drawn["remaining_capacity_cents"] == 0
    assert drawn["status"] == "DRAWN"


def test_a_noncompliant_finding_before_the_period_closes_is_refused():
    """PRD §3.7: "a review may be moved from `ESCALATED` to `NONCOMPLIANT` only
    once the logical clock has reached the review's `review_period_end`, because a
    noncompliance finding may not be recorded before the reviewed period has
    closed, and a finding recorded earlier is rejected with
    `ERR_REVIEW_PERIOD_OPEN`."

    Design: Corner/errors/review_period_open_blocks_a_noncompliant_finding
    """
    from test_helpers import ApiErrorId

    scenario = setup_committed_project()
    project_id = scenario.project["id"]
    review = open_review(
        project_id,
        review_period_index=1,
        review_period_end="2027-06-30T00:00:00Z",
    )
    escalated = resolve_review(
        review["id"],
        outcome="ESCALATED",
        headers=TEST_USERS["compliance_officer_headers"],
    )
    assert escalated["status"] == "ESCALATED"

    response = api_client.resolve_review(
        review["id"],
        TEST_USERS["compliance_officer_headers"],
        outcome="NONCOMPLIANT",
    )

    validate_error(response, ApiErrorId.ERR_REVIEW_PERIOD_OPEN)
    assert response.status_code == 422
    assert read_project(project_id)["compliance_failure_count"] == 0
    from test_helpers import list_project_reviews

    assert list_project_reviews(project_id)[0]["status"] == "ESCALATED"


def test_a_second_subscription_for_the_same_fund_and_investor_is_rejected():
    """PRD §3.2: "Only one non-`DEFAULTED` subscription may exist for any given
    fund-and-investor pair; a second attempt is rejected with
    `ERR_DUPLICATE_SUBSCRIPTION`."

    The second attempt carries the fund's live version so the duplicate rule is
    the only rule that can fail.

    Design: Corner/errors/duplicate_subscription_on_the_same_fund_and_investor_is_rejected
    """
    from test_helpers import ApiErrorId

    scenario = setup_canonical_scenario(with_subscription=False, with_project=False)
    first = open_subscription(scenario.fund, scenario.investor, committed_cents=460000000)

    live = read_fund(scenario.fund["id"])
    response = api_client.create_subscription(
        scenario.fund["id"],
        create_subscription_payload(
            investor_id=scenario.investor["id"],
            expected_fund_version=live["version"],
            committed_cents=10000000,
            payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
        ),
        make_investor_headers(scenario.investor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION)
    assert response.status_code == 409
    fund_after = read_fund(scenario.fund["id"])
    assert fund_after["subscription_count"] == 1
    assert fund_after["subscribed_equity_cents"] == 460000000


def test_a_payin_above_the_committed_amount_returns_overpayment():
    """PRD §3.2: "A pay-in that would push `paid_in_cents` above `committed_cents`
    is rejected with `ERR_OVERPAYMENT`."

    Northline commits 75000000 and pays 60000000; a further 20000000 would reach
    80000000.

    Design: Corner/errors/payin_above_the_committed_amount_returns_overpayment
    """
    from test_helpers import ApiErrorId

    scenario = setup_canonical_scenario(with_subscription=False, with_project=False)
    open_subscription(scenario.fund, scenario.investor, committed_cents=425000000)
    northline = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_2",
    )
    subscription = open_subscription(
        scenario.fund, northline, committed_cents=75000000
    )
    assert read_fund(scenario.fund["id"])["status"] == "CLOSING"

    from test_helpers import record_payin

    record_payin(subscription, 60000000, northline["id"])
    partially = read_subscription(subscription["id"])
    assert partially["status"] == "PARTIALLY_FUNDED"
    assert partially["paid_in_cents"] == 60000000

    response = api_client.create_payin(
        subscription["id"],
        create_payin_payload(20000000),
        make_investor_headers(northline["id"]),
    )

    validate_error(response, ApiErrorId.ERR_OVERPAYMENT)
    assert response.status_code == 422
    after = read_subscription(subscription["id"])
    assert after["paid_in_cents"] == 60000000
    assert after["status"] == "PARTIALLY_FUNDED"
    assert after["unfunded_commitment_cents"] == 15000000

"""Depth: intervals that may touch but may not overlap.

Two different temporal rules on two different resources: allocation award
intervals are half-open and permit adjacency, while capital calls must start at
least thirty days after the previous paid call's due date.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_allocation,
    api_client,
    assert_same_instant,
    create_allocation_payload,
    create_capital_call_payload,
    find_capital_call,
    get_success_data,
    issue_call,
    list_project_allocations,
    read_project,
    schedule_capital_call,
    set_logical_clock,
    setup_canonical_scenario,
    setup_project_with_paid_call,
    validate_error,
    validate_success,
)

_AGENCY = "Oregon Housing and Community Services"
_CLOCK_1130 = "2026-11-30T00:00:00Z"


def _project_with_allocation():
    scenario = setup_canonical_scenario(with_subscription=False, with_project=True)
    allocation = add_allocation(scenario.project["id"])
    return scenario, allocation


def test_an_award_interval_that_starts_before_the_previous_deadline_is_rejected():
    """PRD §3.4: "That move is refused when the new allocation's award interval,
    from `awarded_date` up to but not including `placed_in_service_deadline`,
    overlaps another `AWARDED` or `RESERVED` allocation of the same project and
    `state_agency`."

    The first award covers [2026-08-15, 2028-12-31), so a successor starting at
    2028-12-30T23:59:59Z still overlaps it.

    Design: Difficulty/resource_temporal_overlap/allocation_award_intervals_allow_adjacency_reject_overlap
    """
    scenario, allocation = _project_with_allocation()
    project_id = scenario.project["id"]

    response = api_client.create_allocation(
        project_id,
        create_allocation_payload(
            state_agency=_AGENCY,
            awarded_credit_dollars_cents=100000000,
            awarded_date="2028-12-30T23:59:59Z",
            placed_in_service_deadline="2030-12-31T00:00:00Z",
        ),
        TEST_USERS["underwriter_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ALLOCATION_PERIOD)
    allocations = list_project_allocations(project_id)
    assert len(allocations) == 1
    assert allocations[0]["id"] == allocation["id"]
    assert allocations[0]["status"] == "AWARDED"


def test_an_award_interval_that_starts_exactly_at_the_deadline_is_allowed():
    """PRD §3.4: "touching intervals are permitted, so a new `awarded_date` that
    exactly equals an existing `placed_in_service_deadline` is allowed."

    Design: Difficulty/resource_temporal_overlap/allocation_award_intervals_allow_adjacency_reject_overlap
    """
    scenario, allocation = _project_with_allocation()
    project_id = scenario.project["id"]

    response = api_client.create_allocation(
        project_id,
        create_allocation_payload(
            state_agency=_AGENCY,
            awarded_credit_dollars_cents=100000000,
            awarded_date="2028-12-31T00:00:00Z",
            placed_in_service_deadline="2030-12-31T00:00:00Z",
        ),
        TEST_USERS["underwriter_headers"],
    )

    created = validate_success(response, expected_status=201)
    assert created["status"] == "AWARDED"
    assert_same_instant(created["awarded_date"], "2028-12-31T00:00:00Z")
    assert len(list_project_allocations(project_id)) == 2
    assert read_project(project_id)["committed_credit_dollars_cents"] == 0


def test_a_call_starting_twenty_nine_days_after_the_previous_due_date_is_rejected():
    """PRD §3.5: "the call's `scheduled_date` must be at least 30 days after the
    `due_date` of the most recently `PAID` or `DEFICIENT` capital call of the same
    project; when there is no such prior call the buffer check passes vacuously."
    PRD §3.5: "A call whose `scheduled_date` falls fewer than 30 days after that
    prior `due_date` is rejected with `ERR_CALL_BUFFER_TOO_SHORT`."

    The paid call was due 2026-10-31, so 2026-11-29 is one day short.

    Design: Difficulty/resource_temporal_overlap/capital_call_buffers_require_thirty_days_after_the_previous_due_date
    """
    scenario = setup_project_with_paid_call()
    project_id = scenario.project["id"]
    assert scenario.call["status"] == "PAID"
    assert_same_instant(scenario.call["due_date"], "2026-10-31T00:00:00Z")

    set_logical_clock(_CLOCK_1130)
    call = schedule_capital_call(
        project_id,
        "CONSTRUCTION_50PCT",
        scheduled_date="2026-11-29T00:00:00Z",
        due_date="2026-12-29T00:00:00Z",
    )

    response = api_client.issue_capital_call(
        call["id"], TEST_USERS["asset_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CALL_BUFFER_TOO_SHORT)
    unchanged = find_capital_call(project_id, call["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["called_amount_cents"] == 0


def test_a_call_starting_exactly_thirty_days_after_the_previous_due_date_issues():
    """PRD §3.5: "the call's `scheduled_date` must be at least 30 days after the
    `due_date` of the most recently `PAID` or `DEFICIENT` capital call of the same
    project; when there is no such prior call the buffer check passes vacuously."

    Design: Difficulty/resource_temporal_overlap/capital_call_buffers_require_thirty_days_after_the_previous_due_date
    """
    scenario = setup_project_with_paid_call()
    project_id = scenario.project["id"]

    set_logical_clock(_CLOCK_1130)
    call = schedule_capital_call(
        project_id,
        "LEASE_UP_50PCT",
        scheduled_date="2026-11-30T00:00:00Z",
        due_date="2026-12-30T00:00:00Z",
    )

    issued = issue_call(call["id"])

    assert issued["status"] == "ISSUED"
    assert issued["called_amount_cents"] > 0

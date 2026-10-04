"""Depth: state machines that loop rather than advance.

Both instances here assert a value returning to a state it already held — the
project cycling through DISTRESSED back to COMPLIANCE_PERIOD, and the
subscription cycling from FULLY_FUNDED back to PARTIALLY_FUNDED and forward
again.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    issue_call,
    read_developer,
    read_fund,
    read_project,
    read_subscription,
    record_payin,
    resolve_review,
    schedule_capital_call,
    set_logical_clock,
    settle_call,
    setup_committed_project,
    setup_project_in_compliance_period,
)

_CLOCK_ISSUE_C1 = "2026-10-05T00:00:00Z"


def _compliance_project():
    """A committed project driven into COMPLIANCE_PERIOD by four PAID calls."""
    return setup_project_in_compliance_period()


def _escalate(project_id):
    """Open a review of period 0 and resolve it into ESCALATED.

    PRD §3.7 bands the score: "a score of 85 or above resolves it from
    `PENDING` to `ESCALATED`".  Occupancy 1.0, DSCR 1.5 and a 30000000-cent
    reserve score 35 + 30 + 20 = 85, the lowest escalatable score.
    """
    review = get_success_data(
        api_client.create_review(
            project_id,
            {
                "review_period_index": 0,
                "review_period_end": "2026-08-31T00:00:00Z",
                "occupancy_pct": 1.0,
                "dscr_observed": 1.5,
                "reserve_balance_cents": 30000000,
            },
            TEST_USERS["compliance_officer_headers"],
        )
    )
    return resolve_review(
        review["id"],
        outcome="ESCALATED",
        headers=TEST_USERS["compliance_officer_headers"],
    )


def _build_refund_scenario(am_headers):
    """Committed project, fully funded subscription, one PAID call at the 0.12 band.

    Riverside Commons is awarded 912345678 credit dollars and 830000000 are
    delivered, so the band is 0.12 and C1 (share 0.20) is called at
    round(105887208 * 1.12) = 118593673. After the call settles in full the
    delivered total is corrected to 500000000, which selects the 0.20 band.
    """
    scenario = setup_committed_project()
    project_id = scenario.project["id"]
    allocation_id = scenario.allocation["id"]

    get_success_data(
        api_client.record_allocation_delivery(
            project_id, allocation_id, 830000000, am_headers
        )
    )

    call = schedule_capital_call(
        project_id,
        "CONSTRUCTION_START",
        scheduled_date="2026-10-01T00:00:00Z",
        due_date="2026-10-31T00:00:00Z",
        milestone_share=0.20,
    )
    set_logical_clock(_CLOCK_ISSUE_C1)
    call = issue_call(call["id"])
    assert call["called_amount_cents"] == 118593673
    call = settle_call(call["id"], call["called_amount_cents"], scenario.investor["id"])

    # Restore the commitment to fully paid before the reclaim, so the cycle
    # under test starts from FULLY_FUNDED.
    subscription = read_subscription(scenario.subscription["id"])
    if subscription["paid_in_cents"] < subscription["committed_cents"]:
        record_payin(
            subscription,
            subscription["committed_cents"] - subscription["paid_in_cents"],
            scenario.investor["id"],
        )
        subscription = read_subscription(scenario.subscription["id"])

    get_success_data(
        api_client.record_allocation_delivery(
            project_id, allocation_id, 500000000, am_headers
        )
    )
    scenario.call = call
    scenario.subscription = subscription
    return scenario


def test_escalated_review_cycles_the_project_into_distressed():
    """PRD §3.7: "Resolving a review into `ESCALATED` stamps `escalated_at` with
    the logical clock, moves the owning project to `DISTRESSED` because an
    escalated review is sufficient on its own, recomputes the owning developer's
    status, and recomputes the owning fund's posture."

    Design: Difficulty/non_linear_state_machine/project_status_revision_cycle_through_distressed_and_back
    """
    scenario = _compliance_project()
    project_id = scenario.project["id"]
    assert read_project(project_id)["status"] == "COMPLIANCE_PERIOD"

    review = _escalate(project_id)

    assert review["status"] == "ESCALATED"
    assert read_project(project_id)["status"] == "DISTRESSED"
    assert read_fund(scenario.fund["id"])["posture"] == "WATCH"
    assert read_developer(scenario.developer["id"])["status"] == "WATCH"


def test_cured_review_returns_the_project_to_compliance_period():
    """PRD §3.7: "A `DISTRESSED` project returns to `COMPLIANCE_PERIOD` once none
    of its reviews remains `ESCALATED`, provided the project had reached
    `COMPLIANCE_PERIOD` before it became distressed."
    PRD §3.7: "Curing moves the review to `CURED`, removes it from the count that
    drives the `FROZEN` condition, recomputes the owning fund's posture, and
    recomputes the developer's status."

    Design: Difficulty/non_linear_state_machine/project_status_revision_cycle_through_distressed_and_back
    """
    scenario = _compliance_project()
    project_id = scenario.project["id"]
    review = _escalate(project_id)
    assert read_project(project_id)["status"] == "DISTRESSED"

    # PRD §3.7: "A `NONCOMPLIANT` review is cured by a `ComplianceOfficer`
    # supplying the `corrected_reserve_balance_cents` recorded with the cure."
    # The reviewed period (ending 2026-08-31) has closed by the scenario's
    # 2027-04-10 clock, so the escalated review can take the noncompliance
    # finding that the cure then clears.
    resolve_review(review["id"], outcome="NONCOMPLIANT")
    cured = resolve_review(
        review["id"],
        outcome="CURED",
        corrected_reserve_balance_cents=60000000,
    )

    assert cured["status"] == "CURED"
    assert read_project(project_id)["status"] == "COMPLIANCE_PERIOD", (
        "the cycle returns the project to the state it held before distress"
    )
    assert read_fund(scenario.fund["id"])["posture"] == "OPEN"
    assert read_developer(scenario.developer["id"])["status"] == "ELIGIBLE"


def test_adjusted_call_knocks_a_fully_funded_subscription_back_down(
    asset_manager_headers,
):
    """PRD §3.5: "Reducing those paid-in amounts moves every `FULLY_FUNDED`
    subscription back to `PARTIALLY_FUNDED` — the cyclic edge that this domain is
    built around — and raises each subscription's `unfunded_commitment_cents`."
    PRD §3.5: "the delta between the new `called_amount_cents` and the recorded
    `settled_amount_cents` is reclaimed from the project's fund: the fund's
    `funded_equity_cents` decreases by that delta, and every subscription of the
    fund has its `paid_in_cents` reduced by that delta."

    The delta is 127064650 - 118593673 = 8470977.

    Design: Difficulty/non_linear_state_machine/fund_subscription_cyclic_refund_and_refund_reversal
    """
    scenario = _build_refund_scenario(asset_manager_headers)
    subscription_before = scenario.subscription
    assert subscription_before["status"] == "FULLY_FUNDED"
    assert subscription_before["paid_in_cents"] == subscription_before["committed_cents"]

    fund_before = read_fund(scenario.fund["id"])
    adjusted = get_success_data(
        api_client.adjust_capital_call(scenario.call["id"], asset_manager_headers)
    )
    delta = adjusted["called_amount_cents"] - scenario.call["settled_amount_cents"]
    assert delta == 8470977

    subscription_after = read_subscription(subscription_before["id"])
    fund_after = read_fund(scenario.fund["id"])

    assert adjusted["status"] == "ADJUSTED"
    assert subscription_after["status"] == "PARTIALLY_FUNDED"
    assert subscription_after["paid_in_cents"] == (
        subscription_before["paid_in_cents"] - delta
    ), "every subscription of the fund has its paid-in amount reduced by the delta"
    assert subscription_after["unfunded_commitment_cents"] == (
        subscription_before["unfunded_commitment_cents"] + delta
    )
    assert fund_after["funded_equity_cents"] == fund_before["funded_equity_cents"] - delta


def test_paying_the_reclaimed_delta_returns_the_subscription_to_fully_funded(
    asset_manager_headers,
):
    """PRD §3.2: "a pay-in that brings `paid_in_cents` to exactly `committed_cents`
    lands it in `FULLY_FUNDED`."

    Design: Difficulty/non_linear_state_machine/fund_subscription_cyclic_refund_and_refund_reversal
    """
    scenario = _build_refund_scenario(asset_manager_headers)
    committed = scenario.subscription["committed_cents"]

    adjusted = get_success_data(
        api_client.adjust_capital_call(scenario.call["id"], asset_manager_headers)
    )
    delta = adjusted["called_amount_cents"] - scenario.call["settled_amount_cents"]
    after_adjust = read_subscription(scenario.subscription["id"])
    assert after_adjust["status"] == "PARTIALLY_FUNDED"

    record_payin(after_adjust, delta, scenario.investor["id"])
    restored = read_subscription(scenario.subscription["id"])

    assert restored["paid_in_cents"] == committed
    assert restored["unfunded_commitment_cents"] == 0
    assert restored["status"] == "FULLY_FUNDED"

"""Backward edges: the cycle's bounded reopen loop and the adjustment's bounded
revision loop, both of which re-enter a status they have already occupied.
"""

from test_helpers.assertions import assert_cycle_money_conserved, assert_cycle_posture
from test_helpers.fixtures import (
    create_adjustment,
    create_forecast,
    read_adjustment,
    read_cycle,
    read_forecast,
    read_plan,
    read_scenario,
    resubmit_adjustment,
    review_adjustment,
    setup_base_fixture,
    setup_selected_scenario_fixture,
    transition_cycle,
)
from test_helpers.test_users import make_executive_sponsor_headers

EXEC = make_executive_sponsor_headers("exec-1")


def test_reopen_re_enters_demand_review_and_advances_the_loop_counter():
    """The one backward edge in the phase machine returns the cycle to the status
    it was created in and increments the bounded loop counter.

    PRD: "An `ExecutiveSponsor` may drive a cycle `EXECUTIVE_REVIEW →
    DEMAND_REVIEW` by naming that `target_status` together with a
    `reopen_reason`, which is mandatory for this transition."

    Design: Difficulty/non_linear_state_machine/cycle_reopen_loop_from_executive_review_back_to_demand_review
    """
    ctx = setup_selected_scenario_fixture()

    before = read_cycle(ctx["cycle"]["id"])
    assert before["residual_gap_cents"] == 5412000
    assert before["selected_closure_cents"] == 3588000
    assert before["reopen_count"] == 0

    reopened = transition_cycle(
        ctx["cycle"]["id"],
        "DEMAND_REVIEW",
        EXEC,
        reopen_reason="Sales withdrew the club channel commitment",
    )

    assert reopened["status"] == "DEMAND_REVIEW"
    assert reopened["reopen_count"] == 1


def test_reopen_cascade_demotes_the_line_stales_the_plan_and_supersedes_the_scenario():
    """Reopening is the widest cascade: the locked line, the plan and the selected
    scenario all move, and the closure money leaves the cycle.

    PRD: "Every forecast line of the cycle in `CONSENSUS_LOCKED` returns to
    `UNDER_CONSENSUS`. Every scenario of the cycle in `SELECTED` transitions to
    `SUPERSEDED` and its `net_gap_closure_cents` leaves `selected_closure_cents`."

    Design: Difficulty/non_linear_state_machine/cycle_reopen_loop_from_executive_review_back_to_demand_review
    """
    ctx = setup_selected_scenario_fixture()

    transition_cycle(
        ctx["cycle"]["id"],
        "DEMAND_REVIEW",
        EXEC,
        reopen_reason="Sales withdrew the club channel commitment",
    )

    forecast = read_forecast(ctx["forecast"]["id"])
    assert forecast["status"] == "UNDER_CONSENSUS"

    plan = read_plan(ctx["plan"]["id"])
    assert plan["status"] == "STALE"
    assert plan["requires_replan"] is True

    scenario = read_scenario(ctx["scenario"]["id"])
    assert scenario["status"] == "SUPERSEDED"
    assert scenario["net_gap_closure_cents"] == 3588000

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 0
    assert cycle["gross_gap_cents"] == 10000000
    assert cycle["selected_closure_cents"] == 0
    assert cycle["residual_gap_cents"] == 10000000
    assert cycle["constrained_plan_count"] == 0
    assert cycle["posture"] == "AT_RISK"
    assert_cycle_money_conserved(cycle)
    assert_cycle_posture(cycle)


def _proposed_adjustment_sent_back_once():
    """One SALES_INTELLIGENCE adjustment of +20 units on a 333-unit baseline that
    has already been returned once with REQUEST_REVISION."""
    ctx = setup_base_fixture(cycle_code="SOP-REV-09", item_overrides={
        "sku": "SKU-BAR-1",
        "unit_price_cents": 500,
        "unit_cost_cents": 200,
    })
    forecast = create_forecast(
        ctx["cycle"]["id"],
        ctx["item"]["id"],
        ctx["customer"]["id"],
        level_units=333,
    )
    adjustment = create_adjustment(
        forecast["id"],
        forecast["version"],
        adjustment_type="SALES_INTELLIGENCE",
        delta_units=20,
        rationale="distribution gain rumour",
    )
    review_adjustment(
        adjustment["id"],
        "REQUEST_REVISION",
        review_note="attach the customer confirmation",
    )
    ctx["forecast"] = forecast
    ctx["adjustment"] = adjustment
    return ctx


def test_two_revision_loops_leave_the_adjustment_proposed_at_round_two():
    """Each resubmission re-enters `PROPOSED` and advances the round counter, and
    the latest quantity replaces the one before it.

    PRD: "Three round trips are therefore available — `revision_round` climbing 0
    to 1 to 2 to 3 — and a fourth resubmission is refused."

    Design: Difficulty/non_linear_state_machine/adjustment_revision_loop_proposed_revision_requested_proposed
    """
    ctx = _proposed_adjustment_sent_back_once()
    adjustment_id = ctx["adjustment"]["id"]
    forecast_id = ctx["forecast"]["id"]

    resubmit_adjustment(
        adjustment_id,
        read_forecast(forecast_id)["version"],
        rationale="confirmation attached",
        delta_units=25,
    )
    review_adjustment(
        adjustment_id, "REQUEST_REVISION", review_note="quantity still unsupported"
    )
    resubmitted = resubmit_adjustment(
        adjustment_id,
        read_forecast(forecast_id)["version"],
        rationale="trimmed to the confirmed volume",
        delta_units=30,
    )

    assert resubmitted["status"] == "PROPOSED"
    assert resubmitted["revision_round"] == 2
    assert resubmitted["delta_units"] == 30
    assert resubmitted["applied_delta_units"] == 30


def test_re_entry_into_proposed_clears_the_reviewer_fields():
    """Coming back into `PROPOSED` wipes the previous verdict, and a looping
    adjustment never reaches the consensus roll-up.

    PRD: "`reviewed_by_user_id` and `review_note` are both cleared back to null, and
    both the adjustment's `version` and the forecast line's `version` increment by 1."

    Design: Difficulty/non_linear_state_machine/adjustment_revision_loop_proposed_revision_requested_proposed
    """
    ctx = _proposed_adjustment_sent_back_once()
    adjustment_id = ctx["adjustment"]["id"]
    forecast_id = ctx["forecast"]["id"]

    resubmit_adjustment(
        adjustment_id,
        read_forecast(forecast_id)["version"],
        rationale="confirmation attached",
        delta_units=25,
    )
    review_adjustment(
        adjustment_id, "REQUEST_REVISION", review_note="quantity still unsupported"
    )
    resubmit_adjustment(
        adjustment_id,
        read_forecast(forecast_id)["version"],
        rationale="trimmed to the confirmed volume",
        delta_units=30,
    )

    adjustment = read_adjustment(adjustment_id)
    assert adjustment["reviewed_by_user_id"] is None
    assert adjustment["review_note"] is None

    forecast = read_forecast(forecast_id)
    assert forecast["consensus_units"] == 333
    assert forecast["endorsed_adjustment_count"] == 0
    assert forecast["status"] == "UNDER_CONSENSUS"

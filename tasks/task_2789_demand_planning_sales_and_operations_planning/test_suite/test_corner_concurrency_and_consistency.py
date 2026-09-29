"""Breadth over the two declared cross-cutting layers: the version tokens that guard
the adjustment and selection writes nothing else would have refused, the cumulative
counters that must not be conflated, and the immediacy of every derived read.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_consensus_adjustment, assert_planning_cycle
from test_helpers.factories import consensus_adjustment_payload, scenario_select_payload
from test_helpers.fixtures import (
    EXEC,
    LEAD,
    PLANNER,
    SUPPLY,
    build_supply_plan,
    create_adjustment,
    create_capacity_block,
    create_capacity_scenario,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    evaluate_scenario,
    read_adjustment,
    read_cycle,
    read_forecast,
    resubmit_adjustment,
    review_adjustment,
    transition_cycle,
    transition_forecast,
)


def test_a_one_behind_forecast_token_is_refused_and_the_refreshed_one_is_accepted():
    """Nothing about the proposal is wrong except the token — the phase admits it, the
    item is mature and the swing is well inside the quarter-baseline ceiling — so the
    identical payload succeeds the moment the client re-reads the line's counter.

    PRD: "Creating a consensus adjustment requires a non-optional
    `expected_demand_forecast_version` field in the request body, carrying the `version`
    of the target `DemandForecast` as the client last observed it. If that value does
    not equal the forecast's current `version`, the create is rejected with
    `ERR_STALE_FORECAST_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/adjustment_create_with_a_stale_forecast_version_returns_412_then_succeeds
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-OCC-FC", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    stale_token = forecast["version"]

    opened = transition_forecast(forecast["id"], "UNDER_CONSENSUS", LEAD)
    assert opened["status"] == "UNDER_CONSENSUS"
    fresh_token = opened["version"]
    assert fresh_token == stale_token + 1

    payload_stale = consensus_adjustment_payload(
        forecast["id"],
        stale_token,
        "SALES_INTELLIGENCE",
        100,
        rationale="written against a one-behind view",
    )
    refused = validate_error(
        api_client.create_consensus_adjustment(payload_stale, PLANNER),
        ApiErrorId.ERR_STALE_FORECAST_VERSION.value,
        412,
    )
    assert refused["error_id"] != ApiErrorId.ERR_CYCLE_PHASE_CLOSED.value
    assert refused["error_id"] != ApiErrorId.ERR_ADJUSTMENT_SWING_EXCEEDED.value

    untouched = read_forecast(forecast["id"])
    assert untouched["version"] == fresh_token
    assert untouched["consensus_units"] == 1000

    empty, empty_meta = validate_paginated(
        api_client.list_consensus_adjustments(
            PLANNER, params={"demand_forecast_id": forecast["id"], "limit": 100}
        )
    )
    assert empty_meta["total_count"] == 0
    assert empty == []

    payload_fresh = consensus_adjustment_payload(
        forecast["id"],
        fresh_token,
        "SALES_INTELLIGENCE",
        100,
        rationale="written against a one-behind view",
    )
    accepted = validate_success(
        api_client.create_consensus_adjustment(payload_fresh, PLANNER), 201
    )
    assert_consensus_adjustment(accepted)
    assert accepted["status"] == "PROPOSED"
    assert accepted["applied_delta_units"] == 100
    assert accepted["revision_round"] == 0


def test_only_the_phase_transitions_move_the_cycle_token_that_selection_checks():
    """A scenario is created and evaluated between two captures of the cycle's counter
    and moves it not at all, so the token from one phase back is exactly one behind and
    the selection is refused until the current one is supplied.

    PRD: "Selecting a scenario requires a non-optional `expected_cycle_version` field in
    the request body, carrying the `version` of the governing `PlanningCycle` as the
    client last observed it. If that value does not equal the cycle's current `version`,
    the selection is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/cycle_version_increments_on_every_transition_and_a_one_behind_token_is_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-OCC-CYCLE", financial_commitment_cents=2000000)
    at_create = cycle["version"]
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)

    at_supply = transition_cycle(cycle["id"], "SUPPLY_REVIEW")["version"]
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    at_scenario = transition_cycle(cycle["id"], "SCENARIO_REVIEW")["version"]
    assert at_supply > at_create
    assert at_scenario > at_supply

    scenario = create_capacity_scenario(cycle["id"], item["id"], 5, name="Buy 5 hours")
    evaluated = evaluate_scenario(scenario["id"])
    assert evaluated["net_gap_closure_cents"] == 287800

    at_executive = transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")["version"]
    assert at_executive == at_scenario + 1

    refused = validate_error(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(at_scenario), EXEC
        ),
        ApiErrorId.ERR_STALE_CYCLE_VERSION.value,
        412,
    )
    assert refused["error_id"] != ApiErrorId.ERR_STALE_FORECAST_VERSION.value
    assert refused["error_id"] != ApiErrorId.ERR_SCENARIO_NOT_SELECTABLE.value

    unchanged = read_cycle(cycle["id"], EXEC)
    assert unchanged["selected_closure_cents"] == 0
    assert unchanged["residual_gap_cents"] == 1100000
    assert unchanged["version"] == at_executive

    selected = validate_success(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(at_executive), EXEC
        ),
        200,
    )
    assert selected["status"] == "SELECTED"

    closed = read_cycle(cycle["id"], EXEC)
    assert closed["selected_closure_cents"] == 287800
    assert closed["residual_gap_cents"] == 812200


def test_an_exhausted_revision_counter_costs_the_cycle_none_of_its_reopen_budget():
    """One adjustment is driven to its third revision and rejected, and the reopen that
    follows spends the cycle's own budget without reviving that row or resetting its
    counter — while a proposal made after the reopen starts its own three rounds afresh.

    PRD: "A proposal is created in `PROPOSED` with `revision_round` at 0,
    `reviewed_by_user_id` and `review_note` both null, and `proposed_by_user_id`
    captured from the acting `X-User-ID`."

    Design: Corner/cross_cutting_complexity_layers/revision_round_and_reopen_count_are_independent_threshold_counters
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-COUNTERS", financial_commitment_cents=0)
    assert cycle["reopen_count"] == 0
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)

    adjustment = create_adjustment(
        forecast["id"], forecast["version"], "SALES_INTELLIGENCE", 100, rationale="round zero"
    )
    assert adjustment["revision_round"] == 0

    for expected_round in (1, 2, 3):
        sent_back = review_adjustment(adjustment["id"], "REQUEST_REVISION", review_note="again")
        assert sent_back["status"] == "REVISION_REQUESTED"
        current = read_forecast(forecast["id"])
        resubmitted = resubmit_adjustment(
            adjustment["id"], current["version"], rationale="round %d" % expected_round
        )
        assert resubmitted["status"] == "PROPOSED"
        assert resubmitted["revision_round"] == expected_round

    rejected = review_adjustment(
        adjustment["id"], "REJECT", review_note="never substantiated"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["revision_round"] == 3

    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")

    reopened = transition_cycle(
        cycle["id"], "DEMAND_REVIEW", EXEC, reopen_reason="sales wants another pass"
    )
    assert_planning_cycle(reopened)
    assert reopened["status"] == "DEMAND_REVIEW"
    assert reopened["reopen_count"] == 1
    assert reopened["reopen_count"] != 2

    survivor = read_adjustment(adjustment["id"])
    assert survivor["revision_round"] == 3
    assert survivor["revision_round"] != 0
    assert survivor["status"] == "REJECTED"

    unlocked = read_forecast(forecast["id"])
    assert unlocked["status"] == "UNDER_CONSENSUS"

    fresh = create_adjustment(
        forecast["id"],
        unlocked["version"],
        "SALES_INTELLIGENCE",
        50,
        rationale="fresh proposal after the reopen",
    )
    assert fresh["revision_round"] == 0
    assert fresh["status"] == "PROPOSED"
    assert fresh["applied_delta_units"] == 50

    rows, meta = validate_paginated(
        api_client.list_consensus_adjustments(
            PLANNER, params={"demand_forecast_id": forecast["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_the_endorsement_response_and_the_next_forecast_read_report_the_same_units():
    """A promotion-driven delta is derived in the create response itself, contributes
    nothing while merely proposed, and lands on the parent line's rolled-up units on the
    very next read of it — no second read and no cycle advance required.

    PRD: "Only adjustments in `ENDORSED` or `COMMITTED` status contribute; rows in
    `PROPOSED`, `REVISION_REQUESTED`, `REJECTED` and `VOIDED` contribute nothing.
    `consensus_units` is the line's `baseline_units` plus the sum of
    `applied_delta_units` over the contributing rows, and `endorsed_adjustment_count` is
    how many rows contributed."

    Design: Corner/consistency_model/endorse_response_and_the_immediate_forecast_read_agree_on_consensus_units
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    promotion = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=10,
        cannibalization_pct=2,
    )
    approved = validate_success(
        api_client.approve_promotion(promotion["id"], LEAD, {}), 200
    )
    assert approved["status"] == "APPROVED"

    cycle = create_cycle(cycle_code="CY-IMMEDIATE", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    assert forecast["baseline_units"] == 1000

    adjustment = create_adjustment(
        forecast["id"],
        forecast["version"],
        "PROMOTION",
        0,
        promotion_id=promotion["id"],
        rationale="approved september promotion",
    )
    assert adjustment["applied_delta_units"] == 80
    assert adjustment["status"] == "PROPOSED"

    before = read_forecast(forecast["id"])
    assert before["status"] == "UNDER_CONSENSUS"
    assert before["consensus_units"] == 1000
    assert before["endorsed_adjustment_count"] == 0

    endorsed = review_adjustment(adjustment["id"], "ENDORSE")
    assert endorsed["status"] == "ENDORSED"
    assert endorsed["applied_delta_units"] == 80

    after = read_forecast(forecast["id"])
    assert after["consensus_units"] == 1080
    assert after["endorsed_adjustment_count"] == 1
    assert after["baseline_units"] == 1000

    reread = read_adjustment(adjustment["id"])
    assert reread["applied_delta_units"] == 80
    assert reread["revision_round"] == 0


def test_the_first_read_after_a_plan_create_already_carries_the_cycles_money():
    """The plan's own create re-runs the cycle roll-up in the same request, so the first
    read afterwards shows all five figures moved from their empty-plan-set values, and a
    second identical read repeats them exactly.

    PRD: "`plan_value_cents` is the sum, over the cycle's supply plans whose status is
    `PLANNED`, `RATIONED` or `COMMITTED`, of each plan's `constrained_units` multiplied
    by that plan's item's `unit_price_cents`; plans in `STALE` are excluded."

    Design: Corner/consistency_model/supply_plan_create_makes_the_cycle_money_visible_on_the_next_read
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-VISIBLE", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)

    advanced = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    assert advanced["plan_value_cents"] == 0
    assert advanced["gross_gap_cents"] == 2000000
    assert advanced["constrained_plan_count"] == 0
    assert advanced["posture"] == "AT_RISK"

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    assert plan["constraint_type"] == "CAPACITY"

    first = read_cycle(cycle["id"], SUPPLY)
    assert first["plan_value_cents"] == 900000
    assert first["gross_gap_cents"] == 1100000
    assert first["residual_gap_cents"] == 1100000
    assert first["constrained_plan_count"] == 1
    assert first["posture"] == "AT_RISK"

    second = read_cycle(cycle["id"], SUPPLY)
    assert second["plan_value_cents"] == first["plan_value_cents"]
    assert second["gross_gap_cents"] == first["gross_gap_cents"]
    assert second["residual_gap_cents"] == first["residual_gap_cents"]
    assert second["constrained_plan_count"] == first["constrained_plan_count"]
    assert second["posture"] == first["posture"]
    assert second["version"] == first["version"]

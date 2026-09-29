"""Breadth over the error catalogue itself: one 404 code per entity type rather than
a shared generic, the single-shot status guards on the scenario verbs, and the two
referential guards that protect the executive hand-off from a neighbouring row.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import cycle_transition_payload, scenario_select_payload
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    LEAD,
    SUPPLY,
    build_supply_plan,
    create_capacity_block,
    create_capacity_scenario,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_price_scenario,
    create_promotion,
    evaluate_scenario,
    read_cycle,
    read_plan,
    read_promotion,
    read_scenario,
    reset_inventory_policy,
    select_scenario,
    set_clock,
    transition_cycle,
)
from test_helpers.test_users import make_executive_sponsor_headers

UNKNOWN_BLOCK_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_FORECAST_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_ADJUSTMENT_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_ALLOCATION_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_SCENARIO_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_RECORD_ID = "00000000-0000-4000-8000-000000000006"


def test_six_unknown_identifiers_answer_with_six_different_not_found_codes():
    """Against a database with no rows at all, six single-row reads share one status
    and nothing else: each names the entity type of the segment that failed to
    resolve, and the empty collections behind them are ordinary successful reads.

    PRD: "the response is the 404 that belongs to that segment's entity type —
    `ERR_CYCLE_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_CAPACITY_BLOCK_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`,
    `ERR_SUPPLY_PLAN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SCENARIO_NOT_FOUND`
    or `ERR_ACCURACY_RECORD_NOT_FOUND` — and no later validation runs."

    Design: Corner/errors/unknown_id_reads_return_the_entity_specific_not_found_code
    """
    reads = (
        (api_client.get_capacity_block(UNKNOWN_BLOCK_ID, ADMIN), ApiErrorId.ERR_CAPACITY_BLOCK_NOT_FOUND),
        (api_client.get_demand_forecast(UNKNOWN_FORECAST_ID, ADMIN), ApiErrorId.ERR_FORECAST_NOT_FOUND),
        (api_client.get_consensus_adjustment(UNKNOWN_ADJUSTMENT_ID, ADMIN), ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND),
        (api_client.get_allocation(UNKNOWN_ALLOCATION_ID, ADMIN), ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api_client.get_scenario(UNKNOWN_SCENARIO_ID, ADMIN), ApiErrorId.ERR_SCENARIO_NOT_FOUND),
        (api_client.get_accuracy_record(UNKNOWN_RECORD_ID, ADMIN), ApiErrorId.ERR_ACCURACY_RECORD_NOT_FOUND),
    )

    reported = []
    for response, expected in reads:
        body = response.json()
        assert body["response_type"] == "error"
        error = validate_error(response, expected.value, 404)
        reported.append(error["error_id"])

    assert len(set(reported)) == 6

    for listing in (
        api_client.list_capacity_blocks(ADMIN, params={"limit": 100}),
        api_client.list_scenarios(ADMIN, params={"limit": 100}),
        api_client.list_accuracy_records(ADMIN, params={"limit": 100}),
    ):
        rows, meta = validate_paginated(listing)
        assert meta["total_count"] == 0
        assert rows == []


def test_both_scenario_verbs_are_single_shot_and_report_where_the_row_now_sits():
    """The same scenario refuses the same two calls for opposite reasons — too far
    along to be evaluated again, not far enough back to be selected again — and the
    refused second selection credits the cycle nothing.

    PRD: "The scenario must be in `EVALUATED` — still `DRAFT`, or already `SELECTED`,
    `SUPERSEDED` or `EXECUTED`, all yield `ERR_SCENARIO_NOT_SELECTABLE`"

    Design: Corner/errors/scenario_status_guards_reject_second_evaluate_and_second_select
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-GUARD", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    assert plan["shortfall_units"] == 430
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")

    scenario = create_capacity_scenario(cycle["id"], item["id"], 5, name="Buy 5 hours")
    evaluated = evaluate_scenario(scenario["id"])
    assert evaluated["status"] == "EVALUATED"
    assert evaluated["net_gap_closure_cents"] == 287800

    repeat_evaluate = validate_error(
        api_client.evaluate_scenario(scenario["id"], SUPPLY, {}),
        ApiErrorId.ERR_SCENARIO_NOT_EVALUATABLE.value,
        409,
    )
    assert repeat_evaluate["error_id"] != ApiErrorId.ERR_CYCLE_PHASE_CLOSED.value

    at_executive = transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")
    selected = select_scenario(scenario["id"], at_executive["version"])
    assert selected["status"] == "SELECTED"
    assert selected["selected_by_user_id"] == "exec-1"
    assert selected["net_gap_closure_cents"] == 287800

    colleague = make_executive_sponsor_headers("exec-2")
    before = read_cycle(cycle["id"], colleague)
    assert before["selected_closure_cents"] == 287800
    assert before["residual_gap_cents"] == 812200

    repeat_select = validate_error(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(before["version"]), colleague
        ),
        ApiErrorId.ERR_SCENARIO_NOT_SELECTABLE.value,
        409,
    )
    assert repeat_select["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    assert repeat_select["error_id"] != ApiErrorId.ERR_STALE_CYCLE_VERSION.value

    after = read_cycle(cycle["id"], colleague)
    assert after["selected_closure_cents"] == 287800
    assert after["selected_closure_cents"] != 575600
    assert after["residual_gap_cents"] == 812200

    unmoved = read_scenario(scenario["id"], colleague)
    assert unmoved["status"] == "SELECTED"
    assert unmoved["selected_by_user_id"] == "exec-1"


def test_re_approving_a_finished_promotion_reports_its_state_not_the_calendar():
    """One clock position, two drafts of the same window: the promotion that already
    went through answers with the state guard while its still-unapproved sibling
    answers with the calendar, proving both rules are live and which one sits higher.

    PRD: "The promotion must currently be in `DRAFT`; one already `APPROVED` or
    already `CANCELLED_RUNOUT` is rejected with `ERR_PROMOTION_NOT_APPROVABLE`."

    Design: Corner/errors/promotion_not_approvable_beats_frozen_horizon_on_a_second_approve
    """
    family = create_family()
    item = create_item(family["id"])
    customer_a = create_customer(customer_code="CUST-A", name="Grocer A")
    customer_b = create_customer(
        customer_code="CUST-B", name="Club B", channel="CLUB", priority_rank=4
    )
    finished = create_promotion(
        item["id"],
        customer_a["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=10,
        cannibalization_pct=2,
    )
    still_draft = create_promotion(
        item["id"],
        customer_b["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=10,
        cannibalization_pct=2,
    )

    approved = validate_success(
        api_client.approve_promotion(finished["id"], LEAD, {}), 200
    )
    assert approved["status"] == "APPROVED"

    moved = set_clock("2026-09-15T00:00:00Z")
    assert moved["current_utc"].startswith("2026-09-15T00:00:00")

    state_guard = validate_error(
        api_client.approve_promotion(finished["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_NOT_APPROVABLE.value,
        409,
    )
    assert state_guard["error_id"] != ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value

    calendar_guard = validate_error(
        api_client.approve_promotion(still_draft["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value,
        422,
    )
    assert calendar_guard["error_id"] != ApiErrorId.ERR_PROMOTION_NOT_APPROVABLE.value
    assert calendar_guard["error_id"] != ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value

    assert read_promotion(finished["id"])["version"] == approved["version"]
    assert read_promotion(still_draft["id"])["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api_client.list_promotions(LEAD, params={"status": "APPROVED", "limit": 100})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == finished["id"]


def test_the_executive_path_is_blocked_first_by_a_draft_then_by_a_stale_plan():
    """Two guards on the same hand-off fire at different hops and neither is about
    the subject row's own status: an unevaluated sibling stops the phase advance, and
    a plan that went stale underneath a perfectly evaluated scenario stops selection.

    PRD: "Advancing the cycle `SCENARIO_REVIEW → EXECUTIVE_REVIEW` requires the cycle
    to be in `SCENARIO_REVIEW` and requires that none of its scenarios is still in
    `DRAFT`; an unevaluated scenario blocks the advance with
    `ERR_UNEVALUATED_SCENARIO`."

    Design: Corner/errors/unevaluated_scenario_then_stale_supply_plan_block_the_executive_path
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-EXECPATH", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")

    capacity = create_capacity_scenario(cycle["id"], item["id"], 5, name="Buy 5 hours")
    capacity = evaluate_scenario(capacity["id"])
    assert capacity["net_gap_closure_cents"] == 287800
    price = create_price_scenario(cycle["id"], 5, name="Raise price five percent")
    assert price["status"] == "DRAFT"

    blocked = validate_error(
        api_client.transition_planning_cycle(
            cycle["id"], cycle_transition_payload("EXECUTIVE_REVIEW"), ADMIN
        ),
        ApiErrorId.ERR_UNEVALUATED_SCENARIO.value,
        422,
    )
    assert blocked["error_id"] != ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value
    assert read_cycle(cycle["id"])["status"] == "SCENARIO_REVIEW"

    price = evaluate_scenario(price["id"])
    assert price["status"] == "EVALUATED"
    advanced = transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")
    assert advanced["status"] == "EXECUTIVE_REVIEW"

    reset = reset_inventory_policy(item["id"], 97.5, 0.20, 30)
    assert reset["safety_stock_units"] == 392
    staled = read_plan(plan["id"])
    assert staled["status"] == "STALE"
    assert staled["requires_replan"] is True

    now = read_cycle(cycle["id"], EXEC)
    assert now["plan_value_cents"] == 0

    refused = validate_error(
        api_client.select_scenario(
            capacity["id"], scenario_select_payload(now["version"]), EXEC
        ),
        ApiErrorId.ERR_STALE_SUPPLY_PLAN.value,
        422,
    )
    assert refused["error_id"] != ApiErrorId.ERR_SCENARIO_NOT_SELECTABLE.value
    assert refused["error_id"] != ApiErrorId.ERR_STALE_CYCLE_VERSION.value

    intact = read_scenario(capacity["id"], EXEC)
    assert intact["status"] == "EVALUATED"
    assert intact["net_gap_closure_cents"] == 287800

    closing = read_cycle(cycle["id"], EXEC)
    assert closing["selected_closure_cents"] == 0
    assert closing["gross_gap_cents"] == 2000000
    assert closing["residual_gap_cents"] == 2000000

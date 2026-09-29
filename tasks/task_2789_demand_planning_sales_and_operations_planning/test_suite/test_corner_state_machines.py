"""State-machine breadth: initial states, the side effects each edge fans out to,
the preconditions guarding an edge, the edges that do not exist, and the lockdown
that terminal states impose.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_allocation, assert_planning_cycle
from test_helpers.factories import (
    adjustment_resubmit_payload,
    adjustment_review_payload,
    cycle_transition_payload,
    demand_forecast_payload,
    item_lifecycle_payload,
    forecast_transition_payload,
    planning_cycle_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    LEAD,
    PLANNER,
    SUPPLY,
    build_supply_plan,
    create_adjustment,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    list_plan_allocations,
    lock_forecast_directly,
    ration_plan,
    read_adjustment,
    read_cycle,
    read_forecast,
    read_item,
    read_plan,
    read_promotion,
    review_adjustment,
    transition_cycle,
    transition_item,
)
from test_helpers.test_users import make_demand_review_lead_headers

SECOND_LEAD = make_demand_review_lead_headers("lead-2")


def test_new_cycle_opens_in_demand_review_with_its_counters_at_zero():
    """The opening status is server-set while the supply-review policy is the one
    thing the client does choose, and the fresh cycle carries no reopen history and
    no publication stamp.

    PRD: "A new cycle opens in `DEMAND_REVIEW` with `reopen_count` at 0,
    `plan_value_cents` at 0 and `constrained_plan_count` at 0, and its
    `published_at` is null"

    Design: Corner/state_machines/planning_cycle_created_in_demand_review_initial_state
    """
    payload = planning_cycle_payload(
        cycle_code="CY-INIT",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
        supply_review_policy="GROSS_CAPACITY_FIRST",
    )
    cycle = validate_success(api_client.create_planning_cycle(payload, ADMIN), 201)
    assert_planning_cycle(cycle)
    assert cycle["status"] == "DEMAND_REVIEW"
    assert cycle["reopen_count"] == 0
    assert cycle["published_at"] is None
    assert cycle["version"] == 1
    assert cycle["supply_review_policy"] == "GROSS_CAPACITY_FIRST"

    _rows, meta = validate_paginated(
        api_client.list_planning_cycles(ADMIN, params={"status": "DEMAND_REVIEW"})
    )
    assert meta["total_count"] == 1


def test_closing_demand_review_locks_both_line_states_and_commits_the_endorsement():
    """One transition sweeps a line that was already under consensus and a line
    that never left baseline, and carrying the endorsement to committed leaves the
    rolled-up consensus exactly where it was.

    PRD: "every forecast line still in `BASELINE` or `UNDER_CONSENSUS` is carried
    to `CONSENSUS_LOCKED`, and every `ENDORSED` adjustment sitting on those lines is
    carried `ENDORSED → COMMITTED` with its `applied_delta_units` untouched"

    Design: Corner/state_machines/cycle_demand_to_supply_review_locks_forecasts_and_commits_endorsements
    """
    family = create_family()
    item = create_item(family["id"])
    customer_one = create_customer()
    customer_two = create_customer(
        customer_code="CUST-TWO", name="Second Club", channel="CLUB", priority_rank=4
    )
    cycle = create_cycle(cycle_code="CY-LOCK", financial_commitment_cents=0)

    line_a = create_forecast(
        cycle["id"], item["id"], customer_one["id"], level_units=1000
    )
    line_b = create_forecast(
        cycle["id"], item["id"], customer_two["id"], level_units=400
    )
    adjustment = create_adjustment(
        line_a["id"],
        line_a["version"],
        adjustment_type="SALES_INTELLIGENCE",
        delta_units=100,
        rationale="incremental door count",
    )
    review_adjustment(adjustment["id"], "ENDORSE")

    advanced = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    assert advanced["status"] == "SUPPLY_REVIEW"

    reread_a = read_forecast(line_a["id"])
    assert reread_a["status"] == "CONSENSUS_LOCKED"
    assert reread_a["consensus_units"] == 1100
    assert reread_a["endorsed_adjustment_count"] == 1

    reread_b = read_forecast(line_b["id"])
    assert reread_b["status"] == "CONSENSUS_LOCKED"
    assert reread_b["consensus_units"] == 400
    assert reread_b["consensus_units"] == reread_b["baseline_units"]

    committed = read_adjustment(adjustment["id"])
    assert committed["status"] == "COMMITTED"
    assert committed["applied_delta_units"] == 100

    reread_cycle = read_cycle(cycle["id"])
    assert reread_cycle["plan_value_cents"] == 0
    assert reread_cycle["residual_gap_cents"] == 0
    assert reread_cycle["posture"] == "GREEN"


def test_demand_review_cannot_close_over_an_unreviewed_proposal():
    """A single proposal still awaiting a verdict blocks the advance, the refusal
    leaves nothing half-locked, and once the proposal has been rejected the
    identical advance goes through.

    PRD: "no adjustment attached to any of the cycle's forecast lines may be in
    `PROPOSED` or `REVISION_REQUESTED`, or the advance is rejected with
    `ERR_OPEN_ADJUSTMENTS`."

    Design: Corner/state_machines/cycle_advance_with_open_adjustment_rejected_with_open_adjustments
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-OPEN", financial_commitment_cents=0)
    line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    adjustment = create_adjustment(
        line["id"],
        line["version"],
        adjustment_type="SALES_INTELLIGENCE",
        delta_units=100,
        rationale="awaiting review",
    )

    validate_error(
        api_client.transition_planning_cycle(
            cycle["id"], cycle_transition_payload("SUPPLY_REVIEW"), ADMIN
        ),
        ApiErrorId.ERR_OPEN_ADJUSTMENTS.value,
        422,
    )
    assert read_cycle(cycle["id"])["status"] == "DEMAND_REVIEW"
    assert read_forecast(line["id"])["status"] == "UNDER_CONSENSUS"

    review_adjustment(adjustment["id"], "REJECT", review_note="not substantiated")
    assert read_adjustment(adjustment["id"])["status"] == "REJECTED"
    assert read_forecast(line["id"])["consensus_units"] == 1000

    advanced = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    assert advanced["status"] == "SUPPLY_REVIEW"
    assert read_forecast(line["id"])["status"] == "CONSENSUS_LOCKED"


def test_publication_is_refused_while_the_residual_gap_is_still_positive():
    """The gap check lives only on the publication edge, so the cycle reaches the
    executive phase legally and is stopped there.

    PRD: "`residual_gap_cents` must be zero or negative, and publishing a cycle
    whose residual gap is still greater than zero is rejected with
    `ERR_UNCLOSED_GAP`."

    Design: Corner/state_machines/cycle_publish_with_positive_residual_gap_rejected_with_unclosed_gap
    """
    cycle = create_cycle(cycle_code="CY-GAP", financial_commitment_cents=5000000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")

    validate_error(
        api_client.transition_planning_cycle(
            cycle["id"], cycle_transition_payload("PUBLISHED"), EXEC
        ),
        ApiErrorId.ERR_UNCLOSED_GAP.value,
        422,
    )

    reread = read_cycle(cycle["id"])
    assert reread["status"] == "EXECUTIVE_REVIEW"
    assert reread["published_at"] is None
    assert reread["posture"] == "AT_RISK"
    assert reread["plan_value_cents"] == 0
    assert reread["gross_gap_cents"] == 5000000
    assert reread["selected_closure_cents"] == 0
    assert reread["residual_gap_cents"] == 5000000


def test_demand_review_declares_only_one_outgoing_edge():
    """Jumping to the executive phase, jumping to publication and looping back onto
    the current status are all unreachable targets, and three refusals move nothing.

    PRD: "Any `target_status` that is not reachable from the cycle's present status
    is rejected with `ERR_CYCLE_TRANSITION_INVALID`."

    Design: Corner/state_machines/cycle_cannot_skip_demand_review_straight_to_executive_review
    """
    cycle = create_cycle(cycle_code="CY-SKIP", financial_commitment_cents=0)

    for payload, headers in (
        (cycle_transition_payload("EXECUTIVE_REVIEW"), ADMIN),
        (cycle_transition_payload("PUBLISHED"), EXEC),
        (
            cycle_transition_payload(
                "DEMAND_REVIEW", reopen_reason="self loop attempt"
            ),
            EXEC,
        ),
    ):
        validate_error(
            api_client.transition_planning_cycle(cycle["id"], payload, headers),
            ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value,
            409,
        )

    reread = read_cycle(cycle["id"])
    assert reread["status"] == "DEMAND_REVIEW"
    assert reread["reopen_count"] == 0
    assert reread["version"] == 1


def test_a_published_cycle_locks_down_along_two_separate_axes():
    """The terminal status kills every further cycle transition, while the frozen
    posture that publication produces kills the child write with its own error.

    PRD: "`PUBLISHED` is terminal, and the resulting `FROZEN` posture blocks every
    subsequent cycle-scoped child mutation with `ERR_CYCLE_FROZEN`."

    Design: Corner/state_machines/published_cycle_rejects_every_further_transition
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-TERM", financial_commitment_cents=0)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")
    published = transition_cycle(cycle["id"], "PUBLISHED", EXEC)

    assert published["status"] == "PUBLISHED"
    assert published["posture"] == "FROZEN"
    assert published["published_at"].startswith("2026-08-01T00:00:00")

    validate_error(
        api_client.transition_planning_cycle(
            cycle["id"],
            cycle_transition_payload(
                "DEMAND_REVIEW", reopen_reason="post-publication rework"
            ),
            EXEC,
        ),
        ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value,
        409,
    )
    validate_error(
        api_client.transition_planning_cycle(
            cycle["id"], cycle_transition_payload("SUPPLY_REVIEW"), ADMIN
        ),
        ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value,
        409,
    )
    validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(
                cycle["id"], item["id"], customer["id"], level_units=500
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_CYCLE_FROZEN.value,
        409,
    )

    assert read_cycle(cycle["id"])["version"] == published["version"]


def test_rationing_a_plan_a_second_time_is_refused_rather_than_replayed():
    """Replaying the waterfall would duplicate the allocation row or double-spend
    the leftover, so the second call is refused and the conserved identity reads
    exactly as it did before.

    PRD: "The plan must currently be in `PLANNED` — one already `RATIONED`, `STALE`
    or `COMMITTED` is rejected with `ERR_SUPPLY_PLAN_NOT_RATIONABLE`"

    Design: Corner/state_machines/second_ration_of_the_same_supply_plan_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-IDEM", financial_commitment_cents=0)
    line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    lock_forecast_directly(line["id"])
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    rationed = ration_plan(plan["id"])

    assert rationed["status"] == "RATIONED"
    assert rationed["constrained_units"] == 900
    assert rationed["unallocated_units"] == 0
    rows = list_plan_allocations(plan["id"])
    assert len(rows) == 1
    assert_allocation(rows[0])
    assert rows[0]["allocated_units"] == 900
    assert float(rows[0]["fill_rate_pct"]) == 90.00
    assert rows[0]["allocation_pass"] == "PRO_RATA"

    validate_error(
        api_client.ration_supply_plan(plan["id"], SUPPLY, {}),
        ApiErrorId.ERR_SUPPLY_PLAN_NOT_RATIONABLE.value,
        409,
    )

    _rows, meta = validate_paginated(
        api_client.list_allocations(SUPPLY, params={"supply_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1
    after = read_plan(plan["id"])
    assert after["unallocated_units"] == 0
    assert after["version"] == rationed["version"]


def _prelaunch_npi_fixture(cycle_code, endorse):
    """A PRELAUNCH item with one forecast line, one NEW_ITEM_PLAN adjustment of
    +100 and one DRAFT promotion for a month outside the cycle horizon."""
    family = create_family()
    item = create_item(
        family["id"], sku="SKU-NPI", npi_ramp_pct=100, lifecycle_state="PRELAUNCH"
    )
    customer = create_customer()
    cycle = create_cycle(cycle_code=cycle_code, financial_commitment_cents=0)
    line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    promotion = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-10",
        end_month="2026-10",
        lift_pct=10,
        cannibalization_pct=2,
    )
    adjustment = create_adjustment(
        line["id"],
        line["version"],
        adjustment_type="NEW_ITEM_PLAN",
        delta_units=100,
        rationale="launch pipeline fill",
    )
    if endorse:
        review_adjustment(adjustment["id"], "ENDORSE")
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "cycle": cycle,
        "forecast": line,
        "promotion": promotion,
        "adjustment": adjustment,
    }


def test_cancelling_a_new_item_truncates_every_month_and_voids_its_plans():
    """Cancellation has no month boundary to compare against: the adjustment is
    voided, the line is truncated with its baseline preserved, and the promotion is
    cancelled even though its window sits outside the horizon.

    PRD: "**every** month of the horizon, not merely months past some boundary"

    Design: Corner/state_machines/item_prelaunch_to_cancelled_npi_truncates_forecasts_and_voids_new_item_plans
    """
    ctx = _prelaunch_npi_fixture("CY-NPI", endorse=True)

    before = read_forecast(ctx["forecast"]["id"])
    assert before["method"] == "ANALOG_PROFILE"
    assert before["baseline_units"] == 1000
    assert before["consensus_units"] == 1100
    assert before["endorsed_adjustment_count"] == 1

    cancelled = transition_item(ctx["item"]["id"], "CANCELLED_NPI", ADMIN)
    assert cancelled["lifecycle_state"] == "CANCELLED_NPI"

    adjustment = read_adjustment(ctx["adjustment"]["id"])
    assert adjustment["status"] == "VOIDED"
    assert adjustment["applied_delta_units"] == 0

    line = read_forecast(ctx["forecast"]["id"])
    assert line["status"] == "RUNOUT_TRUNCATED"
    assert line["consensus_units"] == 0
    assert line["endorsed_adjustment_count"] == 0
    assert line["baseline_units"] == 1000

    assert read_promotion(ctx["promotion"]["id"])["status"] == "CANCELLED_RUNOUT"

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 0
    assert cycle["posture"] == "GREEN"


def test_launching_a_new_item_disturbs_none_of_its_children():
    """The other branch of the same fork has an empty side-effect set: from
    byte-identical prior state the line, the proposal and the promotion all stand
    untouched, and only the item's own version moves.

    PRD: "beyond the item's own `version` bump it touches nothing else at all — no
    forecast, no adjustment, no promotion is disturbed."

    Design: Corner/state_machines/item_prelaunch_to_ramp_touches_no_other_entity
    """
    ctx = _prelaunch_npi_fixture("CY-RAMP", endorse=False)
    before_line = read_forecast(ctx["forecast"]["id"])

    ramped = transition_item(ctx["item"]["id"], "RAMP", ADMIN)
    assert ramped["lifecycle_state"] == "RAMP"

    line = read_forecast(ctx["forecast"]["id"])
    assert line["status"] == "UNDER_CONSENSUS"
    assert line["consensus_units"] == 1000
    assert line["endorsed_adjustment_count"] == 0
    assert line["version"] == before_line["version"]

    adjustment = read_adjustment(ctx["adjustment"]["id"])
    assert adjustment["status"] == "PROPOSED"
    assert adjustment["applied_delta_units"] == 100

    assert read_promotion(ctx["promotion"]["id"])["status"] == "DRAFT"

    approved = validate_success(
        api_client.approve_promotion(ctx["promotion"]["id"], LEAD, {}), 200
    )
    assert approved["status"] == "APPROVED"


def test_discontinuation_needs_the_inventory_at_exactly_zero():
    """Two siblings identical but for their inventory position diverge on the same
    request, because the tolerance is not a band.

    PRD: "Zero passes, one fails."

    Design: Corner/state_machines/item_runout_to_discontinued_rejected_while_on_hand_units_remain
    """
    family = create_family()
    residual = create_item(family["id"], sku="SKU-RESIDUAL", on_hand_units=5)
    clean = create_item(family["id"], sku="SKU-CLEAN", on_hand_units=0)
    transition_item(residual["id"], "RUNOUT", ADMIN, runout_end_month="2026-09")
    transition_item(clean["id"], "RUNOUT", ADMIN, runout_end_month="2026-09")

    validate_error(
        api_client.transition_item_lifecycle(
            residual["id"], item_lifecycle_payload("DISCONTINUED"), ADMIN
        ),
        ApiErrorId.ERR_RUNOUT_INVENTORY_REMAINS.value,
        422,
    )
    assert read_item(residual["id"])["lifecycle_state"] == "RUNOUT"

    discontinued = transition_item(clean["id"], "DISCONTINUED", ADMIN)
    assert discontinued["lifecycle_state"] == "DISCONTINUED"

    for item_id in (residual["id"], clean["id"]):
        reread = read_item(item_id)
        assert reread["runout_end_month"] == "2026-09"
        assert reread["successor_item_id"] is None


def test_a_cancelled_new_item_has_no_outgoing_lifecycle_edge_left():
    """Even the launch edge that existed one request earlier is gone once the item
    has been cancelled, and no refused attempt bumps the version.

    PRD: "including any attempt to move out of the terminal `DISCONTINUED` or
    `CANCELLED_NPI` states — is rejected with
    `ERR_ITEM_LIFECYCLE_TRANSITION_INVALID`."

    Design: Corner/state_machines/cancelled_npi_item_rejects_further_lifecycle_transitions
    """
    family = create_family()
    item = create_item(family["id"], sku="SKU-DEAD", lifecycle_state="PRELAUNCH")
    cancelled = transition_item(item["id"], "CANCELLED_NPI", ADMIN)

    for target in ("RAMP", "MATURE", "DISCONTINUED"):
        validate_error(
            api_client.transition_item_lifecycle(
                item["id"], item_lifecycle_payload(target), ADMIN
            ),
            ApiErrorId.ERR_ITEM_LIFECYCLE_TRANSITION_INVALID.value,
            409,
        )

    reread = read_item(item["id"])
    assert reread["lifecycle_state"] == "CANCELLED_NPI"
    assert reread["version"] == cancelled["version"]


def test_a_rejected_adjustment_cannot_be_reviewed_or_resubmitted_again():
    """Rejection is final: a second reviewer cannot endorse the row, the proposer
    cannot resubmit it, and the volume it asked for never entered the roll-up.

    PRD: "All three decisions require the adjustment to currently be in `PROPOSED`
    — anything else, whether already endorsed, rejected, committed, voided or
    awaiting revision, is rejected with `ERR_ADJUSTMENT_NOT_REVIEWABLE`"

    Design: Corner/state_machines/adjustment_reject_is_terminal_and_second_review_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-REJ", financial_commitment_cents=0)
    line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    adjustment = create_adjustment(
        line["id"],
        line["version"],
        adjustment_type="SALES_INTELLIGENCE",
        delta_units=100,
        rationale="unverified rumour",
    )
    rejected = review_adjustment(
        adjustment["id"], "REJECT", review_note="no evidence"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reviewed_by_user_id"] == "lead-1"
    # PRD 3.4 names review_note storage only on the REQUEST_REVISION branch
    # ("REQUEST_REVISION ... stores the supplied review_note"); the REJECT
    # branch is silent on it, so no assertion is made here.
    current_version = read_forecast(line["id"])["version"]

    validate_error(
        api_client.review_consensus_adjustment(
            adjustment["id"], adjustment_review_payload("ENDORSE"), SECOND_LEAD
        ),
        ApiErrorId.ERR_ADJUSTMENT_NOT_REVIEWABLE.value,
        409,
    )
    validate_error(
        api_client.resubmit_consensus_adjustment(
            adjustment["id"],
            adjustment_resubmit_payload(
                current_version,
                rationale="found the evidence",
                delta_units=100,
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_ADJUSTMENT_NOT_RESUBMITTABLE.value,
        409,
    )

    reread = read_adjustment(adjustment["id"])
    assert reread["version"] == rejected["version"]
    assert reread["revision_round"] == 0

    reread_line = read_forecast(line["id"])
    assert reread_line["consensus_units"] == 1000
    assert reread_line["endorsed_adjustment_count"] == 0


def test_publication_commits_the_plan_and_keeps_it_inside_the_plan_value():
    """The cycle's own transition drags its plan to committed, and because that
    status stays inside the valuation the plan value survives the publish while the
    posture flips regardless of the money verdict.

    PRD: "every supply plan of the cycle in `PLANNED` or `RATIONED` transitions to
    `COMMITTED`"

    Design: Corner/state_machines/cycle_publish_commits_supply_plans_and_freezes_posture
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=14)
    cycle = create_cycle(cycle_code="CY-PUB", financial_commitment_cents=0)
    line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    lock_forecast_directly(line["id"])
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")

    assert plan["available_units"] == 1400
    assert plan["demand_side_units"] == 1330
    assert plan["constrained_units"] == 1330
    assert plan["shortfall_units"] == 0
    assert plan["constraint_type"] == "NONE"
    assert plan["status"] == "PLANNED"
    before = read_cycle(cycle["id"])
    assert before["plan_value_cents"] == 1330000
    assert before["gross_gap_cents"] == -1330000
    assert before["residual_gap_cents"] == -1330000
    assert before["constrained_plan_count"] == 0
    assert before["posture"] == "GREEN"

    published = transition_cycle(cycle["id"], "PUBLISHED", EXEC)
    assert published["status"] == "PUBLISHED"

    committed = read_plan(plan["id"])
    assert committed["status"] == "COMMITTED"
    assert committed["requires_replan"] is False

    after = read_cycle(cycle["id"])
    assert after["plan_value_cents"] == 1330000
    assert after["posture"] == "FROZEN"
    assert after["published_at"].startswith("2026-08-01T00:00:00")
    assert after["constrained_plan_count"] == 0


def test_a_truncated_line_can_never_be_moved_back_into_the_workflow():
    """Truncation is permanent: neither reopening the line nor re-locking it is a
    declared edge, so the zeroed consensus cannot be resurrected by a workflow move.

    PRD: "including any attempt to leave the terminal `RUNOUT_TRUNCATED` — is
    rejected with `ERR_FORECAST_TRANSITION_INVALID`."

    Design: Corner/state_machines/runout_truncated_forecast_rejects_relock_transition
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(
        cycle_code="CY-TRUNC",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
    )
    line = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-11", level_units=1000
    )
    lock_forecast_directly(line["id"])
    transition_item(item["id"], "RUNOUT", ADMIN, runout_end_month="2026-09")

    truncated = read_forecast(line["id"])
    assert truncated["status"] == "RUNOUT_TRUNCATED"
    assert truncated["consensus_units"] == 0
    assert truncated["baseline_units"] == 1000
    reread_item = read_item(item["id"])
    assert reread_item["lifecycle_state"] == "RUNOUT"
    assert reread_item["runout_end_month"] == "2026-09"

    validate_error(
        api_client.transition_demand_forecast(
            line["id"], forecast_transition_payload("UNDER_CONSENSUS"), PLANNER
        ),
        ApiErrorId.ERR_FORECAST_TRANSITION_INVALID.value,
        409,
    )
    validate_error(
        api_client.transition_demand_forecast(
            line["id"], forecast_transition_payload("CONSENSUS_LOCKED"), LEAD
        ),
        ApiErrorId.ERR_FORECAST_TRANSITION_INVALID.value,
        409,
    )
    assert read_forecast(line["id"])["consensus_units"] == 0

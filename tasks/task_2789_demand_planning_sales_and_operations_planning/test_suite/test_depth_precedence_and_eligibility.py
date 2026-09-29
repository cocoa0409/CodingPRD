"""Rejection precedence: which of two simultaneously violated rules is reported,
and the cross-entity eligibility gates that are checked before any arithmetic.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    consensus_adjustment_payload,
    supply_plan_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    LEAD,
    PLANNER,
    SUPPLY,
    approve_promotion,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    lock_forecast,
    read_cycle,
    read_forecast,
    read_item,
    read_promotion,
    setup_base_fixture,
    transition_cycle,
    transition_forecast,
    transition_item,
)


def _swing_conflict_fixture():
    """A 333-unit baseline line in a DEMAND_REVIEW cycle. A quarter of 333 rounds
    to 83 units, so a 5000-unit delta breaks the fiscal guardrail on its own."""
    ctx = setup_base_fixture(
        cycle_code="SOP-CONF-09",
        item_overrides={
            "sku": "SKU-BAR-9",
            "unit_price_cents": 500,
            "unit_cost_cents": 200,
        },
        customer_overrides={"customer_code": "CUST-A", "name": "Alpha Grocery"},
        family_overrides={"family_code": "FAM-CANDY", "name": "Confections"},
    )
    ctx["forecast"] = create_forecast(
        ctx["cycle"]["id"],
        ctx["item"]["id"],
        ctx["customer"]["id"],
        level_units=333,
    )
    return ctx


def test_oversized_delta_alone_is_reported_as_the_fiscal_guardrail():
    """The control call: only the swing guardrail is broken, so that is the error
    that surfaces.

    PRD: "A delta exactly equal to that ceiling is accepted; one unit beyond it is
    rejected with `ERR_ADJUSTMENT_SWING_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_phase_actor_beats_adjustment_swing_exceeded
    """
    ctx = _swing_conflict_fixture()
    forecast = ctx["forecast"]

    payload = consensus_adjustment_payload(
        forecast["id"],
        forecast["version"],
        "SALES_INTELLIGENCE",
        5000,
        rationale="control call: only the fiscal guardrail is violated",
    )
    response = api_client.create_consensus_adjustment(payload, PLANNER)
    validate_error(response, ApiErrorId.ERR_ADJUSTMENT_SWING_EXCEEDED.value, 422)


def test_phase_actor_outranks_the_fiscal_guardrail_on_the_same_request():
    """With the cycle moved past demand review, the phase-actor check sits far
    above the financial guardrails in the ladder and claims the rejection.

    PRD: "**Financial guardrails**, evaluated last because they depend on the
    arithmetic of the calculations in §3"

    Design: Difficulty/priority_pair_validation_conflict/cycle_phase_actor_beats_adjustment_swing_exceeded
    """
    ctx = _swing_conflict_fixture()
    forecast = ctx["forecast"]
    transition_cycle(ctx["cycle"]["id"], "SUPPLY_REVIEW")
    # PRD 3.5: the DEMAND_REVIEW -> SUPPLY_REVIEW advance sweeps "every forecast
    # line still in BASELINE or UNDER_CONSENSUS ... to CONSENSUS_LOCKED", freezing
    # consensus_units at its then-current rolled-up value.
    swept = read_forecast(forecast["id"])
    assert swept["status"] == "CONSENSUS_LOCKED"
    assert swept["consensus_units"] == 333

    payload = consensus_adjustment_payload(
        forecast["id"],
        forecast["version"],
        "SALES_INTELLIGENCE",
        5000,
        rationale="conflict call: fiscal guardrail AND phase actor both violated",
    )
    response = api_client.create_consensus_adjustment(payload, PLANNER)
    error = validate_error(
        response, ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value, 403
    )
    assert error["error_id"] != ApiErrorId.ERR_ADJUSTMENT_SWING_EXCEEDED.value
    assert error["error_id"] != ApiErrorId.ERR_CYCLE_PHASE_CLOSED.value

    listing = api_client.list_consensus_adjustments(
        PLANNER, params={"demand_forecast_id": forecast["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []

    # The refused create wrote nothing: the line is byte-for-byte where the sweep
    # left it, with no further version bump.
    reread = read_forecast(forecast["id"])
    assert reread["status"] == swept["status"]
    assert reread["consensus_units"] == swept["consensus_units"]
    assert reread["version"] == swept["version"]


def _promotion_overlap_fixture():
    """A MATURE item with one APPROVED promotion over 2026-10..2026-12 and two
    DRAFT promotions that both share months with it."""
    family = create_family(family_code="FAM-SAUCE", name="Sauces")
    item = create_item(
        family["id"], sku="SKU-KETCH-1", unit_price_cents=400, unit_cost_cents=150
    )
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    base = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-10",
        end_month="2026-12",
        lift_pct=10,
        cannibalization_pct=2,
    )
    base = approve_promotion(base["id"])
    conflict = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-11",
        end_month="2027-01",
        lift_pct=15,
        cannibalization_pct=3,
    )
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "base": base,
        "conflict": conflict,
    }


def test_window_overlap_alone_is_reported_as_the_calendar_conflict():
    """The control call: the item is still promotable, so the shared month is the
    only violation and the interval check reports it.

    PRD: "sharing even a single month is an overlap and yields
    `ERR_PROMOTION_WINDOW_OVERLAP`"

    Design: Difficulty/priority_pair_validation_conflict/item_not_promotable_beats_promotion_window_overlap
    """
    ctx = _promotion_overlap_fixture()

    control = create_promotion(
        ctx["item"]["id"],
        ctx["customer"]["id"],
        start_month="2026-11",
        end_month="2026-11",
        lift_pct=5,
        cannibalization_pct=1,
    )
    response = api_client.approve_promotion(control["id"], LEAD, {})
    validate_error(response, ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value, 409)
    assert read_promotion(control["id"])["status"] == "DRAFT"


def test_item_not_promotable_outranks_the_window_overlap():
    """Cross-entity eligibility is checked before any calendar arithmetic, so once
    the item has left the sellable states the overlap is never reached.

    PRD: "**Cross-entity referential eligibility**, checked before any temporal or
    capacity arithmetic"

    Design: Difficulty/priority_pair_validation_conflict/item_not_promotable_beats_promotion_window_overlap
    """
    ctx = _promotion_overlap_fixture()

    item = transition_item(ctx["item"]["id"], "RUNOUT", runout_end_month="2026-12")
    assert item["lifecycle_state"] == "RUNOUT"
    assert read_promotion(ctx["base"]["id"])["status"] == "APPROVED"

    response = api_client.approve_promotion(ctx["conflict"]["id"], LEAD, {})
    error = validate_error(response, ApiErrorId.ERR_ITEM_NOT_PROMOTABLE.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value
    assert read_promotion(ctx["conflict"]["id"])["status"] == "DRAFT"


def _unsettled_demand_side_cycle():
    """A cycle in SUPPLY_REVIEW holding a locked line for `sibling` and no line at
    all for `item`, so a plan for `item` violates PRD 3.5's demand-side
    precondition.

    The empty-line-set branch is the reachable one. An UNDER_CONSENSUS line cannot
    coexist with a SUPPLY_REVIEW cycle, because the DEMAND_REVIEW -> SUPPLY_REVIEW
    advance sweeps "every forecast line still in BASELINE or UNDER_CONSENSUS ... to
    CONSENSUS_LOCKED" (PRD 3.5) and forecast transitions are barred once the cycle
    has left DEMAND_REVIEW (PRD 2.8).
    """
    family = create_family(family_code="FAM-PAPER", name="Paper Goods")
    item = create_item(
        family["id"], sku="SKU-TOWEL-1", unit_price_cents=900, unit_cost_cents=300
    )
    sibling = create_item(
        family["id"], sku="SKU-TOWEL-2", unit_price_cents=900, unit_cost_cents=300
    )
    customer_a = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="SOP-LOCK-09", financial_commitment_cents=0)
    sibling_line = create_forecast(
        cycle["id"], sibling["id"], customer_a["id"], level_units=600
    )
    lock_forecast(sibling_line["id"])
    cycle = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    return {
        "family": family,
        "item": item,
        "sibling": sibling,
        "cycle": cycle,
        "sibling_line": sibling_line,
    }


def test_rejected_supply_plan_create_writes_nothing():
    """The refused create leaves no plan behind, moves no line and leaves the
    cycle's money at its pre-plan values.

    PRD: "at least one forecast line must exist for that cycle-and-item pair, and
    every such line must be in either `CONSENSUS_LOCKED` or `RUNOUT_TRUNCATED`."

    Design: Difficulty/cross_entity_state_dependency/supply_plan_create_requires_all_forecasts_consensus_locked
    """
    ctx = _unsettled_demand_side_cycle()

    validate_error(
        api_client.create_supply_plan(
            supply_plan_payload(ctx["cycle"]["id"], ctx["item"]["id"]), SUPPLY
        ),
        ApiErrorId.ERR_FORECAST_NOT_LOCKED.value,
        422,
    )

    listing = api_client.list_supply_plans(
        SUPPLY, params={"cycle_id": ctx["cycle"]["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []

    assert read_forecast(ctx["sibling_line"]["id"])["status"] == "CONSENSUS_LOCKED"

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 0
    assert cycle["constrained_plan_count"] == 0


def _prelaunch_promotion_fixture():
    family = create_family(family_code="FAM-NPI", name="New Ventures")
    item = create_item(
        family["id"],
        sku="SKU-NEW-1",
        unit_price_cents=700,
        unit_cost_cents=250,
        avg_monthly_demand_units=500,
        lifecycle_state="PRELAUNCH",
    )
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    promotion = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-10",
        end_month="2026-10",
        lift_pct=20,
        cannibalization_pct=0,
    )
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "promotion": promotion,
    }


def test_promotion_approve_rejects_a_prelaunch_item():
    """Approval requires a sellable item, and a product that has not launched is
    not one.

    PRD: "The promoted item must be sellable, meaning its `lifecycle_state` is
    either `RAMP` or `MATURE`"

    Design: Difficulty/cross_entity_state_dependency/promotion_approve_requires_item_lifecycle_ramp_or_mature
    """
    ctx = _prelaunch_promotion_fixture()

    response = api_client.approve_promotion(ctx["promotion"]["id"], LEAD, {})
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_PROMOTABLE.value, 422)
    assert read_promotion(ctx["promotion"]["id"])["status"] == "DRAFT"


def test_promotion_approve_succeeds_once_the_item_has_ramped():
    """Launching the item is what changes the eligibility, and the identical
    approval then goes through.

    PRD: "What it changes is eligibility: a `RAMP` item is promotable, which is
    what a promotion approval requires."

    Design: Difficulty/cross_entity_state_dependency/promotion_approve_requires_item_lifecycle_ramp_or_mature
    """
    ctx = _prelaunch_promotion_fixture()

    api_client.approve_promotion(ctx["promotion"]["id"], LEAD, {})

    ramped = transition_item(ctx["item"]["id"], "RAMP", ADMIN)
    assert ramped["lifecycle_state"] == "RAMP"
    assert read_item(ctx["item"]["id"])["lifecycle_state"] == "RAMP"

    response = api_client.approve_promotion(ctx["promotion"]["id"], LEAD, {})
    approved = validate_success(response, 200)
    assert approved["status"] == "APPROVED"

"""Composite setup builders.

Every helper here drives the real HTTP surface with PRD-declared endpoints only
and unwraps each response with ``get_success_data`` so that a broken precondition
surfaces as a clear setup failure rather than a confusing assertion error later.

The low-level wrappers cover the single-POST cases; the ``setup_*`` builders
assemble the recurring multi-entity chains (locked forecast lines, rationed
supply plans, published cycles, evaluated scenarios) that the test suite reuses.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accuracy_record_payload,
    adjustment_resubmit_payload,
    adjustment_review_payload,
    capacity_block_payload,
    capacity_investment_scenario_payload,
    clock_payload,
    consensus_adjustment_payload,
    customer_payload,
    cycle_transition_payload,
    demand_forecast_payload,
    forecast_transition_payload,
    inventory_policy_payload,
    item_lifecycle_payload,
    item_payload,
    mature_item_payload,
    planning_cycle_payload,
    price_realization_scenario_payload,
    product_family_payload,
    promotion_payload,
    scenario_select_payload,
    supply_plan_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["sop_admin_headers"]
PLANNER = TEST_USERS["demand_planner_headers"]
LEAD = TEST_USERS["demand_review_lead_headers"]
SUPPLY = TEST_USERS["supply_planner_headers"]
EXEC = TEST_USERS["executive_sponsor_headers"]


# ---------------------------------------------------------------------------
# Low-level single-call wrappers
# ---------------------------------------------------------------------------


def create_family(**overrides) -> dict:
    """One ProductFamily. Defaults to FAM-BASE at 100 units/hour, 800 max hours."""
    payload = product_family_payload(**overrides)
    return get_success_data(api_client.create_product_family(payload, ADMIN), 201)


def create_item(family_id: str, **overrides) -> dict:
    """One Item with the recurring MATURE 95.0 / 0.20 / 30 policy triple, which
    yields safety_stock_units 330 and reorder_point_units 1330."""
    payload = mature_item_payload(family_id, **overrides)
    return get_success_data(api_client.create_item(payload, ADMIN), 201)


def create_item_with_defaults(family_id: str, **overrides) -> dict:
    """One Item that omits every optional policy field so the declared defaults
    apply (npi_ramp_pct 100, service_level_target_pct 95.0, demand_cv 0.30,
    lead_time_days 30, lifecycle_state MATURE)."""
    payload = item_payload(family_id, **overrides)
    return get_success_data(api_client.create_item(payload, ADMIN), 201)


def create_customer(**overrides) -> dict:
    payload = customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN), 201)


def create_capacity_block(family_id: str, **overrides) -> dict:
    payload = capacity_block_payload(family_id, **overrides)
    return get_success_data(api_client.create_capacity_block(payload, SUPPLY), 201)


def create_cycle(**overrides) -> dict:
    payload = planning_cycle_payload(**overrides)
    return get_success_data(api_client.create_planning_cycle(payload, ADMIN), 201)


def create_forecast(cycle_id: str, item_id: str, customer_id: str, **overrides) -> dict:
    payload = demand_forecast_payload(cycle_id, item_id, customer_id, **overrides)
    return get_success_data(api_client.create_demand_forecast(payload, PLANNER), 201)


def transition_forecast(forecast_id: str, target_status: str, headers=None, **extra) -> dict:
    payload = forecast_transition_payload(target_status, **extra)
    return get_success_data(
        api_client.transition_demand_forecast(
            forecast_id, payload, headers if headers is not None else PLANNER
        ),
        200,
    )


def lock_forecast(forecast_id: str) -> dict:
    """BASELINE -> UNDER_CONSENSUS as the planner, then UNDER_CONSENSUS ->
    CONSENSUS_LOCKED as the review lead."""
    transition_forecast(forecast_id, "UNDER_CONSENSUS", PLANNER)
    return transition_forecast(forecast_id, "CONSENSUS_LOCKED", LEAD)


def lock_forecast_directly(forecast_id: str) -> dict:
    """BASELINE -> CONSENSUS_LOCKED in one hop, which has no precondition beyond
    the line being in BASELINE."""
    return transition_forecast(forecast_id, "CONSENSUS_LOCKED", LEAD)


def transition_cycle(cycle_id: str, target_status: str, headers=None, **extra) -> dict:
    payload = cycle_transition_payload(target_status, **extra)
    return get_success_data(
        api_client.transition_planning_cycle(
            cycle_id, payload, headers if headers is not None else ADMIN
        ),
        200,
    )


def create_promotion(item_id: str, customer_id: str, **overrides) -> dict:
    payload = promotion_payload(item_id, customer_id, **overrides)
    return get_success_data(api_client.create_promotion(payload, PLANNER), 201)


def approve_promotion(promotion_id: str) -> dict:
    return get_success_data(api_client.approve_promotion(promotion_id, LEAD, {}), 200)


def create_approved_promotion(item_id: str, customer_id: str, **overrides) -> dict:
    promotion = create_promotion(item_id, customer_id, **overrides)
    return approve_promotion(promotion["id"])


def create_adjustment(
    forecast_id: str,
    expected_version: int,
    adjustment_type: str = "SALES_INTELLIGENCE",
    delta_units: int = 0,
    **overrides,
) -> dict:
    payload = consensus_adjustment_payload(
        forecast_id, expected_version, adjustment_type, delta_units, **overrides
    )
    return get_success_data(
        api_client.create_consensus_adjustment(payload, PLANNER), 201
    )


def review_adjustment(adjustment_id: str, decision: str, **overrides) -> dict:
    payload = adjustment_review_payload(decision, **overrides)
    return get_success_data(
        api_client.review_consensus_adjustment(adjustment_id, payload, LEAD), 200
    )


def resubmit_adjustment(adjustment_id: str, expected_version: int, **overrides) -> dict:
    payload = adjustment_resubmit_payload(expected_version, **overrides)
    return get_success_data(
        api_client.resubmit_consensus_adjustment(adjustment_id, payload, PLANNER), 200
    )


def read_forecast(forecast_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_demand_forecast(
            forecast_id, headers if headers is not None else PLANNER
        ),
        200,
    )


def read_cycle(cycle_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_planning_cycle(
            cycle_id, headers if headers is not None else ADMIN
        ),
        200,
    )


def read_item(item_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_item(item_id, headers if headers is not None else ADMIN), 200
    )


def read_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_supply_plan(plan_id, headers if headers is not None else SUPPLY),
        200,
    )


def read_scenario(scenario_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_scenario(
            scenario_id, headers if headers is not None else SUPPLY
        ),
        200,
    )


def read_promotion(promotion_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_promotion(
            promotion_id, headers if headers is not None else PLANNER
        ),
        200,
    )


def read_adjustment(adjustment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_consensus_adjustment(
            adjustment_id, headers if headers is not None else PLANNER
        ),
        200,
    )


def build_supply_plan(cycle_id: str, item_id: str) -> dict:
    payload = supply_plan_payload(cycle_id, item_id)
    return get_success_data(api_client.create_supply_plan(payload, SUPPLY), 201)


def ration_plan(plan_id: str) -> dict:
    return get_success_data(api_client.ration_supply_plan(plan_id, SUPPLY, {}), 200)


def list_plan_allocations(plan_id: str, headers=None) -> list:
    response = api_client.list_allocations(
        headers if headers is not None else SUPPLY,
        params={"supply_plan_id": plan_id, "limit": 100},
    )
    return get_success_data(response, 200)


def create_capacity_scenario(
    cycle_id: str, target_item_id: str, added_capacity_hours, **overrides
) -> dict:
    payload = capacity_investment_scenario_payload(
        cycle_id, target_item_id, added_capacity_hours, **overrides
    )
    return get_success_data(api_client.create_scenario(payload, SUPPLY), 201)


def create_price_scenario(cycle_id: str, price_increase_pct, **overrides) -> dict:
    payload = price_realization_scenario_payload(
        cycle_id, price_increase_pct, **overrides
    )
    return get_success_data(api_client.create_scenario(payload, SUPPLY), 201)


def evaluate_scenario(scenario_id: str) -> dict:
    return get_success_data(api_client.evaluate_scenario(scenario_id, SUPPLY, {}), 200)


def select_scenario(scenario_id: str, expected_cycle_version: int) -> dict:
    payload = scenario_select_payload(expected_cycle_version)
    return get_success_data(api_client.select_scenario(scenario_id, payload, EXEC), 200)


def reset_inventory_policy(
    item_id: str, service_level_target_pct, demand_cv, lead_time_days
) -> dict:
    payload = inventory_policy_payload(
        service_level_target_pct, demand_cv, lead_time_days
    )
    return get_success_data(
        api_client.reset_inventory_policy(item_id, payload, SUPPLY), 200
    )


def transition_item(item_id: str, target_state: str, headers=None, **extra) -> dict:
    payload = item_lifecycle_payload(target_state, **extra)
    return get_success_data(
        api_client.transition_item_lifecycle(
            item_id, payload, headers if headers is not None else PLANNER
        ),
        200,
    )


def post_accuracy_record(
    cycle_id: str, item_id: str, customer_id: str, actual_units: int, **overrides
) -> dict:
    payload = accuracy_record_payload(
        cycle_id, item_id, customer_id, actual_units, **overrides
    )
    return get_success_data(api_client.create_accuracy_record(payload, PLANNER), 201)


def read_accuracy_summary(cycle_id: str, headers=None, params=None) -> dict:
    return get_success_data(
        api_client.get_cycle_accuracy_summary(
            cycle_id, headers if headers is not None else ADMIN, params=params
        ),
        200,
    )


def read_family(family_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_product_family(
            family_id, headers if headers is not None else ADMIN
        ),
        200,
    )


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc(clock_payload(to_iso8601), ADMIN), 200
    )


# ---------------------------------------------------------------------------
# Cycle phase walking
# ---------------------------------------------------------------------------

CYCLE_PHASE_ORDER = [
    "DEMAND_REVIEW",
    "SUPPLY_REVIEW",
    "SCENARIO_REVIEW",
    "EXECUTIVE_REVIEW",
    "PUBLISHED",
]


def advance_cycle_to(cycle_id: str, target_status: str) -> dict:
    """Walk the cycle forward one phase at a time up to ``target_status``.

    The forward phase edges are driven by the SopAdmin; publication is reserved
    to the ExecutiveSponsor, so the final hop switches identity.
    """
    current = read_cycle(cycle_id)["status"]
    start = CYCLE_PHASE_ORDER.index(current)
    stop = CYCLE_PHASE_ORDER.index(target_status)
    data = None
    for phase in CYCLE_PHASE_ORDER[start + 1 : stop + 1]:
        headers = EXEC if phase == "PUBLISHED" else ADMIN
        data = transition_cycle(cycle_id, phase, headers)
    return data if data is not None else read_cycle(cycle_id)


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------


def setup_base_fixture(
    cycle_code: str = "CY-BASE",
    horizon_start_month: str = "2026-09",
    horizon_end_month: str = "2026-09",
    financial_commitment_cents: int = 0,
    supply_review_policy: str = "NET_INVENTORY_FIRST",
    with_capacity_block: bool = False,
    available_hours=9,
    item_overrides: dict = None,
    customer_overrides: dict = None,
    family_overrides: dict = None,
) -> dict:
    """One ProductFamily, one MATURE Item, one Customer and one PlanningCycle in
    DEMAND_REVIEW — the shape almost every scenario starts from.

    With ``with_capacity_block`` a single block spanning the whole 2026-09 month
    is added, which at 100 units/hour turns ``available_hours`` into available
    units.
    """
    family = create_family(**(family_overrides or {}))
    item = create_item(family["id"], **(item_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    block = None
    if with_capacity_block:
        block = create_capacity_block(family["id"], available_hours=available_hours)
    cycle = create_cycle(
        cycle_code=cycle_code,
        horizon_start_month=horizon_start_month,
        horizon_end_month=horizon_end_month,
        financial_commitment_cents=financial_commitment_cents,
        supply_review_policy=supply_review_policy,
    )
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "block": block,
        "cycle": cycle,
    }


def setup_locked_line_fixture(
    cycle_code: str = "CY-LOCKED",
    level_units: int = 1000,
    financial_commitment_cents: int = 0,
    supply_review_policy: str = "NET_INVENTORY_FIRST",
    with_capacity_block: bool = True,
    available_hours=9,
    item_overrides: dict = None,
) -> dict:
    """Base fixture plus one CONSENSUS_LOCKED forecast line for 2026-09."""
    ctx = setup_base_fixture(
        cycle_code=cycle_code,
        financial_commitment_cents=financial_commitment_cents,
        supply_review_policy=supply_review_policy,
        with_capacity_block=with_capacity_block,
        available_hours=available_hours,
        item_overrides=item_overrides,
    )
    forecast = create_forecast(
        ctx["cycle"]["id"],
        ctx["item"]["id"],
        ctx["customer"]["id"],
        level_units=level_units,
    )
    ctx["forecast"] = lock_forecast(forecast["id"])
    return ctx


def setup_supply_review_fixture(**kwargs) -> dict:
    """A locked line whose cycle has been advanced to SUPPLY_REVIEW, ready for a
    supply plan."""
    ctx = setup_locked_line_fixture(**kwargs)
    ctx["cycle"] = transition_cycle(ctx["cycle"]["id"], "SUPPLY_REVIEW")
    return ctx


def setup_planned_supply_plan(**kwargs) -> dict:
    """SUPPLY_REVIEW fixture with a PLANNED SupplyPlan already derived."""
    ctx = setup_supply_review_fixture(**kwargs)
    ctx["plan"] = build_supply_plan(ctx["cycle"]["id"], ctx["item"]["id"])
    return ctx


def setup_published_cycle_fixture(
    cycle_code: str = "CY-PUBLISHED",
    level_units: int = 1000,
    horizon_start_month: str = "2026-09",
    horizon_end_month: str = "2026-09",
) -> dict:
    """A cycle carrying one CONSENSUS_LOCKED line, driven all the way to
    PUBLISHED with a zero financial commitment so the gap is already closed.

    Accuracy records may only be posted while the cycle is PUBLISHED, so this is
    the entry point for every accuracy scenario.
    """
    ctx = setup_base_fixture(
        cycle_code=cycle_code,
        horizon_start_month=horizon_start_month,
        horizon_end_month=horizon_end_month,
        financial_commitment_cents=0,
    )
    forecast = create_forecast(
        ctx["cycle"]["id"],
        ctx["item"]["id"],
        ctx["customer"]["id"],
        month=horizon_start_month,
        level_units=level_units,
    )
    ctx["forecast"] = lock_forecast_directly(forecast["id"])
    ctx["cycle"] = advance_cycle_to(ctx["cycle"]["id"], "PUBLISHED")
    return ctx


def setup_two_customer_published_cycle() -> dict:
    """Two customers on one item inside a PUBLISHED cycle, each carrying one
    CONSENSUS_LOCKED line.

    Line A is 130 units and line B is 5200 units, a deliberately lopsided pair:
    the unweighted mean of the per-record percentage errors and the
    volume-weighted ratio of total absolute error to total actual land on very
    different numbers over exactly the same two records.
    """
    family = create_family(family_code="FAM-SNACK", name="Salty Snacks")
    item = create_item(family["id"], sku="SKU-CHIP-1")
    customer_a = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=1
    )
    customer_b = create_customer(
        customer_code="CUST-B", name="Beta Club", channel="CLUB", priority_rank=3
    )
    cycle = create_cycle(cycle_code="SOP-2026-09", financial_commitment_cents=0)
    forecast_a = create_forecast(
        cycle["id"], item["id"], customer_a["id"], level_units=130
    )
    forecast_b = create_forecast(
        cycle["id"], item["id"], customer_b["id"], level_units=5200
    )
    lock_forecast(forecast_a["id"])
    lock_forecast(forecast_b["id"])
    cycle = advance_cycle_to(cycle["id"], "PUBLISHED")
    return {
        "family": family,
        "item": item,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "cycle": cycle,
        "forecast_a": forecast_a,
        "forecast_b": forecast_b,
    }


def setup_gap_fixture(
    cycle_code: str = "SOP-GAP-09",
    sku: str = "SKU-PIZZA-1",
    financial_commitment_cents: int = 10000000,
    available_hours=10,
    level_units: int = 7000,
) -> dict:
    """A capacity-starved cycle with a large open commitment.

    A single 10-hour block against a 100 units/hour family yields 1000 available
    units against a 7000-unit locked line, so the plan is CAPACITY constrained
    with a 6330-unit shortfall and the cycle keeps a 9,000,000-cent gross gap
    that only a scenario can close.
    """
    family = create_family(family_code="FAM-FROZ", name="Frozen")
    item = create_item(family["id"], sku=sku)
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    block = create_capacity_block(family["id"], available_hours=available_hours)
    cycle = create_cycle(
        cycle_code=cycle_code,
        financial_commitment_cents=financial_commitment_cents,
    )
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=level_units
    )
    lock_forecast(forecast["id"])
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    cycle = transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "block": block,
        "cycle": cycle,
        "forecast": forecast,
        "plan": plan,
    }


def setup_five_customer_rationing(
    cycle_code: str = "SOP-RATION-09",
    sku: str = "SKU-BREAD-1",
    family_code: str = "FAM-BAKE",
    family_name: str = "Bakery",
    ration: bool = True,
) -> dict:
    """The full rationing waterfall in one fixture.

    Five customers spread across the priority ladder — rank 1 (protected), rank 3
    and rank 4 (pro-rata pool), rank 5 on credit hold and rank 6 with a
    zero-unit request — all locked at 400 / 500 / 300 / 200 / 0 units against a
    900-unit constrained plan, so pass one, pass two, the credit-hold exclusion
    and the zero-request case are all exercised at once.
    """
    family = create_family(family_code=family_code, name=family_name)
    item = create_item(family["id"], sku=sku)
    c1 = create_customer(
        customer_code="CUST-1", name="Protected Club", channel="CLUB", priority_rank=1
    )
    c2 = create_customer(
        customer_code="CUST-2", name="Big Grocery", channel="GROCERY", priority_rank=3
    )
    c3 = create_customer(
        customer_code="CUST-3", name="Discount Chain", channel="DISCOUNT", priority_rank=4
    )
    c4 = create_customer(
        customer_code="CUST-4",
        name="Held Account",
        channel="ECOMMERCE",
        priority_rank=5,
        credit_hold=True,
    )
    c5 = create_customer(
        customer_code="CUST-5",
        name="Dormant Account",
        channel="ECOMMERCE",
        priority_rank=6,
    )
    block = create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code=cycle_code, financial_commitment_cents=0)
    customers = [c1, c2, c3, c4, c5]
    levels = [400, 500, 300, 200, 0]
    forecasts = []
    for customer, level in zip(customers, levels):
        forecast = create_forecast(
            cycle["id"], item["id"], customer["id"], level_units=level
        )
        lock_forecast(forecast["id"])
        forecasts.append(forecast)
    cycle = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    if ration:
        plan = ration_plan(plan["id"])
    return {
        "family": family,
        "item": item,
        "customers": customers,
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "c4": c4,
        "c5": c5,
        "block": block,
        "cycle": cycle,
        "forecasts": forecasts,
        "plan": plan,
    }


def setup_runout_cascade_fixture() -> dict:
    """Three consecutive monthly lines with a promotion-backed endorsement on the
    last one, all locked, plan built and rationed.

    Everything downstream of the November promotion is in place before the item
    is sent to RUNOUT, so a single lifecycle transition has promotions,
    adjustments, consensus lines, a supply plan, its allocations and the cycle's
    money to walk through.
    """
    family = create_family(family_code="FAM-DAIRY", name="Dairy")
    item = create_item(family["id"], sku="SKU-YOG-1")
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    block = create_capacity_block(family["id"], available_hours=9)
    promotion = create_approved_promotion(
        item["id"],
        customer["id"],
        start_month="2026-11",
        end_month="2026-11",
        lift_pct=10,
        cannibalization_pct=0,
    )
    cycle = create_cycle(
        cycle_code="SOP-RUNOUT",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
    )
    fc_sep = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-09", level_units=1000
    )
    fc_oct = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-10", level_units=1000
    )
    fc_nov = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-11", level_units=1000
    )
    adjustment = create_adjustment(
        fc_nov["id"],
        fc_nov["version"],
        adjustment_type="PROMOTION",
        delta_units=0,
        rationale="November club feature",
        promotion_id=promotion["id"],
    )
    adjustment = review_adjustment(adjustment["id"], "ENDORSE")
    lock_forecast(fc_sep["id"])
    lock_forecast(fc_oct["id"])
    lock_forecast_directly(fc_nov["id"])
    cycle = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    plan = ration_plan(plan["id"])
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "block": block,
        "promotion": promotion,
        "cycle": cycle,
        "fc_sep": fc_sep,
        "fc_oct": fc_oct,
        "fc_nov": fc_nov,
        "adjustment": adjustment,
        "plan": plan,
    }


def setup_consensus_promo_fixture(
    cycle_code: str = "SOP-COMB-09", sku: str = "SKU-BAR-1"
) -> dict:
    """An APPROVED promotion sitting over a 333-unit baseline line.

    333 is chosen because eleven per cent of it and four per cent of it both fall
    on a half-cent boundary, so rounding the two percentage terms separately and
    rounding their difference in one pass disagree by a unit.
    """
    family = create_family(family_code="FAM-CANDY", name="Confections")
    item = create_item(
        family["id"], sku=sku, unit_price_cents=500, unit_cost_cents=200
    )
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    promotion = create_approved_promotion(
        item["id"],
        customer["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=11,
        cannibalization_pct=4,
    )
    cycle = create_cycle(cycle_code=cycle_code, financial_commitment_cents=0)
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=333
    )
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "promotion": promotion,
        "cycle": cycle,
        "forecast": forecast,
    }


def setup_two_policy_cycles() -> dict:
    """Two cycles over the same item and month that differ only in
    ``supply_review_policy``, both parked in SUPPLY_REVIEW.

    The item carries 500 units of on-hand stock, which is exactly what makes the
    two policies diverge: one nets the stock off demand before clamping, the
    other clamps first and subtracts the stock afterwards.
    """
    family = create_family(family_code="FAM-BEV", name="Beverages")
    item = create_item(family["id"], sku="SKU-COLA-1", on_hand_units=500)
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    block = create_capacity_block(family["id"], available_hours=9)
    net_cycle = create_cycle(
        cycle_code="SOP-NET-09",
        financial_commitment_cents=0,
        supply_review_policy="NET_INVENTORY_FIRST",
    )
    gross_cycle = create_cycle(
        cycle_code="SOP-GROSS-09",
        financial_commitment_cents=0,
        supply_review_policy="GROSS_CAPACITY_FIRST",
    )
    net_forecast = create_forecast(
        net_cycle["id"], item["id"], customer["id"], level_units=1000
    )
    gross_forecast = create_forecast(
        gross_cycle["id"], item["id"], customer["id"], level_units=1000
    )
    lock_forecast(net_forecast["id"])
    lock_forecast(gross_forecast["id"])
    net_cycle = transition_cycle(net_cycle["id"], "SUPPLY_REVIEW")
    gross_cycle = transition_cycle(gross_cycle["id"], "SUPPLY_REVIEW")
    return {
        "family": family,
        "item": item,
        "customer": customer,
        "block": block,
        "net_cycle": net_cycle,
        "gross_cycle": gross_cycle,
        "net_forecast": net_forecast,
        "gross_forecast": gross_forecast,
    }


def setup_selected_scenario_fixture(
    cycle_code: str = "SOP-LOOP-09",
    sku: str = "SKU-PIZZA-1",
    added_capacity_hours=52,
) -> dict:
    """The gap fixture carried all the way to a SELECTED scenario in
    EXECUTIVE_REVIEW, so the cycle's closure money is live and every downstream
    record (locked line, plan, allocations, scenario) is exposed to whatever the
    next transition does."""
    ctx = setup_gap_fixture(cycle_code=cycle_code, sku=sku)
    scenario = create_capacity_scenario(
        ctx["cycle"]["id"],
        ctx["item"]["id"],
        added_capacity_hours,
        name="Add second shift",
    )
    scenario = evaluate_scenario(scenario["id"])
    cycle = transition_cycle(ctx["cycle"]["id"], "EXECUTIVE_REVIEW")
    scenario = select_scenario(scenario["id"], cycle["version"])
    ctx["scenario"] = scenario
    ctx["cycle"] = read_cycle(ctx["cycle"]["id"])
    return ctx


def setup_two_evaluated_scenarios_fixture(
    cycle_code: str = "SOP-SUP-09", sku: str = "SKU-PIZZA-2"
) -> dict:
    """Two evaluated capacity-investment scenarios of different sizes over one
    gap, with the larger one already SELECTED and the cycle in EXECUTIVE_REVIEW.

    Both plays are of the same type, so selecting the second one has to displace
    the first and rewrite the cycle's closure money in the same request.
    """
    ctx = setup_gap_fixture(cycle_code=cycle_code, sku=sku)
    first = create_capacity_scenario(
        ctx["cycle"]["id"], ctx["item"]["id"], 52, name="S1 second shift"
    )
    first = evaluate_scenario(first["id"])
    second = create_capacity_scenario(
        ctx["cycle"]["id"], ctx["item"]["id"], 20, name="S2 weekend overtime"
    )
    second = evaluate_scenario(second["id"])
    cycle = transition_cycle(ctx["cycle"]["id"], "EXECUTIVE_REVIEW")
    first = select_scenario(first["id"], cycle["version"])
    ctx["first_scenario"] = first
    ctx["second_scenario"] = second
    ctx["cycle"] = read_cycle(ctx["cycle"]["id"])
    return ctx


def setup_two_customer_rationed_plan(
    cycle_code: str = "SOP-CONS-09",
    sku: str = "SKU-SOUP-1",
    family_code: str = "FAM-SOUP",
    family_name: str = "Soups",
) -> dict:
    """A rationed plan whose 900 constrained units are fully distributed across a
    protected rank-1 customer and a rank-3 pro-rata customer, leaving
    unallocated_units at zero."""
    family = create_family(family_code=family_code, name=family_name)
    item = create_item(family["id"], sku=sku)
    c1 = create_customer(
        customer_code="CUST-1", name="Protected Club", channel="CLUB", priority_rank=1
    )
    c2 = create_customer(
        customer_code="CUST-2", name="Big Grocery", channel="GROCERY", priority_rank=3
    )
    block = create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code=cycle_code, financial_commitment_cents=0)
    fc1 = create_forecast(cycle["id"], item["id"], c1["id"], level_units=400)
    fc2 = create_forecast(cycle["id"], item["id"], c2["id"], level_units=500)
    lock_forecast(fc1["id"])
    lock_forecast(fc2["id"])
    cycle = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    plan = ration_plan(plan["id"])
    return {
        "family": family,
        "item": item,
        "c1": c1,
        "c2": c2,
        "block": block,
        "cycle": cycle,
        "fc1": fc1,
        "fc2": fc2,
        "plan": plan,
    }

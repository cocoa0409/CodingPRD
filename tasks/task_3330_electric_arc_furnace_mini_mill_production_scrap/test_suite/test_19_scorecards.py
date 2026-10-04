"""Division scorecards: profit-share floor on a loss-making period (PRD §3.11)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, make_scorecard, setup_supply_pool, setup_cast_heat,
    get_scorecard, assert_scorecard_profit_invariants,
)

PM = TEST_USERS["plant_manager_headers"]


def test_profit_sharing_loss_month_distributes_zero():
    """PRD §3.11: "The `profit_pool_cents` is ten percent of `profit_cents` — the
    profit share rate is 0.10 — floored at zero: a loss-making month distributes
    nothing, and a loss never creates a negative pool. Each eligible employee's
    `distribution_per_employee_cents` is the pool divided by `headcount` using floor
    division to whole cents, and `remainder_cents` is the pool minus the per-employee
    distribution times `headcount`."
    PRD §3.11: "`profit_cents` is `revenue_cents` minus `material_cost_cents` minus
    `energy_cost_cents`."

    Design: Corner/calculations/profit_sharing_loss_month_distributes_zero
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=30000, committed=50, supplier_name="Coastal Scrap Co",
        lots=[{"received_on": "2026-09-03", "tons_received": 25, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    scorecard = make_scorecard(mill["id"], period="2026-09", headcount=7)
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 10,
                           tap_at="2026-09-08T12:00:00Z")

    closed = validate_success(
        api_client.close_scorecard(mill["id"], scorecard["id"], PM), 200)
    assert closed["status"] == "CLOSED"
    # The 10t CAST heat at 30000/t posted 300000 of material cost; no revenue.
    assert closed["material_cost_cents"] == 300_000
    assert closed["revenue_cents"] == 0
    # Negative profit is stored, not floored; the floor applies to the POOL.
    assert closed["profit_cents"] == -300_000
    assert closed["profit_pool_cents"] == 0
    assert closed["distribution_per_employee_cents"] == 0
    assert closed["remainder_cents"] == 0
    assert_scorecard_profit_invariants(closed)

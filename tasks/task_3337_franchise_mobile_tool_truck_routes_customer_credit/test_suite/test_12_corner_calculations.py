"""Corner queue B — calculations: clamps, marginal tiering, waterfall fill."""
from test_helpers import (
    CREDIT_OFFICER,
    add_inventory,
    api_client,
    confirm_order,
    create_order,
    create_product,
    create_product_order,
    create_technician,
    file_application,
    get_route,
    order_line,
    position_for,
    requested_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_success,
)


def test_decision_score_clamps_at_both_ends(api):
    """PRD §3.3: "the floored value is clamped to the integer
    range 1 to 100 inclusive. The floor binds before the ceiling ever does, which is visible in the
    arithmetic: seven prior delinquencies at 9 points each drive the base far below zero and the floor at 1
    is what a caller actually observes."
    PRD §3.3: "when the `requested_limit_cents` are at least 500000, the base is multiplied by 1.05; below
    that boundary it is multiplied by 1.00, which leaves it unchanged."

    Design: Corner/calculations/calc_credit_decision_score_clamped_at_floor_and_ceiling
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store, credit_line_limit_cents=400_000)
    weak = create_technician(store["franchisee"], people["shop"], full_name="Weak Applicant",
                             credit_line_limit_cents=100_000, months_in_trade=10,
                             employment_verified=False)
    strong = create_technician(store["franchisee"], people["shop"],
                               full_name="Strong Applicant",
                               credit_line_limit_cents=400_000, months_in_trade=100,
                               employment_verified=True)

    low = file_application(store["franchisee"], people["shop"], weak,
                           requested_limit_cents=400_000, employment_verified=False,
                           months_in_trade=10, prior_delinquency_count=7)
    high = file_application(store["franchisee"], people["shop"], strong,
                            requested_limit_cents=400_000, employment_verified=True,
                            months_in_trade=100)

    assert low["decision_score"] == 1
    assert high["decision_score"] == 100
    assert 1 <= low["decision_score"] <= 100
    assert low["approved_limit_cents"] == 0
    assert low["approved_kind"] is None


def test_granted_limit_is_marginal_and_capped_by_the_request(api):
    """PRD §3.3: "the word marginally is load-bearing: each tier's rate applies only to the points that fall inside that tier."
    PRD §3.3: "`approved_limit_cents` is the smaller of the tiered amount and the application's
    `requested_limit_cents`."

    Design: Corner/calculations/calc_credit_decision_limit_marginal_tiering_and_requested_cap
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store, credit_line_limit_cents=400_000)
    first = create_technician(store["franchisee"], people["shop"], full_name="First Applicant",
                              credit_line_limit_cents=400_000, months_in_trade=40,
                              employment_verified=True)
    second = create_technician(store["franchisee"], people["shop"],
                               full_name="Second Applicant",
                               credit_line_limit_cents=400_000, months_in_trade=100,
                               employment_verified=True)

    wide = file_application(store["franchisee"], people["shop"], first,
                            requested_limit_cents=400_000, months_in_trade=40)
    assert wide["decision_score"] == 72
    approved_wide = validate_success(api_client.advance_application(
        wide["id"], {"action": "APPROVE"}, store["franchisee"]["owner_headers"]))
    assert approved_wide["approved_limit_cents"] == 43000, (
        "750*40 + 500*20 + 250*12 across the three marginal tiers")
    assert approved_wide["approved_limit_cents"] != 54000, "the average-rate variant"

    narrow = file_application(store["franchisee"], people["shop"], second,
                              requested_limit_cents=45_338, months_in_trade=100)
    approved_narrow = validate_success(api_client.advance_application(
        narrow["id"], {"action": "APPROVE"}, store["franchisee"]["owner_headers"]))
    assert approved_narrow["approved_limit_cents"] == 45338
    assert approved_narrow["approved_kind"] == "REVOLVING"
    assert approved_narrow["approved_term_months"] == 0


def test_declined_application_records_no_limit(api):
    """PRD §3.3: "All four side effects are likewise identical on a decline except that
    `approved_limit_cents` is set to 0 — a declined application records no limit — and the
    `decision_note` records the refusal."

    Design: Corner/calculations/calc_credit_decision_limit_declined_sets_zero
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store, months_in_trade=10, employment_verified=False)
    application = file_application(store["franchisee"], people["shop"],
                                   people["technician"], requested_limit_cents=400_000,
                                   employment_verified=False, months_in_trade=10,
                                   decision_source="FRANCHISOR")
    reviewed = validate_success(api_client.advance_application(
        application["id"], {"action": "REVIEW"}, CREDIT_OFFICER))
    assert reviewed["decision_score"] == 45

    declined = validate_success(api_client.advance_application(
        application["id"], {"action": "DECLINE"}, CREDIT_OFFICER))
    assert declined["application_status"] == "DECLINED"
    assert declined["approved_limit_cents"] == 0
    assert declined["approved_kind"] is None
    assert declined["approved_term_months"] == 0
    assert declined["decision_note"]


def test_replenishment_waterfall_fills_every_line_the_budget_covers(api):
    """PRD §3.6: "A line whose unit cost exceeds
    the remaining budget is skipped with a `deferred_qty` equal to its full requested quantity, and the
    loop continues to cheaper lines that the budget can still cover"
    PRD §3.6: "`ordered_cost_cents` is the sum over the ordered lines of
    `ordered_qty` multiplied by `unit_cost_cents`, and it can never exceed `investment_ceiling_cents`."

    Design: Corner/calculations/calc_route_replenishment_allocation_deferred_when_budget_runs_out
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    powered = create_product(sku="P1", product_name="Powertool", category="POWER_TOOLS",
                             unit_cost_cents=30000, retail_price_cents=39000)
    diagnostic = create_product(sku="P2", product_name="Diagnostic Reader",
                                category="DIAGNOSTICS", unit_cost_cents=12000,
                                retail_price_cents=15000)

    order = create_product_order(
        store["franchisee"], store["route"],
        [requested_line(powered["id"], 1), requested_line(diagnostic["id"], 1)],
        ceiling=42000, mix_profile="POWER_TOOLS")

    assert order["requested_cost_cents"] == 42000
    assert order["ordered_cost_cents"] == 42000
    assert order["is_fully_covered"] is True
    assert order["deferred_lines"] == []
    assert order["ordered_cost_cents"] <= order["investment_ceiling_cents"]


def test_over_pledge_sums_the_excess_across_every_position(api):
    """PRD §2.12: "`over_pledge_cents` is the sum over every
    `(route, product)` pair of the excess of committed units over physical units multiplied by cost"
    PRD §2.12: "A product with no position on the route contributes zero to both aggregates."

    Design: Corner/calculations/calc_inventory_over_pledge_aggregates_across_positions
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    wrench = setup_product_with_stock(store, sku="P1", category="POWER_TOOLS", cost=12000,
                                      retail=15000, on_hand=3)
    reader = setup_product_with_stock(store, sku="P2", category="DIAGNOSTICS", cost=20000,
                                      retail=25000, on_hand=5)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=100_000)

    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(wrench, 3, unit_price_cents=15000),
                          order_line(reader, 5, unit_price_cents=25000)],
                         mix_profile="POWER_TOOLS")
    confirm_order(store["franchisee"], order, order["version"])

    wrench_position = position_for(store["franchisee"], store["route"]["id"], wrench["id"])
    add_inventory(store["franchisee"], store["route"], wrench, 1,
                  position_id=wrench_position["id"])

    route = get_route(store["route"]["id"])
    assert route["over_pledge_cents"] == 24000, "two units over at 12000 cents"
    assert route["inventory_at_risk_cents"] == 136000

    adjusted = position_for(store["franchisee"], store["route"]["id"], wrench["id"])
    assert adjusted["reserved_qty"] == 3
    assert adjusted["on_hand_qty"] == 1
    untouched = position_for(store["franchisee"], store["route"]["id"], reader["id"])
    assert untouched["reserved_qty"] == 5
    assert untouched["remaining_qty"] == 0

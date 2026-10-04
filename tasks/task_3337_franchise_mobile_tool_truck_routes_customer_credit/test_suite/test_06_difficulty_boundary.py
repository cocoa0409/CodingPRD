"""Difficulty queue A — boundary_precision_check: exact crossings."""
from test_helpers import (
    add_inventory,
    confirm_order,
    create_order,
    deliver_order,
    get_account,
    get_route,
    order_line,
    position_for,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
)


def test_accrual_rate_tier_crosses_at_exactly_fifty_thousand_cents(api):
    """PRD §3.5: "The boundaries are on the cents and
    inclusive upward: a basis of exactly 50000 cents takes the mid rate, not the low rate, and a basis of
    exactly 200000 cents takes the high rate."
    PRD §3.5: "when the basis is less than 50000
    cents the low rate of `0.1560` applies"

    Design: Difficulty/boundary_precision_check/boundary_rate_tier_crossing_at_exactly_50000_cents
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store, credit_line_limit_cents=200_000)
    upper = setup_product_with_stock(store, sku="P1", cost=40_000, retail=49_875, on_hand=10)
    lower = setup_product_with_stock(store, sku="P2", cost=40_000, retail=49_874, on_hand=10)

    account_upper = setup_account(store["franchisee"], people["shop"],
                                  people["technician"], requested_limit_cents=50_000)
    account_lower = setup_account(store["franchisee"], people["shop"],
                                  people["technician"], requested_limit_cents=49_999)

    for product, account in ((upper, account_upper), (lower, account_lower)):
        order = create_order(store["franchisee"], store["route"], people["technician"],
                             account,
                             [order_line(product, 1, unit_price_cents=product["retail_price_cents"])],
                             mix_profile="POWER_TOOLS")
        confirm_order(store["franchisee"], order, order["version"])
        deliver_order(store["franchisee"], order)

    set_clock("2026-09-14T00:00:00Z")
    at_boundary = get_account(account_upper["id"])
    one_cent_below = get_account(account_lower["id"])

    assert at_boundary["principal_balance_cents"] == 50000
    assert one_cent_below["principal_balance_cents"] == 49999
    assert at_boundary["accrued_finance_charge_cents"] == 175
    assert one_cent_below["accrued_finance_charge_cents"] == 150
    assert (at_boundary["accrued_finance_charge_cents"]
            - one_cent_below["accrued_finance_charge_cents"]) == 25


def test_over_pledge_stays_zero_until_commitment_strictly_exceeds_stock(api):
    """PRD §2.12: "A position that is committed exactly to its on-hand quantity contributes zero: a
    fully committed position is not over-pledged, and only a strictly larger committed quantity adds cost."
    PRD §2.12: "`inventory_at_risk_cents` is the sum over every position on the route of
    `reserved_qty` multiplied by `unit_cost_cents`"

    Design: Difficulty/boundary_precision_check/boundary_fully_committed_stock_adds_zero_over_pledge
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=2)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)

    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 2)], mix_profile="POWER_TOOLS")
    confirm_order(store["franchisee"], order, order["version"])

    at_capacity = get_route(store["route"]["id"])
    assert at_capacity["over_pledge_cents"] == 0
    assert at_capacity["inventory_at_risk_cents"] == 24000

    position = position_for(store["franchisee"], store["route"]["id"], product["id"])
    adjusted = add_inventory(store["franchisee"], store["route"], product, 1,
                             position_id=position["id"])
    assert adjusted["on_hand_qty"] == 1
    assert adjusted["reserved_qty"] == 2

    over = get_route(store["route"]["id"])
    assert over["over_pledge_cents"] == 12000, "one unit over at 12000 cents"
    assert over["over_pledge_cents"] != 0
    assert over["inventory_at_risk_cents"] == 24000, (
        "the aggregate reads reserved units, not on-hand units")

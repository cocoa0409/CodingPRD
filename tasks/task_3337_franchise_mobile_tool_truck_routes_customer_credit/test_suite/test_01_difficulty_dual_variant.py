"""Difficulty queue A — dual_variant_calc: one rule, two valid bases."""
from test_helpers import (
    advance_claim,
    confirm_order,
    create_order,
    deliver_order,
    file_claim,
    get_account,
    get_order,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_success,
)


def test_sales_order_exposes_provisional_and_final_financing_bases(api):
    """PRD §3.4: "While the order is `DRAFT` or `CONFIRMED`, the provisional basis
    applies and `financed_principal_cents` equals `gross_total_cents`; warranty
    allocations that already exist against the order are ignored."
    PRD §3.4: "Once the order reaches `DELIVERED`, the final basis applies and
    `financed_principal_cents` equals `gross_total_cents` minus the sum of
    `principal_allocated_cents` over every warranty claim on this order whose
    `claim_status` is `APPROVED`".
    PRD §3.8: "Outside warranty it is the smaller of the line's `unit_price_cents`
    and 40 percent of the product's `unit_cost_cents` — a `CAP_RATE` of `0.40`,
    rounded down to a whole number of cents."

    Design: Difficulty/dual_variant_calc/dual_variant_financing_principal_on_sales_order
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)

    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 2)],
                         mix_profile="DIAGNOSTIC_WEIGHTED")
    confirmed = confirm_order(store["franchisee"], order, order["version"])
    assert confirmed["gross_total_cents"] == 30225
    provisional = confirmed["financed_principal_cents"]
    assert provisional == 30225, "the provisional basis is the gross order value"

    # Move past the 12-month warranty term so the claim prices outside warranty.
    set_clock("2027-09-13T00:00:00Z")
    deliver_order(store["franchisee"], order)
    claim = validate_success(file_claim(store["franchisee"], order, "idem-dual-fin-1",
                                        apply_to_account_id=account["id"]), 201)
    advance_claim(store["franchisee"], order, claim, "SUBMIT")
    approved = validate_success(advance_claim(store["franchisee"], order, claim,
                                              "APPROVE"))
    assert approved["principal_allocated_cents"] == 4800

    final_order = get_order(order["id"])
    assert final_order["gross_total_cents"] == 30225
    assert final_order["financed_principal_cents"] == 25425
    assert final_order["gross_total_cents"] - final_order["financed_principal_cents"] == 4800
    assert provisional != final_order["financed_principal_cents"], (
        "the two bases must be distinguishable for the same order")

    # The charge basis writes the allocation onto the named account as new principal.
    refreshed = get_account(account["id"])
    assert refreshed["principal_balance_cents"] == 35025

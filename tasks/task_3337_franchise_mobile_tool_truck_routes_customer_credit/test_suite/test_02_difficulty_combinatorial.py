"""Difficulty queue A — combinatorial_formula: pinned rounding and evaluation order."""
from test_helpers import (
    confirm_order,
    create_order,
    deliver_order,
    get_account,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_success,
)


def test_order_gross_rounds_each_line_before_summing(api):
    """PRD §3.4: "Each line's extended amount is
    the line's `unit_price_cents` multiplied by the line's `quantity` multiplied by
    the selected multiplier, rounded half up to a whole number of cents, and that
    rounding is performed per line, independently."
    PRD §3.4: "rounding the total once at the end, after summing the unrounded
    extended amounts, produces a different cent value for the same order, and that
    variant is prohibited."

    Design: Difficulty/combinatorial_formula/combinatorial_nested_rounding_order_on_order_gross
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)

    split = create_order(
        store["franchisee"], store["route"], people["technician"], account,
        [order_line(product, 1), order_line(product, 1)],
        mix_profile="DIAGNOSTIC_WEIGHTED")
    merged = create_order(
        store["franchisee"], store["route"], people["technician"], account,
        [order_line(product, 2)], mix_profile="DIAGNOSTIC_WEIGHTED")

    assert split["gross_total_cents"] == 30226, "15113 + 15113, rounded per line"
    assert merged["gross_total_cents"] == 30225, "30000 * 1.0075 rounds once"
    assert split["gross_total_cents"] != merged["gross_total_cents"], (
        "the prohibited sum-then-round variant would make the two orders agree")


def test_minimum_payment_due_reads_the_opening_balance_tier(api):
    """PRD §3.5: "The tier is read from the account's
    current balance, never from the value the formula is about to produce: first the current balance is
    read, then the percentage is selected from that opening figure, then the due is derived."
    PRD §3.5: "when it is below 150000 cents the mid tier percentage of `0.10` applies"

    Design: Difficulty/combinatorial_formula/combinatorial_circular_total_and_fee_evaluation_order
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=45_338)

    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 3)],
                         mix_profile="DIAGNOSTIC_WEIGHTED")
    confirm_order(store["franchisee"], order, order["version"])
    deliver_order(store["franchisee"], order)

    before = get_account(account["id"])
    assert before["current_balance_cents"] == 45338
    assert before["minimum_payment_due_cents"] == 4534, "10 percent of the 45338 balance"

    set_clock("2026-09-14T00:00:00Z")
    after = get_account(account["id"])
    assert after["accrued_finance_charge_cents"] == 136
    assert after["current_balance_cents"] == 45474, "principal plus the accrued charge"
    assert after["minimum_payment_due_cents"] == 4547, (
        "the tier is read from the post-accrual balance, not from the pre-accrual one")
    assert after["minimum_payment_due_cents"] != 4534

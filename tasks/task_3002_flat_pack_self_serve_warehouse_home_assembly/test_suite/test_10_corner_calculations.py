"""Corner design — section: calculations."""
from test_helpers import (
    OPS,
    add_return_line,
    create_customer,
    create_return,
    cust_headers,
    get_success_data,
    grade_line,
    seed_member_points,
    settle_return,
    setup_article_with_stock,
    setup_fulfilled_order,
    setup_paid_order,
    setup_store_and_customer,
    submit_return,
    validate_success,
)


def test_signal_threshold_boundary_in_stock_vs_low_stock(api):
    """PRD §3.1: "`OUT_OF_STOCK` when no complete units are available,
    `LOW_STOCK` when some are available but fewer than the threshold, and
    `IN_STOCK` once availability reaches the threshold."
    PRD §3.1: "The response reports the queried `article_id` and `store_id`,
    the computed `available_units`, the `threshold_used` (the store's
    `low_stock_threshold`), and the `signal` itself"

    Design: Corner/calculations/signal_threshold_boundary_in_stock_vs_low_stock
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
    stock = stocks[0]

    signal = get_success_data(
        api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
    assert signal["signal"] == "IN_STOCK"
    assert signal["available_units"] == 5
    assert signal["threshold_used"] == 5

    validate_success(api.adjust_bin_stock(
        stock["id"],
        {"delta_on_hand": -1, "expected_stock_version": stock["version"]},
        OPS,
    ))
    signal2 = get_success_data(
        api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
    assert signal2["signal"] == "LOW_STOCK"
    assert signal2["available_units"] == 4


def test_signal_multi_carton_min_over_cartons(api):
    """PRD §3.1: "Otherwise `available_units` is the smallest per-carton
    `available` across all of the article's cartons — the number of complete
    multi-box sets the shelf can yield."

    Design: Corner/calculations/signal_multi_carton_min_over_cartons
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, price_cents=5000, category="FURNITURE",
        cartons=[(10, 0.1, 7), (8, 0.08, 4)])

    signal = get_success_data(
        api.get_stock_signal(store["id"], article["id"], cust_headers(customer)))
    assert signal["available_units"] == 4, (
        "min over cartons: not 7 and not the 11-unit sum"
    )
    assert signal["signal"] == "LOW_STOCK"


def test_family_price_applies_only_to_members(api):
    """PRD §3.3: "First, each line's `unit_price_cents` is captured: the
    article's `family_price_cents` when the customer is an `ACTIVE` member and
    a member price is set, otherwise the regular `price_cents`."

    Design: Corner/calculations/family_price_applies_only_to_members
    """
    store, non_member = setup_store_and_customer(member=False)
    member = create_customer(member=True)
    article, _, _ = setup_article_with_stock(
        store, on_hand=10, price_cents=999, family_price_cents=799)

    order_m, lines_m = setup_paid_order(member, store, [(article, 2)])
    order_n, lines_n = setup_paid_order(non_member, store, [(article, 2)])

    assert order_m["total_cents"] == 1598
    assert order_m["discount_cents"] == 0
    line_m = get_success_data(api.get_order_line(lines_m[0]["id"], cust_headers(member)))
    assert line_m["unit_price_cents"] == 799

    assert order_n["total_cents"] == 1998
    assert order_n["discount_cents"] == 0
    line_n = get_success_data(api.get_order_line(lines_n[0]["id"], cust_headers(non_member)))
    assert line_n["unit_price_cents"] == 999


def test_points_redemption_capped_at_twenty_percent(api):
    """PRD §3.3: "Seventh, points redemption: the applied
    `points_discount_cents` is the smallest of the requested `redeem_points`,
    the customer's `points_balance`, and 20 percent of the post-discount
    merchandise value (the subtotal minus the discount), that last term
    rounded down to a whole cent."
    PRD §3.3: "The redeemed points are debited from the customer's
    `points_balance` as part of the same checkout."

    Design: Corner/calculations/points_redemption_capped_at_twenty_percent
    """
    store, member = setup_store_and_customer(member=True)
    article, _, _ = setup_article_with_stock(store, on_hand=10, price_cents=500)
    seed_member_points(member, store, 1000)

    order, _ = setup_paid_order(member, store, [(article, 2)], redeem_points=500)
    assert order["subtotal_cents"] == 1000
    assert order["points_discount_cents"] == 200, (
        f"cap floor(1000 x 0.20) = 200 binds below the requested 500; got "
        f"{order['points_discount_cents']}"
    )
    assert order["total_cents"] == 800
    customer_after = get_success_data(api.get_customer(member["id"], OPS))
    assert customer_after["points_balance"] == 800


def test_points_accrual_zero_for_non_member(api):
    """PRD §3.3: "if the customer is an `ACTIVE` member the server computes
    `points_earned` as the whole-dollar floor of `total_cents` divided by 100
    and adds those points to the customer's `points_balance`; a non-member
    earns nothing."

    Design: Corner/calculations/points_accrual_zero_for_non_member
    """
    store, customer = setup_store_and_customer(member=False)
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    order, _ = setup_fulfilled_order(customer, store, [(article, 2)])

    closed = validate_success(api.close_order(order["id"], cust_headers(customer)))
    assert closed["status"] == "CLOSED"
    assert closed["points_earned"] == 0
    customer_after = get_success_data(api.get_customer(customer["id"], OPS))
    assert customer_after["points_balance"] == 0


def test_grade_capped_at_open_box_for_assembled_goods(api):
    """PRD §3.8: "Assembly work is held against the grade: when a line's
    `assembly_state` is `PARTIALLY_ASSEMBLED` or `ASSEMBLED`, its
    `effective_condition_grade` is the recorded grade capped at `OPEN_BOX` —
    a beautifully reassembled wardrobe is still an opened box"
    PRD §3.8: "A receipted line graded below `LIKE_NEW` still rolls
    `returned_qty` up but restocks nothing"

    Design: Corner/calculations/grade_capped_at_open_box_for_assembled_goods
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(store, on_hand=3, price_cents=1000)
    stock = stocks[0]
    order, order_lines = setup_fulfilled_order(customer, store, [(article, 1)])

    ret = create_return(customer, order_id=order["id"])
    ret_line = add_return_line(customer, ret["id"], article["id"], qty=1,
                               assembly_state="ASSEMBLED",
                               order_line_id=order_lines[0]["id"])
    submit_return(customer, ret["id"])
    graded = grade_line(ret["id"], ret_line["id"], "LIKE_NEW")
    assert graded["condition_grade"] == "LIKE_NEW"
    assert graded["effective_condition_grade"] == "OPEN_BOX"

    settled = settle_return(ret["id"])
    assert settled["refund_total_cents"] == 850
    assert settled["writeoff_total_cents"] == 150
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 2, "OPEN_BOX does not restock"
    line_after = get_success_data(api.get_return_line(ret_line["id"], OPS))
    assert line_after["restocked_units"] == 0


def test_no_receipt_refund_defaults_to_current_price(api):
    """PRD §3.8: "a no-receipt line's basis starts from the article's
    `lowest_price_365d_cents` when set, falling back to its current
    `price_cents`, and is then discounted by a 10 percent no-receipt penalty
    with a single rounding half-up"
    PRD §3.8: "a no-receipt line neither restocks nor rolls any order line
    up."

    Design: Corner/calculations/no_receipt_refund_defaults_to_current_price
    """
    store, member = setup_store_and_customer(member=True)
    article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
    stock = stocks[0]

    ret = create_return(member)  # no order_id -> no-receipt return
    ret_line = add_return_line(member, ret["id"], article["id"], qty=1)
    submit_return(member, ret["id"])
    grade_line(ret["id"], ret_line["id"], "LIKE_NEW")
    settled = settle_return(ret["id"])

    line_after = get_success_data(api.get_return_line(ret_line["id"], OPS))
    assert line_after["unit_basis_cents"] == 450, (
        f"basis = round_half_up(500 x 0.9) = 450, got {line_after['unit_basis_cents']}"
    )
    assert settled["refund_total_cents"] == 450
    assert settled["writeoff_total_cents"] == 0
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 5, "no-receipt lines never restock"

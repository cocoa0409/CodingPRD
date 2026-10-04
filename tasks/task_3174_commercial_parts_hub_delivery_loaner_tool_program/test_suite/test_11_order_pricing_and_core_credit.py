"""Per-line rounding versus order-level rounding, and the nested core credit."""

from test_helpers import (
    advance_order_to,
    advance_order_to_delivered,
    api_client,
    confirm_n_orders,
    confirm_order,
    create_account,
    create_hub,
    create_part,
    create_satellite,
    get_success_data,
    line_item,
    open_core_return,
    register_warranty,
    reload_account,
    reload_order,
    set_clock,
    stock,
    transit_core_return,
    write_simple_order,
)


def _rounding_account():
    """The SILVER-bound account: satellite + hub with the hub holding both parts."""
    hub = create_hub(store_code="S500", name="Rounding Hub", promise_time_minutes=90)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S400",
                                 name="Rounding Satellite",
                                 delivery_radius_miles=8.0)
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    hubassy = create_part(sku="HUBASSY-9", list_price_cents=3005, line_code="DRV")
    fog = create_part(sku="FOG-3", list_price_cents=1199, line_code="LGT")
    stock(satellite["id"], plug["id"], 10)
    stock(hub["id"], plug["id"], 20)
    stock(hub["id"], hubassy["id"], 10)
    stock(hub["id"], fog["id"], 20)
    account = create_account(satellite["id"])
    return {"satellite": satellite, "hub": hub, "plug": plug,
            "hubassy": hubassy, "fog": fog, "account": account}


def test_draft_reading_rounds_each_line_independently(api, sales_rep_headers,
                                                      parts_manager_headers):
    """PRD §3.3: "The line's `unit_price_cents` is the resolved list amount minus
    that line discount. The order's `parts_subtotal_cents` is the sum over lines
    of the line's unit price multiplied by its quantity, and the order's
    `tier_discount_cents` is the sum over lines of the line discount multiplied
    by its quantity."

    Design: Difficulty/combinatorial_formula/tier_line_price_per_line_rounding_plus_band_step
    """
    set_clock("2026-09-01T08:00:00.000Z")
    ctx = _rounding_account()
    account = ctx["account"]

    confirm_n_orders(account["id"], ctx["plug"]["id"], 3, quantity=2)

    order = write_simple_order(account["id"], ctx["hubassy"]["id"], quantity=3)
    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(ctx["hubassy"]["id"], 3),
                        line_item(ctx["fog"]["id"], 3)],
         "expected_order_version": order["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    assert updated["member_sequence"] == 4
    assert updated["pricing_band"] == "SILVER"
    assert updated["tier_discount_cents"] == 630, (
        "each line is rounded on its own: round(3005 * 0.05) * 3 + round(1199 * 0.05) * 3"
    )
    assert updated["parts_subtotal_cents"] == 11982


def test_allocation_rebases_the_discount_on_one_order_level_rounding(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.7: "From `ALLOCATED` onward it is read finally, with discount
    re-based on one order-level rounding of the summed list amount."
    PRD §3.3: "`tier_discount_cents` is recomputed as one order-level
    round-half-up of the summed list amount multiplied by the band rate, and
    `parts_subtotal_cents` becomes that summed list amount less the order-level
    discount."

    Design: Difficulty/combinatorial_formula/tier_line_price_per_line_rounding_plus_band_step
    """
    set_clock("2026-09-01T08:00:00.000Z")
    ctx = _rounding_account()
    account = ctx["account"]

    confirm_n_orders(account["id"], ctx["plug"]["id"], 3, quantity=2)

    order = write_simple_order(account["id"], ctx["hubassy"]["id"], quantity=3)
    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(ctx["hubassy"]["id"], 3),
                        line_item(ctx["fog"]["id"], 3)],
         "expected_order_version": order["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    confirmed = confirm_order(updated["id"], account["id"])
    allocated = advance_order_to(confirmed["id"], account["id"], "ALLOCATED")

    assert allocated["tier_discount_cents"] == 631, (
        "one order-level round of the 12612-cent summed list amount"
    )
    assert allocated["parts_subtotal_cents"] == 11981
    assert allocated["tier_discount_cents"] - updated["tier_discount_cents"] == 1, (
        "the rounding order changes the answer by exactly one cent on identical input"
    )


def test_line_unit_price_is_left_at_its_provisional_value_after_allocation(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.7: "the final reading deliberately leaves `unit_price_cents` at its
    provisional per-line value, so the order's subtotal and the sum of its line
    unit prices disagree after allocation. This divergence is intended, not a
    defect."

    Design: Difficulty/combinatorial_formula/tier_line_price_per_line_rounding_plus_band_step
    """
    set_clock("2026-09-01T08:00:00.000Z")
    ctx = _rounding_account()
    account = ctx["account"]

    confirm_n_orders(account["id"], ctx["plug"]["id"], 3, quantity=2)

    order = write_simple_order(account["id"], ctx["hubassy"]["id"], quantity=3)
    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(ctx["hubassy"]["id"], 3),
                        line_item(ctx["fog"]["id"], 3)],
         "expected_order_version": order["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    provisional_prices = sorted(line["unit_price_cents"] for line in updated["line_items"])
    allocated = advance_order_to(confirm_order(updated["id"], account["id"])["id"],
                                 account["id"], "ALLOCATED")

    assert sorted(line["unit_price_cents"] for line in allocated["line_items"]) == \
        provisional_prices, "unit_price_cents keeps its provisional per-line value"

    summed = sum(line["unit_price_cents"] * line["quantity"] for line in allocated["line_items"])
    assert summed != allocated["parts_subtotal_cents"], (
        "the order subtotal and the sum of its line unit prices intentionally disagree"
    )
    assert summed - allocated["parts_subtotal_cents"] == 1


def test_core_credit_pins_a_warranty_covered_return_with_no_receipt(
        api, sales_rep_headers, driver_headers, tool_crib_headers,
        credit_analyst_headers, parts_manager_headers):
    """PRD §3.7: "The lookup performs no match on `claim_reference` and no match on
    `purchase_order_id`: a credit is issued whether or not the shop can present a
    receipt, and the registration's `purchase_order_id` may legitimately be null
    for a warranty recorded without a purchase record."
    PRD §3.7: "The restocking fee is zero when the return is warranty-covered"

    Design: Difficulty/combinatorial_formula/core_credit_nested_core_portion_max_and_waterfall_cap
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S900", name="Core Hub", delivery_radius_miles=40.0,
                     promise_time_minutes=150, daily_capacity_units=800)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S800",
                                 name="Core Satellite", delivery_radius_miles=6.0)
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(hub["id"], machined["id"], 10)
    stock(hub["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000,
                             credit_terms_days=60)

    delivered = advance_order_to_delivered(
        account["id"], [line_item(machined["id"], 4), line_item(used["id"], 2)],
        driver_id="drv-core", route_code="R-CORE")

    order = delivered["order"]
    assert order["core_charge_total_cents"] == 13000
    assert order["refundable_deposit_cents"] == 2600

    register_warranty(account["id"], used["id"])
    core_return = transit_core_return(
        open_core_return(order["id"], [line_item(used["id"], 2)])["id"])
    inspected = get_success_data(
        api_client.inspect_core_return(core_return["id"], {}, tool_crib_headers))

    assert inspected["core_subtotal_cents"] == 1000
    assert inspected["warranty_covered"] is True
    assert inspected["restocking_fee_cents"] == 0
    assert inspected["credit_amount_cents"] == 4100


def test_refundable_waterfall_caps_the_second_payout_at_the_remaining_headroom(
        api, sales_rep_headers, driver_headers, tool_crib_headers,
        credit_analyst_headers):
    """PRD §3.7: "For each payout, the remaining headroom is the order's
    `refundable_deposit_cents` less its `refundable_deposit_consumed_cents`, the
    refundable portion is the smaller of the payout being requested and that
    headroom, and the order's `refundable_deposit_consumed_cents` advances by the
    amount paid. Once the ceiling is exhausted, further payouts are zero, never
    negative."

    Design: Difficulty/combinatorial_formula/core_credit_nested_core_portion_max_and_waterfall_cap
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S900", name="Core Hub", delivery_radius_miles=40.0,
                     promise_time_minutes=150, daily_capacity_units=800)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S800",
                                 name="Core Satellite", delivery_radius_miles=6.0)
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(hub["id"], machined["id"], 10)
    stock(hub["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000,
                             credit_terms_days=60)

    delivered = advance_order_to_delivered(
        account["id"], [line_item(machined["id"], 4), line_item(used["id"], 2)],
        driver_id="drv-cap", route_code="R-CAP")
    order = delivered["order"]

    first = transit_core_return(
        open_core_return(order["id"], [line_item(machined["id"], 4)])["id"])
    first_inspected = get_success_data(
        api_client.inspect_core_return(first["id"], {}, tool_crib_headers))
    get_success_data(api_client.credit_core_return(first["id"], {},
                                                   credit_analyst_headers))

    assert first_inspected["credit_amount_cents"] == 8520, (
        "refundable 2400 plus the 7200 core-charge portion net of a 1080 restocking fee"
    )

    second = transit_core_return(
        open_core_return(order["id"], [line_item(used["id"], 2)])["id"])
    second_inspected = get_success_data(
        api_client.inspect_core_return(second["id"], {}, tool_crib_headers))
    # PRD 3.7: "the order's `refundable_deposit_consumed_cents` advances by the
    # amount paid", and posting the credit is what advances it.
    get_success_data(api_client.credit_core_return(second["id"], {},
                                                   credit_analyst_headers))

    # The second core line's subtotal is 1000, so its computed refundable
    # portion is 200; only 200 of the 2600 ceiling is left once the first payout
    # has consumed 2400, and the core-charge portion is still max(600, 3900) =
    # 3900 net of a 585 restocking fee.  200 + 3900 - 585 = 3515.
    after = reload_order(order["id"])
    assert second_inspected["credit_amount_cents"] == 3515
    # PRD 3.7: "the order's `refundable_deposit_consumed_cents` advances by the
    # amount paid", so the two payouts (2400 and 200) draw 2600 of the order's
    # 2600-cent ceiling -- the second payout is what exhausts it.
    assert after["refundable_deposit_consumed_cents"] == 2600, (
        "both payouts together consumed exactly the order's refundable ceiling"
    )


def test_ordered_quantity_credit_is_not_the_waterfall_capped_payout(
        api, sales_rep_headers, tool_crib_headers, credit_analyst_headers):
    """PRD §3.7: "That entitlement figure is not capped; it is the waterfall's
    ceiling that caps the actual payout."

    Design: Difficulty/combinatorial_formula/core_credit_nested_core_portion_max_and_waterfall_cap
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S900", name="Core Hub", delivery_radius_miles=40.0,
                     promise_time_minutes=150, daily_capacity_units=800)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S800",
                                 name="Core Satellite", delivery_radius_miles=6.0)
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(hub["id"], machined["id"], 10)
    stock(hub["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000,
                             credit_terms_days=60)

    delivered = advance_order_to_delivered(
        account["id"], [line_item(machined["id"], 4), line_item(used["id"], 2)],
        driver_id="drv-ent", route_code="R-ENT")
    order = delivered["order"]

    first = transit_core_return(
        open_core_return(order["id"], [line_item(machined["id"], 4)])["id"])
    first_inspected = get_success_data(
        api_client.inspect_core_return(first["id"], {}, tool_crib_headers))
    get_success_data(api_client.credit_core_return(first["id"], {},
                                                   credit_analyst_headers))

    second = transit_core_return(
        open_core_return(order["id"], [line_item(used["id"], 2)])["id"])
    second_inspected = get_success_data(
        api_client.inspect_core_return(second["id"], {}, tool_crib_headers))

    # PRD 3.7: the first line's 12000-cent core subtotal pays a 2400 refundable
    # portion plus its 7200 core-charge portion net of a 1080 restocking fee
    # (8520), the second line's 1000-cent subtotal pays 200 plus 3900 net of 585
    # (3515), and the waterfall's ceiling of 2600 is what caps the pair.
    paid = first_inspected["credit_amount_cents"] + second_inspected["credit_amount_cents"]
    assert first_inspected["credit_amount_cents"] == 8520
    assert second_inspected["credit_amount_cents"] == 3515
    assert paid == 12035, "the two dwells paid out 8520 and 3515"
    assert 13000 > paid, (
        "the entitled figure by ordered quantity is 13000, strictly larger than what was paid"
    )
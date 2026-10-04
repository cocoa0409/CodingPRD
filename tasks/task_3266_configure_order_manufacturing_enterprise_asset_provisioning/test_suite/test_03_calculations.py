"""Lead time, pricing, and the promised ship date: provisional vs committed
variants, per-line-then-sum rounding, tiered buffers, and build-hour floor
precision."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_job,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_configuration,
    create_validated_configuration,
    create_order_with_lines,
    get_order_build_jobs,
    submit_order,
    make_customer_user_headers,
    get_success_data,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]


def test_order_pricing_round_per_line_then_sum(api):
    """PRD §3.3: "Only after every line has been individually rounded does the
    order aggregate: `total_cents` is the sum of the per-line rounded totals,
    and `discount_cents` is the sum of the pre-discount line amounts minus
    `total_cents`. Summing first and rounding once at the order level is
    forbidden; the pinned order is round per line, then sum."

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
    """
    account = create_account(company_name="A4", account_tier="PREMIER",
                             credit_limit_cents=10_000_000)
    chassis = create_chassis(model_code="L4", base_price_cents=66_671, build_duration_hours=24)
    cpca = create_component(sku="CPCA", price_cents=33_334, lead_time_days=5, stock_on_hand=100)
    rmab = create_component(sku="RMAB", kind="MEMORY", price_cents=33_346,
                            lead_time_days=5, stock_on_hand=100)
    add_allowed_rule(chassis["id"], cpca["id"])
    add_allowed_rule(chassis["id"], rmab["id"])
    cf1 = create_validated_configuration(account, chassis["id"],
                                         [{"component_id": cpca["id"], "qty": 1}])
    cf2 = create_validated_configuration(account, chassis["id"],
                                         [{"component_id": rmab["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account,
        [
            {"configuration_id": cf1["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"},
            {"configuration_id": cf2["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"},
        ],
        po_number="PO-4",
    )
    submit_order(account, order, cf1["version"])
    line_a = get_success_data(api.get_order_line(lines[0]["id"], MANAGER))
    line_b = get_success_data(api.get_order_line(lines[1]["id"], MANAGER))
    assert line_a["line_total_cents"] == 92_005
    assert line_b["line_total_cents"] == 92_016
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["total_cents"] == 184_021
    # pre-discount sum 100_005 + 100_017 = 200_022; 200_022 - 184_021 = 16_001
    assert order_after["discount_cents"] == 16_001


def test_order_pricing_standard_tier_no_discount(api):
    """PRD §3.3: "A discount percentage is then read from the account's tier
    table: `STANDARD` accounts receive no discount, `PREMIER` accounts receive
    8 percent, and `FEDERAL` accounts receive 12 percent."

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
    """
    account = create_account(account_tier="STANDARD")
    chassis = create_chassis(base_price_cents=100_000)
    cpu = create_component(price_cents=20_000, stock_on_hand=10)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["total_cents"] == 120_000
    assert order_after["discount_cents"] == 0


def test_promised_ship_date_tiered_buffer_nonlinear(api):
    """PRD §3.3: "A buffer is then added: `FEDERAL` accounts receive two
    buffer days, `PREMIER` accounts receive one, and `STANDARD` accounts
    receive none; additionally, when any single line of the order carries a
    `qty` of 50 units or more — the bulk threshold — three further buffer days
    are added."
    PRD §2.7: "At server startup the logical clock is initialized to exactly
    `2026-09-01T00:00:00Z` and the server must not fall back to wall-clock time
    under any circumstance."

    Design: Difficulty/combinatorial_formula/promised_ship_date_tiered_buffer_nonlinear
    """
    account = create_account(company_name="A5", account_tier="PREMIER",
                             credit_limit_cents=100_000_000)
    chassis = create_chassis(model_code="L5", base_price_cents=100_000, build_duration_hours=24)
    cpu = create_component(sku="CPU5", price_cents=10_000, lead_time_days=3, stock_on_hand=1_000)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 50, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-5",
    )
    submit_order(account, order, config["version"])
    config_after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert config_after["committed_lead_time_days"] == 1
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["promised_ship_date"] == "2026-09-06T00:00:00Z"
    assert order_after["build_status"] == "SUBMITTED"


def test_promised_ship_date_just_below_bulk_threshold(api):
    """PRD §3.3: "A buffer is then added: `FEDERAL` accounts receive two
    buffer days, `PREMIER` accounts receive one, and `STANDARD` accounts
    receive none; additionally, when any single line of the order carries a
    `qty` of 50 units or more — the bulk threshold — three further buffer days
    are added."
    PRD §2.7: "At server startup the logical clock is initialized to exactly
    `2026-09-01T00:00:00Z` and the server must not fall back to wall-clock time
    under any circumstance."

    Design: Difficulty/combinatorial_formula/promised_ship_date_tiered_buffer_nonlinear
    """
    # Same PREMIER profile at qty 49: one day below the bulk threshold, so the
    # buffer is 1 (PREMIER) with no bulk addition — landing 2026-09-03.
    account = create_account(account_tier="PREMIER", credit_limit_cents=100_000_000)
    chassis = create_chassis(base_price_cents=100_000, build_duration_hours=24)
    cpu = create_component(price_cents=10_000, lead_time_days=3, stock_on_hand=1_000)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 49, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["promised_ship_date"] == "2026-09-03T00:00:00Z"


def test_promised_ship_date_standard_tier_no_buffer(api):
    """PRD §3.3: "`FEDERAL` accounts receive two buffer days, `PREMIER`
    accounts receive one, and `STANDARD` accounts receive none; additionally,
    when any single line of the order carries a `qty` of 50 units or more —
    the bulk threshold — three further buffer days are added."
    PRD §2.7: "At server startup the logical clock is initialized to exactly
    `2026-09-01T00:00:00Z` and the server must not fall back to wall-clock time
    under any circumstance."

    Design: Corner/calculations/promised_ship_date_standard_tier_no_buffer
    """
    account = create_account(company_name="CC3", account_tier="STANDARD",
                             credit_limit_cents=100_000_000)
    chassis = create_chassis(model_code="CCL3", base_price_cents=100_000, build_duration_hours=24)
    cpu = create_component(sku="CCC3", price_cents=20_000, lead_time_days=4, stock_on_hand=100)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 49, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-CC3",
    )
    submit_order(account, order, config["version"])
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["promised_ship_date"] == "2026-09-02T00:00:00Z"


def test_build_hours_floor_precision(api):
    """PRD §2.5: "Lead times, response SLAs, and build durations are expressed
    as integer hours or integer days; where a build duration in hours is
    converted into days, the conversion divides by the 24-hour day and floors
    the result to a whole day."

    Design: Corner/calculations/build_hours_floor_precision
    """
    account = create_account(company_name="CC1")
    chassis = create_chassis(model_code="CCL1", base_price_cents=100_000, build_duration_hours=30)
    cpu = create_component(sku="CCC1", price_cents=20_000, lead_time_days=3, stock_on_hand=10)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    # In stock -> component term 0; floor(30/24) == 1.
    assert config["lead_time_estimate_days"] == 1

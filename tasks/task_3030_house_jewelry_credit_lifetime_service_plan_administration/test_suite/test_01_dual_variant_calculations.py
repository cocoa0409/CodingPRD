"""Dual-variant calculations where two faithful readings diverge by cents.

Each test pins the variant the PRD makes authoritative, plus the second
interpretation's value, so an implementation that picks the wrong variant is
caught at the cent.
"""

from test_helpers import (
    MANAGER,
    get_success_data,
    reset_clock,
    setup_active_registration,
    setup_customer,
    setup_design_order,
    setup_store,
    setup_with_origin_credit,
    validate_success,
)


def _active_registration_graph():
    return setup_active_registration()


def _customer_on_file():
    return setup_customer()


def _origin_with_bonus_credit():
    return setup_with_origin_credit()


def _commission_in_production_with_three_revisions():
    return setup_design_order(estimate_amount_cents=250_000, deposit_pct=0.40,
                              revisions=3, approve=True, in_production=True)


def test_repair_liability_is_pinned_with_the_net_reserve_reading(api, store_manager_headers):
    """PRD §2.7: "The chain's default posture is the `NET_RESERVE` reading. A warranty reserve is taken on parts first: the reserve is `declared_parts_cents` multiplied by `WARRANTY_RESERVE_PCT` (0.07), rounded half up."
    PRD §2.7: "On the shared worked example the two readings diverge: `declared_parts_cents` of 40,000, `declared_labor_cents` of 15,000, `stone_limit_labor_cents` of 25,000, `stone_limit_parts_cents` of 60,000, and `declared_loss_liability_cents` of 5,000 on a valid plan give a `NET_RESERVE` store-absorbed liability of 35,000 cents"

    Design: Difficulty/dual_variant_calc/repair_liability_net_reserve_vs_gross_reserve_divergence
    """
    customer, store, diamond, bundle, purchase, registration = _active_registration_graph()
    repair = validate_success(api.create_repair({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": "SETTING",
        "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000,
        "declared_loss_liability_cents": 5_000,
    }, store_manager_headers), 201)

    assert repair["loss_liability_cents"] == 35_000, (
        "the NET_RESERVE reading prices the liability at 35000"
    )
    assert repair["store_absorbed_cents"] == 35_000
    assert repair["reserve_cents"] == 2_800, "the reserve is taken on parts alone"
    assert repair["repair_status"] == "INTAKE"
    assert repair["loss_liability_cents"] != 38_850, (
        "the GROSS_RESERVE reading would give 38850; the two differ by 3850 cents"
    )


def test_repair_parts_split_is_evaluated_before_any_reserve_term(api, store_manager_headers):
    """PRD §2.7: "The parts split is evaluated before any reserve term. `insurance_parts_cents` is the smaller of covered parts and `stone_limit_parts_cents`. `customer_parts_cents` is `declared_parts_cents` minus `insurance_parts_cents`."
    PRD §2.7: "On the worked example above, `insurance_parts_cents` is 37,200, `customer_parts_cents` is 2,800, and `customer_labor_cents` is 15,000."

    Design: Difficulty/dual_variant_calc/repair_liability_net_reserve_vs_gross_reserve_divergence
    """
    customer, store, diamond, bundle, purchase, registration = _active_registration_graph()
    repair = validate_success(api.create_repair({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": "SETTING",
        "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000,
        "declared_loss_liability_cents": 5_000,
    }, store_manager_headers), 201)

    assert repair["insurance_parts_cents"] == 37_200
    assert repair["customer_parts_cents"] == 2_800
    assert repair["customer_labor_cents"] == 15_000
    assert repair["insurance_parts_cents"] + repair["customer_parts_cents"] == 40_000, (
        "the parts split partitions the declared parts cost"
    )


def test_statement_rollup_selects_the_tier_on_the_aggregate(api, customer_service_headers):
    """PRD §2.11: "Worked reference with two billable lines of 250,000 and 260,000 cents at a `billable_pct` of 1.0: `SUM_THEN_TIER` gives a subtotal of 510,000, a 0.03 tier, and a balance of 525,300; `PER_LINE_TIER` gives 255,000 for the first line, 267,800 for the second, and a balance of 522,800 — a 2,500 cent divergence for identical inputs."
    PRD §2.11: "Under the `SUM_THEN_TIER` reading, each billable line's amount is multiplied by its `billable_pct` and rounded half up, the results are summed into a subtotal, a tier fee percentage is selected from that aggregate"

    Design: Difficulty/dual_variant_calc/statement_rollup_sum_then_tier_vs_per_line_tier_divergence
    """
    reset_clock("2026-09-01T00:00:00Z")
    store = setup_store()
    customer = _customer_on_file()
    statement = get_success_data(api.create_billing_statement({
        "customer_id": customer["id"],
        "statement_period": "2026-09",
        "lines": [
            {"amount_cents": 250_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
            {"amount_cents": 260_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
        ],
    }, customer_service_headers), 201)

    assert statement["statement_balance_cents"] == 525_300, (
        "the aggregate crosses the 500,000 boundary and lifts every line to 3%"
    )
    assert statement["statement_balance_cents"] != 522_800, (
        "the PER_LINE_TIER reading would give 522800, 2500 cents lower"
    )
    assert statement["min_payment_due_cents"] == 5_000, "the floor governs small statements"
    assert statement["statement_status"] == "OPEN"
    del store


def test_statement_rollup_floor_binds_when_no_payment_was_allocated(api, customer_service_headers):
    """PRD §2.11: "`min_payment_due_cents` is the greater of the `MIN_FLOOR_CENTS` floor (5,000 cents) and the sum, over the buckets that received an allocation, of that allocation multiplied by its `min_base_pct`, each rounded half up."
    PRD §2.11: "so the floor of 5,000 cents governs small statements."

    Design: Difficulty/dual_variant_calc/statement_rollup_sum_then_tier_vs_per_line_tier_divergence
    """
    reset_clock("2026-09-01T00:00:00Z")
    setup_store()
    customer = _customer_on_file()
    statement = get_success_data(api.create_billing_statement({
        "customer_id": customer["id"],
        "statement_period": "2026-10",
        "lines": [
            {"amount_cents": 250_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
        ],
    }, customer_service_headers), 201)

    assert set(statement["bucket_totals_cents"]) == {
        "PROMOTIONAL", "CUSTOM_DESIGN", "RETAIL"}, (
        "PRD §2.11 fixes the storage form as an object keyed by the three buckets"
    )
    assert all(v == 0 for v in statement["bucket_totals_cents"].values()), (
        "no payment was supplied, so no bucket received an allocation"
    )
    assert statement["min_payment_due_cents"] == 5_000
    assert statement["statement_status"] == "OPEN"
    assert statement["statement_balance_cents"] == 255_000, (
        "a single 250,000 line at 1.0 takes the 0.02 tier in either reading"
    )


def test_trade_up_credit_uses_one_rounding_over_the_combined_base(api, sales_associate_headers):
    """PRD §2.8: "The credit itself is `TRADE_UP_CREDIT_PCT` (0.85) of the credited base, rounded half up — this single rounding over the combined base is the `SINGLE_ROUND` reading, and it is the authoritative value that lands in `trade_up_credit_cents`."
    PRD §2.8: "an origin ticket of 450,018 with an existing credit of 10,050 gives a bonus of 1,005, a credited base of 451,023, and a `SINGLE_ROUND` credit of 383,370 (against 383,369 under per-component rounding)."

    Design: Difficulty/combinatorial_formula/trade_up_credit_single_round_vs_per_component_round
    """
    reset_clock("2026-09-01T00:00:00Z")
    customer, store, origin, new_purchase = _origin_with_bonus_credit()
    preview = validate_success(
        api.preview_trade_up(new_purchase["id"], sales_associate_headers), 200)

    assert preview["trade_up_credit_cents"] == 383_370, (
        "the single rounding over the combined credited base is authoritative"
    )
    assert preview["trade_up_credit_cents"] != 383_369, (
        "per-component rounding would give 383369, one cent lower"
    )
    assert preview["net_amount_cents"] == 900_100 - 383_370


def test_trade_up_floor_is_twice_the_origin_ticket_and_the_ticket_clears_it(
        api, sales_associate_headers):
    """PRD §2.8: "`trade_up_floor_cents` is twice the origin purchase's `base_price_cents`."
    PRD §2.8: "a 900,100 cent ticket against a 450,018 cent origin gives a cap of 900,036, a credit of 383,370 (which is below the cap), a net amount of 516,730, and — with no bundle — a balance due of 516,730"

    Design: Difficulty/combinatorial_formula/trade_up_credit_single_round_vs_per_component_round
    """
    reset_clock("2026-09-01T00:00:00Z")
    customer, store, origin, new_purchase = _origin_with_bonus_credit()
    preview = validate_success(
        api.preview_trade_up(new_purchase["id"], sales_associate_headers), 200)

    assert preview["trade_up_floor_cents"] == 900_036
    assert new_purchase["base_price_cents"] - preview["trade_up_floor_cents"] == 64, (
        "the ticket clears the floor by exactly 64 cents"
    )
    assert preview["balance_due_cents"] == 516_730
    assert preview["trade_up_credit_cents"] <= 2 * 450_018, "the credit is capped at twice the origin ticket"


def test_design_cancellation_fee_follows_the_pinned_evaluation_order(api, store_manager_headers):
    """PRD §3.6: "The cancellation fee is the greater of two candidates: when the order's `revision_count` has reached 3 or more, the fee is those costs incurred; otherwise it is the whole deposit."
    PRD §2.8: "a 250,000 cent estimate at a 0.40 percentage stamps a 100,000 cent deposit"

    Design: Difficulty/combinatorial_formula/design_cancellation_fee_depends_on_deposit_and_revision_order
    """
    reset_clock("2026-09-01T00:00:00Z")
    customer, store, order = _commission_in_production_with_three_revisions()
    cancelled = validate_success(api.cancel_custom_design_order(
        order["id"], store_manager_headers), 200)

    assert cancelled["deposit_cents"] == 100_000, (
        "round(250000 x 0.40) is stamped at submit and never recomputed"
    )
    assert cancelled["revision_fee_cents"] == 2_500, (
        "only the third revision is charged, at 2,500 cents"
    )
    assert cancelled["cancellation_fee_cents"] == (
        cancelled["deposit_cents"] + cancelled["revision_fee_cents"]
    ), (
        "with three revisions the fee is the costs incurred: the deposit plus "
        "the accumulated revision fee, less the recovered material value"
    )
    assert cancelled["non_refundable_deposit_cents"] == 100_000
    assert cancelled["refundable_deposit_cents"] == 0
    assert cancelled["design_status"] == "CANCELLED"


def test_cancellation_out_of_production_forfeits_the_stamped_deposit(api, store_manager_headers):
    """PRD §3.6: "From `IN_PRODUCTION` the commission still cancels, but the deposit is held: `non_refundable_deposit_cents` becomes the full `deposit_cents`, `refundable_deposit_cents` becomes 0, and `cancellation_fee_cents` becomes the result of `non_refundable_deposit_forfeit`."
    PRD §3.6: "from the third onward an additional 2,500 cents (`CAD_REVISION_FEE_CENTS`) is added to `revision_fee_cents`"

    Design: Difficulty/combinatorial_formula/design_cancellation_fee_depends_on_deposit_and_revision_order
    """
    reset_clock("2026-09-01T00:00:00Z")
    customer, store, order = _commission_in_production_with_three_revisions()
    before = get_success_data(api.get_custom_design_order(order["id"], MANAGER))
    assert before["design_status"] == "IN_PRODUCTION"
    assert before["revision_count"] == 3

    cancelled = validate_success(api.cancel_custom_design_order(
        order["id"], MANAGER), 200)
    assert cancelled["design_status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] != 0, (
        "a fee of 0 is only correct before the design reaches IN_PRODUCTION"
    )
    assert cancelled["refundable_deposit_cents"] == 0
    assert cancelled["deposit_cents"] == 100_000
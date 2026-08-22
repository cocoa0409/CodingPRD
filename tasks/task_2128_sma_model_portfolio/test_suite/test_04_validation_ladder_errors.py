"""Rejection paths of the fixed check ladder, and the state each one leaves behind."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocate_block,
    approve_harvest,
    create_block,
    create_draft_version,
    create_fee_invoice_payload,
    create_harvest_proposal,
    create_harvest_proposal_payload,
    create_invoice,
    create_model,
    create_restriction_payload,
    create_securities,
    evaluate_drift,
    execute_block,
    execute_block_payload,
    execute_harvest,
    get_account,
    get_block,
    get_model_version,
    get_trade_order,
    issue_invoice,
    list_tax_lots,
    list_trade_orders,
    mark_invoice_delinquent,
    rebalance,
    set_clock,
    set_sleeves,
    setup_account_pending_implementation,
    setup_drifted_account_with_orders,
    setup_funded_account,
    setup_harvest_ready_account,
    sleeve,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["portfolio_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_officer_headers"]

ALFA_ONLY = [("ALFA", "Alfa Industrials", 10_000)]
ALFA_SLEEVE = [("ALFA", 10000)]


def _rows(response):
    data, _meta = validate_paginated(response)
    return data


def _single(rows):
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    return rows[0]


def _account_with_one_buy_order(cash_cents=1_000_000):
    """Fund an all-ALFA account, drive it DRIFTED and generate its single BUY."""
    env = setup_funded_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        model_overrides={"drift_threshold_bps": 10},
        account_overrides={"cash_reserve_bps": 100},
        cash_cents=cash_cents,
    )
    env["account"] = evaluate_drift(
        env["account"]["id"], env["sponsor"]["id"], "SETTLED"
    )
    env["rebalance_result"] = rebalance(env["account"]["id"], env["sponsor"]["id"])
    env["order"] = get_trade_order(env["rebalance_result"]["trade_order_ids"][0])
    return env


def test_max_position_restriction_missing_its_cap_is_a_request_shape_failure(api):
    """PRD §3.4: "A `MAX_POSITION` restriction must carry a `max_position_bps` between 1 and 10000 inclusive; the other two types must not carry one at all, and either mistake is a request-shape failure."

    Design: Corner/validations/max_position_restriction_without_cap_returns_invalid_request
    """
    env = setup_funded_account(securities=ALFA_ONLY, sleeves=ALFA_SLEEVE)
    account_id = env["account"]["id"]

    validate_error(
        api.create_restriction(
            create_restriction_payload(
                account_id, env["securities"]["ALFA"]["id"], "MAX_POSITION"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    assert _rows(api.list_restrictions(COMPLIANCE, params={"account_id": account_id})) == []


def test_block_members_spanning_two_securities_are_refused(api):
    """PRD §3.7: "The list must be non-empty, every listed order must be in status `PROPOSED`, and all of them must share one `security_id` and one `side`; any deviation is refused with `ERR_BLOCK_COMPOSITION_INVALID`."

    Design: Corner/validations/block_mixing_two_securities_returns_composition_invalid
    """
    env = setup_drifted_account_with_orders()
    alfa_order, beta_order, ceta_order = env["orders"]

    assert (alfa_order["side"], alfa_order["shares"]) == ("SELL", 13)
    assert (beta_order["side"], beta_order["shares"]) == ("SELL", 15)
    assert (ceta_order["side"], ceta_order["shares"]) == ("BUY", 980)

    validate_error(
        api.create_block(
            {"trade_order_ids": [alfa_order["id"], beta_order["id"]]},
            env["sponsor_headers"],
        ),
        ApiErrorId.ERR_BLOCK_COMPOSITION_INVALID.value,
    )

    for order_id in (alfa_order["id"], beta_order["id"]):
        order = get_trade_order(order_id)
        assert order["status"] == "PROPOSED"
        assert order["block_id"] is None

    assert _rows(api.list_blocks(ADMIN)) == []


def test_reported_fill_above_the_requested_share_count_is_refused(api):
    """PRD §3.7: "The admin reports `filled_shares` — which must be at least 1 and at most the block's `requested_shares`, on pain of `ERR_FILL_EXCEEDS_REQUEST` — and the `avg_fill_price_cents` at which the fill was struck, and the block moves `OPEN → FILLED` with `executed_at` stamped at the clock instant."

    Design: Corner/validations/execute_with_fill_above_requested_returns_fill_exceeds_request
    """
    env = _account_with_one_buy_order()
    order = env["order"]
    assert (order["side"], order["shares"]) == ("BUY", 99)

    block = create_block([order["id"]], env["sponsor"]["id"])
    assert block["requested_shares"] == 99

    validate_error(
        api.execute_block(block["id"], execute_block_payload(200, 10_000), ADMIN),
        ApiErrorId.ERR_FILL_EXCEEDS_REQUEST.value,
    )

    block = get_block(block["id"])
    assert block["status"] == "OPEN"
    assert block["filled_shares"] == 0
    assert block["avg_fill_price_cents"] is None
    assert block["requested_shares"] == 99


def test_billing_periods_collide_on_overlap_but_adjacency_is_legal(api):
    """PRD §2.10: "**Fee-invoice billing periods** use the same half-open convention, running from `period_start` inclusive to `period_end` exclusive, on the account key." PRD §3.9: "Each tier's fee is then prorated over the period and rounded **independently**: `tier1_fee_cents`, `tier2_fee_cents` and `tier3_fee_cents` are each that tier's slice multiplied by its rate in basis points, multiplied by `billing_days`, divided by 10000 and again by 365, then rounded half up to whole cents." "`sponsor_share_cents` is `gross_fee_cents` multiplied by the sponsor's `revenue_share_bps`, divided by 10000, rounded half up. `platform_share_cents` is `gross_fee_cents` multiplied by the platform's own fixed 500-basis-point cut, divided by 10000, rounded half up. `manager_share_cents` is then simply what is left: `gross_fee_cents` minus the sponsor's share minus the platform's share."

    Design: Corner/validations/overlapping_billing_period_rejected_but_adjacent_period_accepted
    """
    env = setup_funded_account(securities=ALFA_ONLY, sleeves=ALFA_SLEEVE)
    account_id = env["account"]["id"]

    create_invoice(
        account_id,
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
        average_daily_value_cents=30_000_000,
    )

    validate_error(
        api.create_fee_invoice(
            create_fee_invoice_payload(
                account_id,
                period_start="2026-03-01T00:00:00Z",
                period_end="2026-06-01T00:00:00Z",
                average_daily_value_cents=30_000_000,
            ),
            BILLING,
        ),
        ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value,
    )

    adjacent = validate_success(
        api.create_fee_invoice(
            create_fee_invoice_payload(
                account_id,
                period_start="2026-04-01T00:00:00Z",
                period_end="2026-07-01T00:00:00Z",
                average_daily_value_cents=30_000_000,
            ),
            BILLING,
        ),
        201,
    )
    assert adjacent["billing_days"] == 91
    assert adjacent["tier1_fee_cents"] == 56096
    assert adjacent["tier2_fee_cents"] == 9973
    assert adjacent["tier3_fee_cents"] == 0
    assert adjacent["gross_fee_cents"] == 66069
    assert adjacent["sponsor_share_cents"] == 22021
    assert adjacent["platform_share_cents"] == 3303
    assert adjacent["manager_share_cents"] == 40745

    assert len(_rows(api.list_fee_invoices(BILLING, params={"account_id": account_id}))) == 2


def test_delinquency_one_day_short_of_the_payment_term_is_refused(api):
    """PRD §3.9: "**Delinquency** moves the account's billing dimension `INVOICED → DELINQUENT` and requires that the payment term has run out: the current clock instant must be at or after the invoice's `period_end` plus thirty days, and an earlier attempt is refused with `ERR_PAYMENT_TERM_NOT_ELAPSED`. The invoice itself stays `ISSUED` through delinquency."

    Design: Corner/validations/marking_delinquent_before_the_payment_term_returns_term_not_elapsed
    """
    set_clock("2026-04-30T00:00:00Z")
    env = setup_funded_account(securities=ALFA_ONLY, sleeves=ALFA_SLEEVE)
    account_id = env["account"]["id"]

    invoice = create_invoice(
        account_id,
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
        average_daily_value_cents=30_000_000,
    )
    assert invoice["gross_fee_cents"] == 65342
    issue_invoice(invoice["id"])

    validate_error(
        api.mark_fee_invoice_delinquent(invoice["id"], BILLING),
        ApiErrorId.ERR_PAYMENT_TERM_NOT_ELAPSED.value,
    )
    assert get_account(account_id)["billing_status"] == "INVOICED"

    set_clock("2026-05-01T00:00:00Z")
    mark_invoice_delinquent(invoice["id"])
    assert get_account(account_id)["billing_status"] == "DELINQUENT"

    final = validate_success(api.get_fee_invoice(invoice["id"], BILLING))
    assert final["status"] == "ISSUED"
    assert final["gross_fee_cents"] == 65342


def test_allocation_costing_more_than_the_account_holds_books_nothing(api):
    """PRD §3.7: "Before any of this is committed, each `BUY` member's account must hold enough `cash_cents` to cover its own allocation cost, failing which the operation is refused with `ERR_INSUFFICIENT_CASH`; and no member's account may be in `SUSPENDED`."

    Design: Corner/validations/allocation_costing_more_than_account_cash_returns_insufficient_cash
    """
    env = _account_with_one_buy_order()
    order = env["order"]
    assert (order["side"], order["shares"]) == ("BUY", 99)

    block = create_block([order["id"]], env["sponsor"]["id"])
    block = execute_block(block["id"], 99, 20_000)
    assert block["status"] == "FILLED"

    validate_error(
        api.allocate_block(block["id"], ADMIN),
        ApiErrorId.ERR_INSUFFICIENT_CASH.value,
    )

    block = get_block(block["id"])
    assert block["status"] == "FILLED"
    assert block["allocated_shares"] == 0
    assert block["unallocated_shares"] == 99

    order = get_trade_order(order["id"])
    assert order["status"] == "BLOCKED"
    assert order["allocated_shares"] == 0
    assert order["fill_price_cents"] is None

    account = get_account(env["account"]["id"])
    assert account["cash_cents"] == 1_000_000
    assert list_tax_lots(account_id=account["id"]) == []


def test_harvest_for_more_shares_than_held_reports_shares_before_budget(api):
    """PRD §2.6: "And a harvest proposal that both requests more shares than the account holds and would blow the harvest budget reports `ERR_INSUFFICIENT_SHARES`, because rung 25 precedes rung 26 — the budget cannot be evaluated until the disposal walk has completed anyway." PRD §3.8: "If the account's `OPEN` lots of that security cannot cover the requested `shares`, the proposal is refused with `ERR_INSUFFICIENT_SHARES`; and the account's `realized_loss_ytd_cents` plus `proposed_loss_cents` must not exceed its `harvest_budget_cents`, on pain of `ERR_HARVEST_BUDGET_EXCEEDED`."

    Design: Corner/validations/harvest_for_more_shares_than_held_returns_insufficient_shares
    """
    env = setup_harvest_ready_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        harvest_budget_cents=0,
        positions=[("ALFA", 50, 600_000)],
    )
    account_id = env["account"]["id"]
    version_before = get_account(account_id)["version"]

    validate_error(
        api.create_harvest_proposal(
            create_harvest_proposal_payload(
                account_id, env["securities"]["ALFA"]["id"], 100, version_before
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_INSUFFICIENT_SHARES.value,
    )

    assert _rows(
        api.list_harvest_proposals(MANAGER, params={"account_id": account_id})
    ) == []
    assert get_account(account_id)["version"] == version_before


def test_submitting_sleeves_that_do_not_sum_to_ten_thousand_is_refused(api):
    """PRD §3.2: "It is refused with `ERR_WEIGHTS_NOT_BALANCED` unless the version carries at least one sleeve **and** its `total_target_weight_bps` equals exactly 10000. No tolerance band applies to this comparison: 9999 and 10001 are both rejected."

    Design: Corner/validations/submitting_unbalanced_sleeves_returns_weights_not_balanced
    """
    securities = create_securities(
        [("ALFA", "Alfa Industrials", 10_000), ("BETA", "Beta Materials", 5_000)]
    )
    model = create_model()
    version = create_draft_version(model["id"])
    version = set_sleeves(
        version["id"],
        [
            sleeve(securities["ALFA"]["id"], 6000),
            sleeve(securities["BETA"]["id"], 3000),
        ],
    )
    assert version["total_target_weight_bps"] == 9000
    assert version["sleeve_count"] == 2

    validate_error(
        api.submit_model_version(version["id"], MANAGER),
        ApiErrorId.ERR_WEIGHTS_NOT_BALANCED.value,
    )

    stored = get_model_version(version["id"])
    assert stored["status"] == "DRAFT"
    assert stored["submitted_by_user_id"] is None


def test_unwind_is_blocked_once_a_lot_the_block_opened_has_been_closed(api):
    """PRD §3.7: "It is permitted only while every tax lot that this block's allocation opened is still in status `OPEN`; if any of them has since been disposed, the reversal would have nothing coherent to undo and the request is refused with `ERR_UNWIND_BLOCKED`."

    Design: Corner/validations/unwinding_a_block_whose_lot_was_already_closed_returns_unwind_blocked
    """
    env = setup_funded_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        model_overrides={"drift_threshold_bps": 10},
        account_overrides={
            "cash_reserve_bps": 100,
            "tax_overlay_enabled": True,
            "harvest_budget_cents": 0,
        },
        cash_cents=1_000_000,
    )
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    evaluate_drift(account_id, sponsor_id, "SETTLED")
    result = rebalance(account_id, sponsor_id)
    order_id = result["trade_order_ids"][0]

    block = create_block([order_id], sponsor_id)
    execute_block(block["id"], 99, 10_000)
    allocate_block(block["id"])

    set_clock("2026-09-01T00:00:00Z")

    proposal = create_harvest_proposal(account_id, alfa_id, 99)
    assert proposal["proposed_loss_cents"] == 0
    approve_harvest(proposal["id"])
    executed = execute_harvest(proposal["id"])
    assert executed["realized_loss_cents"] == 0

    validate_error(
        api.unwind_block(block["id"], ADMIN),
        ApiErrorId.ERR_UNWIND_BLOCKED.value,
    )

    block = get_block(block["id"])
    assert block["status"] == "ALLOCATED"
    assert block["allocated_shares"] == 99
    assert block["unallocated_shares"] == 0

    order = get_trade_order(order_id)
    assert order["status"] == "ALLOCATED"
    assert order["allocated_shares"] == 99

    account = get_account(account_id)
    assert account["cash_cents"] == 1_000_000
    assert account["realized_loss_ytd_cents"] == 0


def test_implementation_under_the_sponsor_minimum_is_refused(api):
    """PRD §3.5: "It further requires the account's `market_value_cents` to be at least its sponsor's `min_account_value_cents`, failing which it is refused with `ERR_BELOW_SPONSOR_MINIMUM`."

    Design: Corner/validations/implementation_below_the_sponsor_minimum_returns_below_sponsor_minimum
    """
    env = setup_account_pending_implementation(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        successor_sleeves=ALFA_SLEEVE,
        sponsor_overrides={
            "implementation_lag_days": 2,
            "min_account_value_cents": 100_000_000,
        },
        account_overrides={"cash_reserve_bps": 100},
        cash_cents=1_000_000,
    )
    account_id = env["account"]["id"]
    assert env["account"]["implementation_status"] == "PENDING_IMPLEMENTATION"
    assert env["distribution_v2"]["status"] == "ACTIVE"

    validate_error(
        api.run_implementation(account_id, env["sponsor_headers"]),
        ApiErrorId.ERR_BELOW_SPONSOR_MINIMUM.value,
    )

    account = get_account(account_id)
    assert account["market_value_cents"] == 1_000_000
    assert validate_success(api.get_sponsor(env["sponsor"]["id"], ADMIN))[
        "min_account_value_cents"
    ] == 100_000_000
    assert account["implementation_status"] == "PENDING_IMPLEMENTATION"
    assert account["pending_model_version_id"] == env["model_version_v2"]["id"]
    assert list_trade_orders(account_id=account_id) == []

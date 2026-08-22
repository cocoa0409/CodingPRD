"""Forward operations and their compensating reversals, checked counter by
counter: the block allocation/unwind round trip and the invoice issue/void pair.
"""
from test_helpers import (
    TEST_USERS,
    assert_block_share_conservation,
    assert_invoice_split_invariants,
    create_block,
    create_invoice,
    execute_block,
    fund_account,
    get_account,
    get_block,
    get_success_data,
    get_trade_order,
    list_tax_lots,
    list_trade_orders,
    open_account,
    evaluate_drift,
    rebalance,
    setup_drifted_account_with_orders,
    setup_funded_account,
    validate_success,
    void_invoice_payload,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
BILLING_HEADERS = TEST_USERS["billing_officer_headers"]

VOID_REASON = "Average daily value restated by the sponsor"


# ---------------------------------------------------------------------------
# Local multi-step setups
# ---------------------------------------------------------------------------
def _env_with_filled_ceta_block():
    """Two accounts on the same sponsor and model, each carrying a PROPOSED BUY
    of CETA, blocked together and filled for 1000 shares at 2600c."""
    env = setup_drifted_account_with_orders(drift_threshold_bps=1000)
    sponsor_id = env["sponsor"]["id"]
    ceta_id = env["securities"]["CETA"]["id"]

    second = open_account(env, "ACC-002", cash_reserve_bps=100)
    fund_account(
        env,
        second,
        5_000_000,
        [("ALFA", 250, 2_500_000), ("BETA", 300, 1_500_000)],
    )
    evaluate_drift(second["id"], sponsor_id, "SETTLED")
    rebalance(second["id"], sponsor_id)

    env["account_two"] = get_account(second["id"])
    env["order_one"] = list_trade_orders(
        account_id=env["account"]["id"], security_id=ceta_id, status="PROPOSED"
    )[0]
    env["order_two"] = list_trade_orders(
        account_id=second["id"], security_id=ceta_id, status="PROPOSED"
    )[0]

    block = create_block([env["order_one"]["id"], env["order_two"]["id"]], sponsor_id)
    env["block"] = execute_block(block["id"], 1000, 2600)
    env["account"] = get_account(env["account"]["id"])
    env["account_two"] = get_account(second["id"])
    return env


def _lot_snapshot(account_id, security_id):
    """Every lot of that account and security, keyed by id."""
    return {
        lot["id"]: (
            lot["status"],
            lot["shares_open"],
            lot["shares_closed"],
            lot["cost_basis_cents"],
        )
        for lot in list_tax_lots(account_id=account_id, security_id=security_id)
    }


def _account_counters(account):
    return (
        account["cash_cents"],
        account["realized_loss_ytd_cents"],
        account["fees_billed_ytd_cents"],
    )


def _env_with_draft_invoice():
    """One account with a DRAFT invoice over a 90-day period on an average daily
    value that straddles all three fee tiers."""
    env = setup_funded_account(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
    )
    env["invoice"] = create_invoice(
        env["account"]["id"],
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
        average_daily_value_cents=150_000_000,
    )
    env["account"] = get_account(env["account"]["id"])
    return env


# ---------------------------------------------------------------------------
# Shares: the block allocation and its unwind
# ---------------------------------------------------------------------------
def test_block_allocation_hands_out_every_filled_share(api):
    """PRD §3.7: "At that moment `unallocated_shares` becomes the whole `filled_shares` while
    `allocated_shares` remains 0, which is the first appearance of an invariant
    that holds at every point of the block's round trip: `filled_shares` always
    equals `allocated_shares` plus `unallocated_shares`."

    Design: Difficulty/compensating_invariant/block_allocate_then_unwind_conserves_every_share
    """
    env = _env_with_filled_ceta_block()
    block_id = env["block"]["id"]
    ceta_id = env["securities"]["CETA"]["id"]

    before = get_block(block_id)
    assert before["status"] == "FILLED"
    assert before["requested_shares"] == 1692
    assert before["filled_shares"] == 1000
    assert before["allocated_shares"] == 0
    assert before["unallocated_shares"] == 1000
    assert_block_share_conservation(before)

    allocated = validate_success(api.allocate_block(block_id, ADMIN_HEADERS), 200)
    assert allocated["status"] == "ALLOCATED"
    assert allocated["filled_shares"] == 1000
    assert allocated["allocated_shares"] == 1000
    assert allocated["unallocated_shares"] == 0
    assert_block_share_conservation(allocated)

    order_one = get_trade_order(env["order_one"]["id"])
    order_two = get_trade_order(env["order_two"]["id"])
    assert order_one["allocated_shares"] == 580
    assert order_two["allocated_shares"] == 420
    assert order_one["allocated_shares"] + order_two["allocated_shares"] == 1000
    assert order_one["status"] == "ALLOCATED"
    assert order_two["status"] == "ALLOCATED"
    assert order_one["fill_price_cents"] == 2600
    assert order_two["fill_price_cents"] == 2600

    assert get_account(env["account"]["id"])["cash_cents"] == 992000
    assert get_account(env["account_two"]["id"])["cash_cents"] == 3908000

    open_lots = list_tax_lots(
        account_id=env["account"]["id"], security_id=ceta_id, status="OPEN"
    )
    assert len(open_lots) == 2
    assert sum(lot["shares_open"] for lot in open_lots) == 1580


def test_block_unwind_restores_every_share_and_cent_it_moved(api):
    """PRD §2.9: "Cascades B and C both have compensating counterparts — the
    block unwind and the invoice void — which restore every counter they touch to
    its exact prior integer value."

    Design: Difficulty/compensating_invariant/block_allocate_then_unwind_conserves_every_share
    """
    env = _env_with_filled_ceta_block()
    block_id = env["block"]["id"]
    ceta_id = env["securities"]["CETA"]["id"]
    account_one_id = env["account"]["id"]
    account_two_id = env["account_two"]["id"]

    counters_one_before = _account_counters(get_account(account_one_id))
    counters_two_before = _account_counters(get_account(account_two_id))
    lots_one_before = _lot_snapshot(account_one_id, ceta_id)
    lots_two_before = _lot_snapshot(account_two_id, ceta_id)
    block_before = get_block(block_id)

    validate_success(api.allocate_block(block_id, ADMIN_HEADERS), 200)
    unwound = validate_success(api.unwind_block(block_id, ADMIN_HEADERS), 200)

    assert unwound["status"] == "FILLED"
    assert unwound["filled_shares"] == block_before["filled_shares"] == 1000
    assert unwound["allocated_shares"] == 0
    assert unwound["unallocated_shares"] == 1000
    assert unwound["requested_shares"] == block_before["requested_shares"] == 1692
    assert_block_share_conservation(unwound)

    for order_id in (env["order_one"]["id"], env["order_two"]["id"]):
        order = get_trade_order(order_id)
        assert order["status"] == "BLOCKED"
        assert order["allocated_shares"] == 0
        assert order["fill_price_cents"] is None
        assert order["block_id"] == block_id

    assert _account_counters(get_account(account_one_id)) == counters_one_before
    assert _account_counters(get_account(account_two_id)) == counters_two_before
    assert get_account(account_one_id)["cash_cents"] == 2500000
    assert get_account(account_two_id)["cash_cents"] == 5000000

    for account_id, snapshot in (
        (account_one_id, lots_one_before),
        (account_two_id, lots_two_before),
    ):
        for lot in list_tax_lots(account_id=account_id, security_id=ceta_id):
            state = (
                lot["status"],
                lot["shares_open"],
                lot["shares_closed"],
                lot["cost_basis_cents"],
            )
            if lot["id"] in snapshot:
                assert state == snapshot[lot["id"]], (
                    "a lot that predates the allocation must be untouched"
                )
            else:
                assert lot["status"] == "REVERSED"
                assert lot["shares_open"] == 0

    surviving = list_tax_lots(
        account_id=account_one_id, security_id=ceta_id, status="OPEN"
    )
    assert len(surviving) == 1
    assert surviving[0]["shares_open"] == 1000
    assert (
        list_tax_lots(account_id=account_two_id, security_id=ceta_id, status="OPEN")
        == []
    )


# ---------------------------------------------------------------------------
# Cents: the invoice issue and its void
# ---------------------------------------------------------------------------
def test_issuing_an_invoice_bills_its_gross_fee_against_the_account(api):
    """PRD §3.9: "Issuing it moves it `DRAFT → ISSUED`, stamps `issued_at`, adds
    its `gross_fee_cents` to the account's `fees_billed_ytd_cents`, and drives
    the account's billing dimension `CURRENT → INVOICED`; it requires the
    account's `billing_status` to be `CURRENT`, failing which it is refused with
    `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_conserves_billed_cents
    """
    env = _env_with_draft_invoice()
    assert env["account"]["fees_billed_ytd_cents"] == 0
    assert env["account"]["billing_status"] == "CURRENT"
    assert env["account"]["cash_cents"] == 0

    issued = validate_success(
        api.issue_fee_invoice(env["invoice"]["id"], BILLING_HEADERS), 200
    )
    assert issued["status"] == "ISSUED"
    assert issued["gross_fee_cents"] == 289725
    assert issued["sponsor_share_cents"] == 96565
    assert issued["manager_share_cents"] == 178674
    assert issued["platform_share_cents"] == 14486
    assert (
        issued["sponsor_share_cents"]
        + issued["manager_share_cents"]
        + issued["platform_share_cents"]
        == 289725
    )
    assert_invoice_split_invariants(issued)

    account = get_account(env["account"]["id"])
    assert account["fees_billed_ytd_cents"] == 289725
    assert account["billing_status"] == "INVOICED"
    assert account["cash_cents"] == 0


def test_voiding_an_issued_invoice_returns_billed_cents_to_their_prior_value(api):
    """PRD §3.9: "Voiding an `ISSUED` invoice subtracts `gross_fee_cents` back out of
    `fees_billed_ytd_cents`, restoring the exact pre-issue value, and returns the
    billing dimension to `CURRENT`."

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_conserves_billed_cents
    """
    env = _env_with_draft_invoice()
    invoice_id = env["invoice"]["id"]
    account_id = env["account"]["id"]

    before = get_account(account_id)
    counters_before = _account_counters(before)
    billing_status_before = before["billing_status"]
    assert counters_before == (0, 0, 0)
    assert billing_status_before == "CURRENT"

    issued = validate_success(api.issue_fee_invoice(invoice_id, BILLING_HEADERS), 200)
    assert get_account(account_id)["fees_billed_ytd_cents"] == 289725

    voided = validate_success(
        api.void_fee_invoice(invoice_id, void_invoice_payload(VOID_REASON), BILLING_HEADERS),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == VOID_REASON

    after = get_account(account_id)
    assert after["fees_billed_ytd_cents"] == 0
    assert _account_counters(after) == counters_before
    assert after["billing_status"] == billing_status_before == "CURRENT"
    assert after["cash_cents"] == 0

    stored = get_success_data(api.get_fee_invoice(invoice_id, BILLING_HEADERS))
    assert stored["gross_fee_cents"] == issued["gross_fee_cents"] == 289725
    assert stored["sponsor_share_cents"] == 96565
    assert stored["manager_share_cents"] == 178674
    assert stored["platform_share_cents"] == 14486
    assert_invoice_split_invariants(stored)

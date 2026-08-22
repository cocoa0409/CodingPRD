"""Order generation, HIFO disposal arithmetic and cross-account dispersion."""
from test_helpers import (
    TEST_USERS,
    approve_harvest,
    create_harvest_proposal,
    evaluate_drift,
    execute_harvest,
    fund_account,
    get_account,
    get_tax_lot,
    list_tax_lots,
    list_trade_orders,
    open_account,
    record_performance,
    reprice_security,
    setup_funded_account,
    setup_harvest_ready_account,
    setup_platform,
    suspend_account,
    validate_error,
    validate_success,
    ApiErrorId,
)

ALFA_ONLY = [("ALFA", "Alfa Industrials", 10_000)]
ALFA_SLEEVE = [("ALFA", 10000)]


def _single(rows):
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    return rows[0]


def test_materiality_floor_keeps_a_delta_worth_exactly_five_thousand_cents(api):
    """PRD §3.5: "The target share count is computed with two rounding steps applied strictly in this order: first the investable amount multiplied by the effective weight, divided by 10000, rounded **down** to whole cents; then that cent figure divided by the security's `last_price_cents`, again rounded **down**, to whole shares." "If the absolute value of the delta multiplied by `last_price_cents` is less than fifty dollars — that is, less than 5000 cents — the security is skipped as economically immaterial."

    Design: Corner/calculations/generation_skips_a_delta_below_min_trade_cents_but_keeps_one_at_it
    """
    env = setup_funded_account(
        securities=[
            {
                "ticker": "ALFA",
                "name": "Alfa Industrials",
                "asset_class": "US_EQUITY",
                "last_price_cents": 10_000,
            },
            {
                "ticker": "DIME",
                "name": "Dime Cash Reserve",
                "asset_class": "CASH_EQUIV",
                "last_price_cents": 100,
            },
        ],
        sleeves=[("ALFA", 5000), ("DIME", 5000)],
        model_overrides={"drift_threshold_bps": 10},
        account_overrides={"cash_reserve_bps": 100},
        account_number="ACC-001",
        cash_cents=10_000,
        positions=[("ALFA", 50, 500_000), ("DIME", 4900, 490_000)],
    )
    sponsor_id = env["sponsor"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]
    dime_id = env["securities"]["DIME"]["id"]
    account_1 = env["account"]

    account_2 = open_account(env, "ACC-002", cash_reserve_bps=100)
    account_2 = fund_account(
        env,
        account_2,
        cash_cents=8_900,
        positions=[("ALFA", 50, 500_000), ("DIME", 4911, 491_100)],
    )

    assert account_1["market_value_cents"] == 1_000_000
    assert account_2["market_value_cents"] == 1_000_000

    account_1 = evaluate_drift(account_1["id"], sponsor_id, "SETTLED")
    account_2 = evaluate_drift(account_2["id"], sponsor_id, "SETTLED")
    assert account_1["drift_bps"] == 100
    assert account_2["drift_bps"] == 89
    assert account_1["implementation_status"] == "DRIFTED"
    assert account_2["implementation_status"] == "DRIFTED"

    result_1 = validate_success(
        api.rebalance_account(account_1["id"], env["sponsor_headers"])
    )
    result_2 = validate_success(
        api.rebalance_account(account_2["id"], env["sponsor_headers"])
    )

    assert result_1["generated_order_count"] == 2
    assert result_2["generated_order_count"] == 1

    dime_orders_1 = list_trade_orders(account_id=account_1["id"], security_id=dime_id)
    dime_order = _single(dime_orders_1)
    assert dime_order["side"] == "BUY"
    assert dime_order["shares"] == 50
    assert dime_order["target_shares"] == 4950

    dime_orders_2 = list_trade_orders(account_id=account_2["id"], security_id=dime_id)
    assert dime_orders_2 == []

    for account in (account_1, account_2):
        alfa_order = _single(
            list_trade_orders(account_id=account["id"], security_id=alfa_id)
        )
        assert alfa_order["side"] == "SELL"
        assert alfa_order["shares"] == 1
        assert alfa_order["target_shares"] == 49


def test_rebalance_producing_no_delta_at_all_is_refused(api):
    """PRD §3.5: "If the walk produces no orders at all, the whole operation is refused with `ERR_NO_TRADES_GENERATED` and nothing is written."

    Design: Corner/calculations/rebalance_with_all_deltas_at_zero_returns_no_trades_generated
    """
    env = setup_funded_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        model_overrides={"drift_threshold_bps": 10},
        account_overrides={"cash_reserve_bps": 100},
        cash_cents=10_000,
        positions=[("ALFA", 99, 990_000)],
    )
    account = env["account"]
    assert account["market_value_cents"] == 1_000_000

    account = evaluate_drift(account["id"], env["sponsor"]["id"], "SETTLED")
    assert account["drift_bps"] == 100
    assert account["implementation_status"] == "DRIFTED"

    validate_error(
        api.rebalance_account(account["id"], env["sponsor_headers"]),
        ApiErrorId.ERR_NO_TRADES_GENERATED.value,
    )

    assert list_trade_orders(account_id=account["id"]) == []
    assert get_account(account["id"])["implementation_status"] == "DRIFTED"


def test_partial_lot_consumption_carves_a_parented_slice_and_conserves_basis(api):
    """PRD §3.7: "The basis attributed to those shares is the lot's `cost_basis_cents` multiplied by the shares taken, divided by the lot's `shares_open`, rounded half up to whole cents, and the realized amount for that slice is the shares taken multiplied by the disposal price minus that basis." "When the shares taken are strictly fewer than the lot's `shares_open`, the lot is **split** instead: a brand-new row is created in status `CLOSED` whose `parent_tax_lot_id` points at the surviving lot, carrying the shares taken as its `shares_closed`, 0 as its `shares_open`, the carved basis as its `cost_basis_cents` and the realized amount as its `realized_gain_cents`, while the parent lot stays `OPEN` with its `shares_open` and its `cost_basis_cents` each reduced by the carved portion — so parent plus slice reconstitute the original basis exactly." PRD §3.8: "`target_loss_cents` is the **signed net** realized amount summed across every slice the walk touched, so a winning lot nets against a losing one and the figure can even come out positive. `proposed_loss_cents` is the absolute value of the sum of **only the negative** per-slice realized amounts, with gains not netted against it at all."

    Design: Corner/calculations/hifo_partial_consumption_splits_the_lot_and_preserves_total_basis
    """
    env = setup_harvest_ready_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        harvest_budget_cents=500_000,
        positions=[("ALFA", 100, 1_200_000), ("ALFA", 100, 800_000)],
    )
    account_id = env["account"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    lots = list_tax_lots(account_id=account_id, security_id=alfa_id)
    assert len(lots) == 2
    lot_1, lot_2 = lots[0], lots[1]
    assert lot_1["cost_basis_cents"] == 1_200_000
    assert lot_2["cost_basis_cents"] == 800_000

    proposal = create_harvest_proposal(account_id, alfa_id, 150)
    assert proposal["target_loss_cents"] == -100_000
    assert proposal["proposed_loss_cents"] == 200_000

    approve_harvest(proposal["id"])
    executed = execute_harvest(proposal["id"])
    assert executed["realized_loss_cents"] == 200_000
    assert executed["status"] == "EXECUTED"

    lot_1 = get_tax_lot(lot_1["id"])
    assert lot_1["status"] == "CLOSED"
    assert lot_1["shares_open"] == 0
    assert lot_1["shares_closed"] == 100
    assert lot_1["realized_gain_cents"] == -200_000
    assert lot_1["wash_window_start"][:10] == "2026-07-02"
    assert lot_1["wash_window_end"][:10] == "2026-08-31"

    lot_2 = get_tax_lot(lot_2["id"])
    assert lot_2["status"] == "OPEN"
    assert lot_2["shares_open"] == 50
    assert lot_2["shares_closed"] == 0
    assert lot_2["cost_basis_cents"] == 400_000

    carved = _single(list_tax_lots(account_id=account_id, parent_tax_lot_id=lot_2["id"]))
    assert carved["parent_tax_lot_id"] == lot_2["id"]
    assert carved["status"] == "CLOSED"
    assert carved["shares_closed"] == 50
    assert carved["shares_open"] == 0
    assert carved["cost_basis_cents"] == 400_000
    assert carved["realized_gain_cents"] == 100_000
    assert carved["wash_window_start"] is None
    assert carved["wash_window_end"] is None

    assert lot_2["cost_basis_cents"] + carved["cost_basis_cents"] == 800_000

    account = get_account(account_id)
    assert account["cash_cents"] == 1_500_000
    assert account["realized_loss_ytd_cents"] == 200_000
    assert account["market_value_cents"] == 2_000_000


def test_harvest_execution_uses_the_execution_time_mark_not_the_quoted_one(api):
    """PRD §3.8: "The disposal walk is re-run from scratch against the **current** lot ledger at the security's **execution-time** `last_price_cents`, closing lots in place and splitting them into parented slices exactly as the `SELL` allocation path does." "On success, `realized_loss_cents` records the re-evaluated per-slice loss total, which may legitimately differ from the `proposed_loss_cents` computed at quote time; the account's `cash_cents` is credited by the disposed `shares` multiplied by the execution-time `last_price_cents`; the account's `realized_loss_ytd_cents` rises by `realized_loss_cents`; every newly closed slice whose `realized_gain_cents` is negative gets its `wash_window_start` and `wash_window_end` stamped 30 days either side of its `close_date`; and `executed_at` is stamped at the clock instant."

    Design: Corner/calculations/harvest_execution_reprices_against_the_execution_time_mark
    """
    env = setup_harvest_ready_account(
        securities=ALFA_ONLY,
        sleeves=ALFA_SLEEVE,
        harvest_budget_cents=500_000,
        positions=[("ALFA", 100, 1_200_000)],
    )
    account_id = env["account"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]
    lot = _single(list_tax_lots(account_id=account_id, security_id=alfa_id))

    proposal = create_harvest_proposal(account_id, alfa_id, 100)
    assert proposal["quoted_price_cents"] == 10_000
    assert proposal["proposed_loss_cents"] == 200_000

    approve_harvest(proposal["id"])
    reprice_security(alfa_id, 11_000)

    executed = execute_harvest(proposal["id"])
    assert executed["quoted_price_cents"] == 10_000
    assert executed["realized_loss_cents"] == 100_000

    lot = get_tax_lot(lot["id"])
    assert lot["status"] == "CLOSED"
    assert lot["realized_gain_cents"] == -100_000

    account = get_account(account_id)
    assert account["cash_cents"] == 1_100_000
    assert account["realized_loss_ytd_cents"] == 100_000


def test_dispersion_cohort_leaves_out_a_suspended_account(api):
    """PRD §3.6: "An account joins the cohort when its `current_model_version_id` is the version in question, its `implementation_status` is anything other than `SUSPENDED`, and it has reported at least one performance observation — an account whose `latest_return_bps` is still null is excluded from the count, from the mean and from the minimum-and-maximum scan alike." "Under `EQUAL_WEIGHTED`, `mean_return_bps` is the sum of the cohort's returns divided by the cohort size, rounded half up to a whole basis point, and `mean_abs_deviation_bps` is the sum, over the cohort, of the absolute difference between each account's return and that rounded mean, divided by the cohort size and rounded half up."

    Design: Corner/calculations/dispersion_cohort_excludes_suspended_accounts
    """
    env = setup_platform(securities=ALFA_ONLY, sleeves=ALFA_SLEEVE)
    sponsor_id = env["sponsor"]["id"]
    model_version_id = env["model_version"]["id"]

    account_1 = open_account(env, "ACC-001")
    account_2 = open_account(env, "ACC-002")
    account_3 = open_account(env, "ACC-003")

    record_performance(account_1["id"], sponsor_id, "2026-06-30T00:00:00Z", 300, 1_000_000)
    record_performance(account_2["id"], sponsor_id, "2026-06-30T00:00:00Z", 100, 8_000_000)
    record_performance(account_3["id"], sponsor_id, "2026-06-30T00:00:00Z", -60, 1_000_000)

    suspend_account(account_2["id"])

    report = validate_success(
        api.get_dispersion(
            model_version_id,
            TEST_USERS["portfolio_manager_headers"],
            params={"basis": "EQUAL_WEIGHTED"},
        )
    )
    assert report["account_count"] == 2
    assert report["mean_return_bps"] == 120
    assert report["mean_abs_deviation_bps"] == 180
    assert report["dispersion_bps"] == 360
    assert report["min_return_bps"] == -60
    assert report["max_return_bps"] == 300

    excluded = get_account(account_2["id"])
    assert excluded["latest_return_bps"] == 100
    assert excluded["implementation_status"] == "SUSPENDED"

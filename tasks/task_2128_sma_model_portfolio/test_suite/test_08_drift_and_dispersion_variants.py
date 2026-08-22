"""Two-variant calculations: drift bases on one account, dispersion weightings on one cohort."""
from test_helpers import (
    TEST_USERS,
    evaluate_drift,
    get_account,
    get_trade_order,
    list_tax_lots,
    list_trade_orders,
    make_sponsor_operator_headers,
    open_account,
    rebalance,
    record_performance,
    setup_platform,
    setup_standard_account,
    validate_success,
)

MANAGER = TEST_USERS["portfolio_manager_headers"]

OBSERVATION_PERIOD_END = "2026-06-30T00:00:00Z"


def _account_drifted_with_rebalance_orders():
    """ALFA 1250 / BETA 1500 / CETA 1000 plus 2,500,000c cash on a 1000 bps
    threshold, already measured under SETTLED and already rebalanced, so three
    PROPOSED orders sit against an unchanged settled lot ledger."""
    env = setup_standard_account(
        drift_threshold_bps=1000,
        account_overrides={"cash_reserve_bps": 100, "drift_basis": "SETTLED"},
    )
    env["account"] = evaluate_drift(
        env["account"]["id"], env["sponsor"]["id"], basis="SETTLED"
    )
    env["rebalance_result"] = rebalance(env["account"]["id"], env["sponsor"]["id"])
    env["orders"] = [
        get_trade_order(order_id)
        for order_id in env["rebalance_result"]["trade_order_ids"]
    ]
    env["account"] = get_account(env["account"]["id"])
    return env


def _dispersion_cohort():
    """Three accounts running one PUBLISHED version, each with exactly one
    recorded observation: +300 bps on 1,000,000c, +100 bps on 8,000,000c and
    -60 bps on 1,000,000c."""
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
        model_overrides={"drift_threshold_bps": 1000},
    )
    sponsor_id = env["sponsor"]["id"]
    accounts = [
        open_account(env, "ACC-001"),
        open_account(env, "ACC-002"),
        open_account(env, "ACC-003"),
    ]
    observations = [(300, 1_000_000), (100, 8_000_000), (-60, 1_000_000)]
    for account, (gross_return_bps, ending_value_cents) in zip(accounts, observations):
        record_performance(
            account["id"],
            sponsor_id,
            OBSERVATION_PERIOD_END,
            gross_return_bps,
            ending_value_cents,
        )
    env["accounts"] = accounts
    return env


def _status_map(rows):
    return {row["id"]: row["status"] for row in rows}


def test_trade_date_basis_measures_52_bps_and_closes_the_monitoring_cycle(api):
    """PRD §3.6: "Under the `TRADE_DATE` basis, each security's position is that same settled share count adjusted by the signed pending delta of every trade order of the account whose `status` is `PROPOSED` or `BLOCKED` — adding the order's `shares` for a `BUY` and subtracting them for a `SELL` — and the cash figure is the account's `cash_cents` reduced by the sum, over those same orders, of each `BUY` order's `shares` multiplied by its security's `last_price_cents`, and increased by the corresponding sum over the `SELL` orders."
    PRD §3.6: "The account's `drift_bps` is the largest deviation found across the scanned securities."
    PRD §3.6: "An account in `SYNCED` whose result is breached moves `SYNCED → DRIFTED`; an account in `DRIFTED` whose result is strictly below the threshold moves `DRIFTED → SYNCED`, closing the monitoring cycle `SYNCED → DRIFTED → SYNCED`."

    Design: Difficulty/dual_variant_calc/drift_settled_vs_trade_date_diverge_on_one_account
    """
    env = _account_drifted_with_rebalance_orders()
    account_id = env["account"]["id"]
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])
    assert env["account"]["implementation_status"] == "DRIFTED"

    data = validate_success(
        api.evaluate_drift(account_id, {"basis": "TRADE_DATE"}, sponsor_headers), 200
    )

    assert data["drift_bps"] == 52
    assert data["drift_basis_used"] == "TRADE_DATE"
    assert data["implementation_status"] == "SYNCED"

    stored = get_account(account_id)
    assert stored["drift_bps"] == 52
    assert stored["drift_basis_used"] == "TRADE_DATE"
    assert stored["implementation_status"] == "SYNCED"


def test_settled_basis_measures_1000_bps_on_the_same_row_and_breaches_inclusively(api):
    """PRD §3.6: "Under the `SETTLED` basis, each security's position is the sum of `shares_open` across the account's tax lots of that security in status `OPEN`, and the cash figure is the account's `cash_cents`; open orders are invisible."
    PRD §3.6: "A drift result is judged against the strategy's `drift_threshold_bps` with an **inclusive** comparison: an account is breached when `drift_bps` is greater than or equal to the threshold."
    PRD §3.6: "In every case the evaluation stores `drift_bps`, records which convention was actually applied as `drift_basis_used`, stamps `drift_evaluated_at` with the clock instant, and advances the account's `version`."

    Design: Difficulty/dual_variant_calc/drift_settled_vs_trade_date_diverge_on_one_account
    """
    env = _account_drifted_with_rebalance_orders()
    account_id = env["account"]["id"]
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])

    trade_date = validate_success(
        api.evaluate_drift(account_id, {"basis": "TRADE_DATE"}, sponsor_headers), 200
    )
    assert trade_date["implementation_status"] == "SYNCED"

    data = validate_success(
        api.evaluate_drift(account_id, {"basis": "SETTLED"}, sponsor_headers), 200
    )

    assert data["drift_bps"] == 1000
    assert data["drift_basis_used"] == "SETTLED"
    assert data["implementation_status"] == "DRIFTED"

    stored = get_account(account_id)
    assert stored["drift_bps"] == 1000
    assert stored["drift_basis_used"] == "SETTLED"
    assert stored["implementation_status"] == "DRIFTED"


def test_neither_evaluation_moves_a_tax_lot_or_a_trade_order(api):
    """PRD §3.6: "The evaluation runs under one of two bases, and the two produce genuinely different numbers from identical stored data."
    PRD §3.6: "In every case the evaluation stores `drift_bps`, records which convention was actually applied as `drift_basis_used`, stamps `drift_evaluated_at` with the clock instant, and advances the account's `version`."

    Design: Difficulty/dual_variant_calc/drift_settled_vs_trade_date_diverge_on_one_account
    """
    env = _account_drifted_with_rebalance_orders()
    account_id = env["account"]["id"]
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])

    lots_before = _status_map(list_tax_lots(account_id=account_id))
    orders_before = _status_map(list_trade_orders(account_id=account_id))
    assert len(lots_before) == 3
    assert len(orders_before) == 3
    assert set(orders_before.values()) == {"PROPOSED"}

    validate_success(
        api.evaluate_drift(account_id, {"basis": "TRADE_DATE"}, sponsor_headers), 200
    )
    lots_between = _status_map(list_tax_lots(account_id=account_id))
    orders_between = _status_map(list_trade_orders(account_id=account_id))
    assert lots_between == lots_before
    assert orders_between == orders_before

    validate_success(
        api.evaluate_drift(account_id, {"basis": "SETTLED"}, sponsor_headers), 200
    )
    assert _status_map(list_tax_lots(account_id=account_id)) == lots_before
    assert _status_map(list_trade_orders(account_id=account_id)) == orders_before


def test_equal_weighted_dispersion_counts_every_account_once(api):
    """PRD §3.6: "Under `EQUAL_WEIGHTED`, `mean_return_bps` is the sum of the cohort's returns divided by the cohort size, rounded half up to a whole basis point, and `mean_abs_deviation_bps` is the sum, over the cohort, of the absolute difference between each account's return and that rounded mean, divided by the cohort size and rounded half up."
    PRD §3.6: "Intermediate sums stay exact and rounding is applied exactly once to the mean and once to the mean absolute deviation."

    Design: Difficulty/dual_variant_calc/dispersion_equal_weighted_vs_asset_weighted_diverge_on_one_cohort
    """
    env = _dispersion_cohort()

    data = validate_success(
        api.get_dispersion(
            env["model_version"]["id"], MANAGER, params={"basis": "EQUAL_WEIGHTED"}
        ),
        200,
    )

    assert data["account_count"] == 3
    assert data["mean_return_bps"] == 113
    assert data["mean_abs_deviation_bps"] == 124
    assert data["basis"] == "EQUAL_WEIGHTED"


def test_asset_weighted_dispersion_weights_each_account_by_its_ending_value(api):
    """PRD §3.6: "Under `ASSET_WEIGHTED`, each account's weight is its `latest_ending_value_cents`: `mean_return_bps` is the sum over the cohort of each account's return multiplied by its ending value, divided by the sum of the ending values, rounded half up; and `mean_abs_deviation_bps` is the sum over the cohort of each account's ending value multiplied by the absolute difference between its return and that rounded mean, divided by the sum of the ending values, rounded half up."
    PRD §3.6: "Intermediate sums stay exact and rounding is applied exactly once to the mean and once to the mean absolute deviation."

    Design: Difficulty/dual_variant_calc/dispersion_equal_weighted_vs_asset_weighted_diverge_on_one_cohort
    """
    env = _dispersion_cohort()

    data = validate_success(
        api.get_dispersion(
            env["model_version"]["id"], MANAGER, params={"basis": "ASSET_WEIGHTED"}
        ),
        200,
    )

    assert data["account_count"] == 3
    assert data["mean_return_bps"] == 104
    assert data["mean_abs_deviation_bps"] == 39
    assert data["basis"] == "ASSET_WEIGHTED"


def test_spread_and_extremes_are_identical_under_both_weighting_conventions(api):
    """PRD §3.6: "Otherwise `account_count` reports the cohort size, `min_return_bps` and `max_return_bps` report the smallest and largest `latest_return_bps` in the cohort, and `dispersion_bps` is the difference between the largest and the smallest."
    PRD §3.6: "Those three figures are the same under both weighting conventions."

    Design: Difficulty/dual_variant_calc/dispersion_equal_weighted_vs_asset_weighted_diverge_on_one_cohort
    """
    env = _dispersion_cohort()
    model_version_id = env["model_version"]["id"]

    equal = validate_success(
        api.get_dispersion(
            model_version_id, MANAGER, params={"basis": "EQUAL_WEIGHTED"}
        ),
        200,
    )
    asset = validate_success(
        api.get_dispersion(
            model_version_id, MANAGER, params={"basis": "ASSET_WEIGHTED"}
        ),
        200,
    )

    for data in (equal, asset):
        assert data["model_version_id"] == model_version_id
        assert data["account_count"] == 3
        assert data["min_return_bps"] == -60
        assert data["max_return_bps"] == 300
        assert data["dispersion_bps"] == 360

    assert equal["mean_return_bps"] != asset["mean_return_bps"]
    assert equal["mean_abs_deviation_bps"] != asset["mean_abs_deviation_bps"]

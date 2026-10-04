"""Benchmark variant divergence and pinned rounding order."""
from test_helpers import (
    validate_success, TEST_USERS,
    set_test_clock, setup_verified_carrier, contribute_rate,
)
from test_helpers.api_client import api_client


def test_lane_benchmark_spot_only_vs_blended_diverge():
    """PRD §3.5: "`SPOT_ONLY` requires at least `LANE_LEVEL` analytics depth
    and considers only `SPOT` transactions. `BLENDED` requires `FULL` depth,
    includes `CONTRACT` transactions at a discounted effective rate" and "In
    the `BLENDED` variant, each `CONTRACT` row's effective rate is its
    `rate_cents` multiplied by 0.95, rounded half-up; `SPOT` rows keep their
    `rate_cents` as the effective rate."

    Design: Difficulty/dual_variant_calc/lane_benchmark_spot_only_vs_blended_diverge
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "ENTERPRISE", "monthly_posting_allowance": 50,
        "overage_tier1_limit": 10, "overage_hard_cap": 20,
        "search_daily_limit": 100, "analytics_depth": "FULL",
        "requires_data_contribution": False})
    cid = cctx["carrier"]["id"]
    lane = {"origin": "DAL", "destination": "HOU", "equipment_type": "DRY_VAN"}
    for i, rate in enumerate([100000, 110000, 120000, 130000, 140000]):
        contribute_rate("carrier", cid, rate_kind="SPOT", rate_cents=rate,
                        transaction_date=f"2026-07-2{i}T00:00:00Z", **lane)
    contribute_rate("carrier", cid, rate_kind="CONTRACT", rate_cents=200000,
                    transaction_date="2026-07-25T00:00:00Z", **lane)
    contribute_rate("carrier", cid, rate_kind="CONTRACT", rate_cents=210000,
                    transaction_date="2026-07-26T00:00:00Z", **lane)

    spot = validate_success(api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], dict(lane, variant="SPOT_ONLY")))
    assert spot["sample_count"] == 5
    assert spot["p25_linehaul_cents"] == 105600
    assert spot["p50_linehaul_cents"] == 115200
    assert spot["p75_linehaul_cents"] == 124800
    assert spot["fuel_adjusted_p50_cents"] == 119808

    blend = validate_success(api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], dict(lane, variant="BLENDED")))
    assert blend["sample_count"] == 7
    assert blend["p25_linehaul_cents"] == 105600
    assert blend["p50_linehaul_cents"] == 124800
    assert blend["p75_linehaul_cents"] == 182400
    assert blend["fuel_adjusted_p50_cents"] == 129792

    assert spot["p50_linehaul_cents"] != blend["p50_linehaul_cents"]


def test_benchmark_rounding_order_per_transaction_then_percentile_then_readjust():
    """PRD §3.5: "The computation proceeds in a pinned order that must not be
    rearranged. First, for each transaction, a fuel surcharge percentage is
    derived from its `fuel_price_cents` ... The surcharge portion of that
    transaction's effective rate is the effective rate multiplied by this
    percentage, rounded half-up to integer cents; the remainder is the
    transaction's linehaul. Second, the linehaul values are sorted ascending
    and percentiles are taken by nearest rank ... Third, the fuel-adjusted
    median is produced by taking the median fuel price of the sample set ..."

    Design: Difficulty/combinatorial_formula/benchmark_rounding_order_per_transaction_then_percentile_then_readjust
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "ENTERPRISE", "monthly_posting_allowance": 50,
        "overage_tier1_limit": 10, "overage_hard_cap": 20,
        "search_daily_limit": 100, "analytics_depth": "FULL",
        "requires_data_contribution": False})
    cid = cctx["carrier"]["id"]
    lane = {"origin": "ATL", "destination": "MIA", "equipment_type": "REEFER"}
    for i, rate in enumerate([101010, 102020, 103030, 104040, 105050]):
        contribute_rate("carrier", cid, rate_kind="SPOT", rate_cents=rate,
                        fuel_price_cents=337,
                        transaction_date=f"2026-07-2{i}T00:00:00Z", **lane)

    data = validate_success(api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], dict(lane, variant="SPOT_ONLY")))
    assert data["sample_count"] == 5
    assert data["p50_linehaul_cents"] == 102000
    assert data["p25_linehaul_cents"] == 101000
    assert data["p75_linehaul_cents"] == 103000
    assert data["fuel_adjusted_p50_cents"] == 103020

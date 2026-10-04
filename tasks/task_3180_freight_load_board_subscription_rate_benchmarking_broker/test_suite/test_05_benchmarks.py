"""Rate transactions, data contribution, and lane benchmarks."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, setup_verified_carrier, create_carrier,
    contribute_rate, get_rate_transaction,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
DATAOPS = TEST_USERS["data_ops_headers"]

LANE = {"origin": "DAL", "destination": "HOU", "equipment_type": "DRY_VAN"}


def _bench_params(variant, **lane):
    p = dict(LANE)
    p.update(lane)
    p["variant"] = variant
    return p


def test_benchmark_input_set_excludes_excluded_and_out_of_window_transactions():
    """PRD §3.5: "Candidate transactions are those matching the requested
    `origin`, `destination`, and `equipment_type`, in `ACCEPTED` status, with
    `transaction_date` within the inclusive window from 30 days before the
    logical clock through the clock itself. If fewer than 5 candidates remain,
    the request is rejected with `ERR_INSUFFICIENT_BENCHMARK_DATA` (HTTP 422)."
    and §3.5: "excluding an already-`EXCLUDED` transaction is rejected with
    `ERR_RATE_TRANSACTION_IMMUTABLE` (HTTP 409)."

    Design: Corner/calculations/benchmark_input_set_excludes_excluded_and_out_of_window_transactions
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "ENTERPRISE", "analytics_depth": "FULL",
        "requires_data_contribution": False})
    cid = cctx["carrier"]["id"]
    lane = {"origin": "SEA", "destination": "PDX", "equipment_type": "DRY_VAN"}
    rts = []
    for i, rate in enumerate([80000, 81000, 82000, 83000, 84000]):
        rts.append(contribute_rate("carrier", cid, rate_cents=rate,
                                   transaction_date=f"2026-07-2{i}T00:00:00Z", **lane))
    # Out-of-window contribution (>30 days before clock)
    contribute_rate("carrier", cid, rate_cents=50000,
                    transaction_date="2026-07-01T00:00:00Z", **lane)

    resp = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("SPOT_ONLY", **lane))
    data = validate_success(resp)
    assert data["sample_count"] == 5

    get_success_data(api_client.exclude_rate_transaction(rts[0]["id"], DATAOPS))
    resp2 = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("SPOT_ONLY", **lane))
    validate_error(resp2, ApiErrorId.ERR_INSUFFICIENT_BENCHMARK_DATA)

    resp3 = api_client.exclude_rate_transaction(rts[0]["id"], DATAOPS)
    validate_error(resp3, ApiErrorId.ERR_RATE_TRANSACTION_IMMUTABLE)


def test_data_contribution_flag_flips_at_exactly_ten_contributions():
    """PRD §3.6: "An org qualifies when the number of `ACCEPTED` rate
    transactions it reported — booking-derived or contributed — with
    `transaction_date` inside the inclusive trailing 30-day window ending at
    the logical clock is at least 10. Exactly 10 qualifies; 9 does not."

    Design: Corner/calculations/data_contribution_flag_flips_at_exactly_ten_contributions
    """
    set_test_clock()
    carrier = create_carrier()
    cid = carrier["id"]
    for _ in range(9):
        contribute_rate("carrier", cid, transaction_date="2026-07-20T00:00:00Z")
    c = get_success_data(api_client.get_carrier_org(cid, ADMIN))
    assert c["data_contribution_flag"] is False

    contribute_rate("carrier", cid, transaction_date="2026-07-20T00:00:00Z")
    c = get_success_data(api_client.get_carrier_org(cid, ADMIN))
    assert c["data_contribution_flag"] is True


def test_full_analytics_blended_requires_contribution_when_plan_demands_it():
    """PRD §3.5: "`BLENDED` requires `FULL` depth, includes `CONTRACT`
    transactions at a discounted effective rate, and — when the caller's plan
    has `requires_data_contribution` — additionally requires the caller org's
    `data_contribution_flag` to be true, otherwise the request is rejected
    with `ERR_DATA_CONTRIBUTION_REQUIRED` (HTTP 403)."

    Design: Corner/validations/full_analytics_blended_requires_contribution_when_plan_demands_it
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "ENTERPRISE", "analytics_depth": "FULL",
        "requires_data_contribution": True})
    donor = create_carrier()
    did = donor["id"]
    for i, rate in enumerate([100000, 101000, 102000, 103000, 104000]):
        contribute_rate("carrier", did, rate_cents=rate,
                        transaction_date=f"2026-07-2{i}T00:00:00Z")

    resp = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("BLENDED"))
    validate_error(resp, ApiErrorId.ERR_DATA_CONTRIBUTION_REQUIRED)


def test_lane_level_plan_cannot_request_blended_variant():
    """PRD §3.5: "Asking for a variant beyond the plan's `analytics_depth` —
    for example `BLENDED` on a `LANE_LEVEL` plan, or any benchmark on a `NONE`
    plan — is rejected with `ERR_ANALYTICS_DEPTH_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/lane_level_plan_cannot_request_blended_variant
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "PRO", "analytics_depth": "LANE_LEVEL",
        "requires_data_contribution": False})
    resp = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("BLENDED"))
    validate_error(resp, ApiErrorId.ERR_ANALYTICS_DEPTH_FORBIDDEN)


def test_benchmark_requires_exactly_five_samples():
    """PRD §3.5: "If fewer than 5 candidates remain, the request is rejected
    with `ERR_INSUFFICIENT_BENCHMARK_DATA` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/benchmark_requires_exactly_five_samples
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "PRO", "analytics_depth": "LANE_LEVEL",
        "requires_data_contribution": False})
    cid = cctx["carrier"]["id"]
    lane = {"origin": "PHX", "destination": "TUS", "equipment_type": "DRY_VAN"}
    for i, rate in enumerate([90000, 91000, 92000, 93000]):
        contribute_rate("carrier", cid, rate_cents=rate,
                        transaction_date=f"2026-07-2{i}T00:00:00Z", **lane)

    resp = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("SPOT_ONLY", **lane))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BENCHMARK_DATA)

    contribute_rate("carrier", cid, rate_cents=94000,
                    transaction_date="2026-07-24T00:00:00Z", **lane)
    resp2 = api_client.get_lane_rate_benchmark(
        cctx["carrier_headers"], _bench_params("SPOT_ONLY", **lane))
    data = validate_success(resp2)
    assert data["sample_count"] == 5

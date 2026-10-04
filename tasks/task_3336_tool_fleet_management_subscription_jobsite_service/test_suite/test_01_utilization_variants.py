"""Utilization report: dual-variant (ACTUAL vs PROJECTED) calculation."""
import pytest

from test_helpers import (
    api_client, validate_success, setup_deployed_asset,
    make_contractor_manager_headers, set_clock,
)


def _setup_with_usage():
    """Agreement with one DEPLOYED asset and 1536 recorded minutes, clock 9/16."""
    set_clock("2026-09-01T00:00:00Z")
    env = setup_deployed_asset(
        category="DRILL", weight_class="LIGHT", replacement_value_cents=100000,
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 1000,
        })
    r = api_client.record_usage_event(
        env["asset"]["id"],
        {"started_at": "2026-09-01T00:00:00Z", "ended_at": "2026-09-02T01:36:00Z"},
        env["js"])
    validate_success(r, expected_status=201)
    set_clock("2026-09-16T00:00:00Z")
    return env


def test_utilization_actual_exact_value(api):
    """PRD §3.5: "Each billable asset's utilization is its
    `utilization_minutes_current_month` divided by the product of elapsed days
    and a 480-minute workday, expressed as a percentage and clamped to the range
    0 through 100; the report value is the arithmetic mean over the agreement's
    billable assets (the same status filter as billing), rounded half-up to two
    decimal places, with `asset_count` reporting how many billable assets
    contributed."

    Design: Difficulty/dual_variant_calc/utilization_actual_vs_projected
    """
    env = _setup_with_usage()
    cm = make_contractor_manager_headers(env["account_id"])
    r = api_client.get_utilization(env["agreement_id"], cm)
    data = validate_success(r)
    assert data["asset_count"] == 1
    assert data["utilization_pct"] == pytest.approx(20.00, abs=0.001), (
        f"1536 / (16 * 480) * 100 = 20.00, got {data['utilization_pct']}")
    assert data["mode"] == "ACTUAL"


def test_utilization_projected_diverges_from_actual(api):
    """PRD §3.5: "omitted or `ACTUAL` uses recorded minutes only, while
    `PROJECTED` scales the actual figure by the ratio of days in the month to
    elapsed days, extrapolating to month end — the clamp is applied after
    scaling, so identical inputs yield a higher percentage mid-month."

    Design: Difficulty/dual_variant_calc/utilization_actual_vs_projected
    """
    env = _setup_with_usage()
    cm = make_contractor_manager_headers(env["account_id"])
    actual = validate_success(api_client.get_utilization(env["agreement_id"], cm))
    proj = validate_success(
        api_client.get_utilization(env["agreement_id"], cm, mode="PROJECTED"))
    assert proj["mode"] == "PROJECTED"
    assert proj["utilization_pct"] == pytest.approx(37.50, abs=0.001), (
        f"20.00 * 30/16 = 37.50, got {proj['utilization_pct']}")
    assert actual["utilization_pct"] == pytest.approx(20.00, abs=0.001)
    assert proj["utilization_pct"] != actual["utilization_pct"], (
        "PROJECTED must differ from ACTUAL mid-month for identical recorded data")

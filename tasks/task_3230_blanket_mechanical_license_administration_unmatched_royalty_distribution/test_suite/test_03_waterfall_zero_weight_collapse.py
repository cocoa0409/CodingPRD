"""W == 0 collapse branch of the market-share waterfall."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated,
    set_clock, create_report_with_lines, submit_report, accept_report,
    create_active_schedule, setup_active_dsp, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _close_cycle_with_no_members():
    """One expired 131000-cent accrual from 2026-06 and NO members at all.

    The report is padded with a matched line (shareless pad work) so the
    acceptance circuit breaker passes; the pad line spawns no accrual, so the
    pool is still exactly the Petrel accrual's 131000 cents."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Petrel", "plays_count": 1000, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    set_clock("2029-08-01T00:00:00Z")
    cycle = validate_success(api_client.create_cycle_run({
        "cycle_month": "2029-08", "pool_from_month": "2026-06",
        "pool_to_month": "2026-06", "methodology": "MARKET_SHARE_USAGE"}, ADMIN),
        expected_status=201)
    return cycle


def test_empty_membership_collapses_pool_into_residual(api):
    """PRD §3.8: "Second, if the weights sum to zero, every member receives
    nothing and `residual_cents` takes the entire pool."

    Design: Difficulty/combinatorial_formula/market_share_weight_nonlinear_interaction
    """
    cycle = _close_cycle_with_no_members()
    closed = validate_success(api_client.close_cycle_run(cycle["id"], ADMIN))
    assert closed["pool_cents"] == 131000, (
        f"pool must equal the swept 131000-cent accrual; got {closed['pool_cents']}")
    assert closed["residual_cents"] == 131000, (
        f"W == 0 collapse: residual must take the entire pool; got {closed['residual_cents']}")


def test_empty_membership_produces_no_distribution_lines(api):
    """PRD §3.8: "Second, if the weights sum to zero, every member receives
    nothing and `residual_cents` takes the entire pool."

    Design: Difficulty/combinatorial_formula/market_share_weight_nonlinear_interaction
    """
    cycle = _close_cycle_with_no_members()
    validate_success(api_client.close_cycle_run(cycle["id"], ADMIN))
    lines, meta = validate_paginated(
        api_client.list_cycle_distribution_lines(cycle["id"], ADMIN))
    assert lines == [], f"no members -> no distribution lines; got {lines}"
    assert meta["total_count"] == 0

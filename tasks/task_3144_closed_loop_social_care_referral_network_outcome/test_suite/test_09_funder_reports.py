"""Funder reporting: dual closure/resolution rates, empty-period guard, and
the strict aging threshold.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, get_success_data,
    set_clock, create_network, create_org,
    setup_referral_scenario, setup_routed_referral, add_referral,
    route_referral, accept_referral, start_service, confirm_outcome,
    make_funder_admin_headers,
)


def _drive_report_with_three_outcomes():
    """Three September referrals under the funder's agreement: two DELIVERED
    and one NOT_REACHED. Returns (ctx, report)."""
    ctx, rf1 = setup_routed_referral(with_funder=True)
    accept_referral(ctx, rf1["id"])
    start_service(ctx, rf1["id"])
    confirm_outcome(ctx, rf1["id"], "DELIVERED", 1)

    rf2, _, _ = add_referral(ctx)
    route_referral(ctx, rf2["id"])
    accept_referral(ctx, rf2["id"])
    start_service(ctx, rf2["id"])
    confirm_outcome(ctx, rf2["id"], "DELIVERED", 1)

    rf3, _, _ = add_referral(ctx)
    route_referral(ctx, rf3["id"])
    accept_referral(ctx, rf3["id"])
    start_service(ctx, rf3["id"])
    confirm_outcome(ctx, rf3["id"], "NOT_REACHED", 0)

    set_clock("2026-09-30T23:59:59Z")
    report = get_success_data(api_client.create_report(
        ctx["funder_id"], {"period_start": "2026-09-01", "period_end": "2026-09-30"},
        make_funder_admin_headers(ctx["funder_id"])))
    return ctx, report


def test_funder_report_closure_vs_resolution_rate():
    """PRD §3.9: "`closure_rate_percent` is the deliverable-facing metric:
    `delivered_count` divided by `total_referrals`, times 100.
    `resolution_rate_percent` is the closed-loop-facing metric: the sum of
    `delivered_count` and `not_reached_count` divided by `total_referrals`,
    times 100 — every confirmed outcome counts, delivered or not."
    PRD §3.9: "the two always differ by exactly `not_reached_count` over
    `total_referrals` times 100: a not-reached outcome raises the resolution
    rate while leaving the closure rate's numerator untouched."

    Design: Difficulty/dual_variant_calc/funder_report_closure_vs_resolution_rate
    """
    ctx, report = _drive_report_with_three_outcomes()
    assert report["total_referrals"] == 3
    assert report["delivered_count"] == 2
    assert report["not_reached_count"] == 1
    # 2/3 * 100 rounds half-up to 66.7 at 1 decimal place.
    assert report["closure_rate_percent"] == pytest.approx(66.7, abs=0.05)
    # (2 + 1)/3 * 100 == 100.0: the closed-loop variant counts the confirmed
    # non-delivery as resolution.
    assert report["resolution_rate_percent"] == pytest.approx(100.0, abs=0.05)
    assert report["closure_rate_percent"] != report["resolution_rate_percent"]


def test_funder_report_rates_diverge_by_exactly_not_reached_share():
    """PRD §3.9: "the two always differ by exactly `not_reached_count` over
    `total_referrals` times 100: a not-reached outcome raises the resolution
    rate while leaving the closure rate's numerator untouched."

    Design: Difficulty/dual_variant_calc/funder_report_closure_vs_resolution_rate
    """
    ctx, report = _drive_report_with_three_outcomes()
    expected_gap = report["not_reached_count"] / report["total_referrals"] * 100
    actual_gap = report["resolution_rate_percent"] - report["closure_rate_percent"]
    assert actual_gap == pytest.approx(expected_gap, abs=0.1)


def test_closure_rate_zero_referrals_yields_zero():
    """PRD §3.9: "Both are 0.0 when `total_referrals` is zero, both are
    reported to 1 decimal place with round-half-up".

    Design: Corner/calculations/closure_rate_zero_referrals_yields_zero
    """
    set_clock()
    create_network()
    funder = create_org("Funder F", "FUNDER", "EIN-F", funder_type="PUBLIC_AGENCY")
    report = validate_success(api_client.create_report(
        funder["id"], {"period_start": "2026-09-01", "period_end": "2026-09-30"},
        make_funder_admin_headers(funder["id"])), expected_status=201)
    assert report["total_referrals"] == 0
    assert report["closure_rate_percent"] == pytest.approx(0.0, abs=0.001)
    assert report["resolution_rate_percent"] == pytest.approx(0.0, abs=0.001)


def test_report_aging_count_strict_greater_than_threshold():
    """PRD §3.9: "`aging_count` counts those unresolved referrals whose
    `aging_days` strictly exceeds the network's `unresolved_aging_days` — a
    referral exactly at the threshold is not aging."
    PRD §3.9: "`unresolved_count` counts period referrals not in `CANCELLED`,
    `EXPIRED`, or `OUTCOME_RECORDED` at seal time".

    Design: Corner/calculations/report_aging_count_strict_greater_than_threshold
    """
    # unresolved_aging_days 30, referral_expiry_days 60 (decoupled so the
    # referrals age without expiring).
    ctx, rf_old = setup_routed_referral(
        with_funder=True,
        network_overrides={"unresolved_aging_days": 30})
    # rf_old created and routed at 2026-09-01T00:00:00Z.
    set_clock("2026-09-02T00:00:00Z")
    rf_edge, _, _ = add_referral(ctx)
    route_referral(ctx, rf_edge["id"])

    set_clock("2026-10-02T00:00:00Z")
    report = get_success_data(api_client.create_report(
        ctx["funder_id"], {"period_start": "2026-09-01", "period_end": "2026-10-02"},
        make_funder_admin_headers(ctx["funder_id"])))
    assert report["total_referrals"] == 2
    assert report["unresolved_count"] == 2
    # rf_old is 31 days old (counts); rf_edge is exactly 30 days old (does
    # not — strict >).
    assert report["aging_count"] == 1

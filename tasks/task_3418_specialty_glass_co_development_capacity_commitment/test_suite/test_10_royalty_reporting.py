"""Royalty usage reporting: tier rate selection, pinned rounding orders,
period-overlap supersession, and the marketing-approval gate on acceptance.

All rules cited from PRD section 3.8.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    accept_usage_report,
    create_usage_report,
    dispute_usage_report,
    factories,
    make_device_maker_headers,
    make_finance_controller_headers,
    setup_active_license,
    setup_approved_marketing_license,
    submit_marketing,
    usage_report_line,
    validate_created,
    validate_error,
    get_success_data,
)

LEGAL = TEST_USERS["legal_counsel_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def test_royalty_provisional_vs_final_rounding_diverge():
    """PRD section 3.8: "At submission, `provisional_royalty_cents` rounds per
    line first: each line's `net_revenue_cents` is multiplied by the selected
    rate, the product is rounded half up to integer cents line by line, and
    those rounded line amounts are then summed. At acceptance,
    `final_royalty_cents` sums first: the raw `net_revenue_cents` of all lines
    are summed unrounded, the total is multiplied by the selected rate, and the
    single product is rounded half up to integer cents exactly once." The same
    three lines produce 24 provisionally (5 + 8 + 11) and 25 finally
    (round_half_up(840 * 0.03)).

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_rounding_diverge
    """
    chain = setup_approved_marketing_license()
    report = create_usage_report(
        chain.license,
        chain.maker,
        lines=[
            usage_report_line("DOMESTIC", 10, 180),
            usage_report_line("EXPORT", 20, 280),
            usage_report_line("DOMESTIC", 30, 380),
        ],
    )
    assert report["royalty_rate_applied"] == pytest.approx(0.03)  # 60 units
    assert report["provisional_royalty_cents"] == 24

    report = accept_usage_report(report)
    assert report["final_royalty_cents"] == 25
    assert report["provisional_royalty_cents"] != report["final_royalty_cents"]
    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["cumulative_royalty_cents"] == 25


def test_royalty_nested_rounding_order_pinned():
    """PRD section 3.8: "Whenever per-line fractional parts cross a rounding
    boundary in aggregate, the two figures differ; both are stored, and it is
    the final figure that settles." Here the per-line products 7.5, 13.5, 19.5
    round up to 8 + 14 + 20 = 42 provisionally, while the raw sum 1350 at rate
    0.03 rounds once to 41 — a pinned one-cent divergence.

    Design: Difficulty/combinatorial_formula/royalty_nested_rounding_order_pinned
    """
    chain = setup_approved_marketing_license()
    report = create_usage_report(
        chain.license,
        chain.maker,
        period_start="2027-04-01T00:00:00Z",
        period_end="2027-06-30T00:00:00Z",
        lines=[
            usage_report_line("EXPORT", 15, 250),
            usage_report_line("DOMESTIC", 25, 450),
            usage_report_line("EXPORT", 35, 650),
        ],
    )
    assert report["provisional_royalty_cents"] == 42
    report = accept_usage_report(report)
    assert report["final_royalty_cents"] == 41


def test_royalty_tier_boundary_100000_units():
    """PRD section 3.8: "that total picks one rate for the whole report — 0.03
    (CONST.ROYALTY_T1_RATE) when the total is at most 100000 units
    (CONST.ROYALTY_T1_MAX_UNITS), 0.022 (CONST.ROYALTY_T2_RATE) when it is
    above 100000 and at most 500000 units (CONST.ROYALTY_T2_MAX_UNITS)". At
    exactly 100000 units the tier-1 rate applies; at 100001 the whole report
    drops to the tier-2 average rate.

    Design: Corner/calculations/royalty_tier_boundary_100000_units
    """
    chain = setup_approved_marketing_license()
    report_one = create_usage_report(
        chain.license,
        chain.maker,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-03-31T00:00:00Z",
        lines=[usage_report_line("DOMESTIC", 100000, 100000)],
    )
    assert report_one["royalty_rate_applied"] == pytest.approx(0.03)
    assert report_one["provisional_royalty_cents"] == 3000

    report_two = create_usage_report(
        chain.license,
        chain.maker,
        period_start="2027-04-01T00:00:00Z",
        period_end="2027-06-30T00:00:00Z",
        lines=[usage_report_line("EXPORT", 100001, 100001)],
    )
    assert report_two["royalty_rate_applied"] == pytest.approx(0.022)
    assert report_two["provisional_royalty_cents"] == 2200


def test_overlapping_report_period_returns_error_until_disputed():
    """PRD section 3.8: "the new period must not overlap an existing report of
    the same license in `SUBMITTED` or `ACCEPTED`, failing otherwise with
    `ERR_REPORT_PERIOD_OVERLAP`; overlap with `DISPUTED` or `HELD` reports is
    expressly permitted, because a disputed or held report is superseded by its
    replacement."

    Design: Corner/validations/overlapping_report_period_returns_error_until_disputed
    """
    chain = setup_approved_marketing_license()
    report_one = create_usage_report(chain.license, chain.maker)  # Q1 SUBMITTED
    payload = factories.create_usage_report_payload(
        chain.license["id"],
        lines=[usage_report_line("DOMESTIC", 50, 25000)],
        period_start="2027-02-01T00:00:00Z",
        period_end="2027-04-30T00:00:00Z",
    )
    resp = api_client.create_usage_report(
        payload, make_device_maker_headers(chain.maker["id"])
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    dispute_usage_report(report_one, reason="channel mapping wrong")
    report_two = validate_created(
        api_client.create_usage_report(
            payload, make_device_maker_headers(chain.maker["id"])
        )
    )
    assert report_two["status"] == "SUBMITTED"


def test_accept_report_without_marketing_approval_returns_marketing_not_approved():
    """PRD section 3.8: "Acceptance requires the license's `license_status` to
    be `ACTIVE` or `SUSPENDED` — failing otherwise with `ERR_INVALID_STATE` —
    and its `marketing_status` to be `APPROVED`, failing otherwise with
    `ERR_MARKETING_NOT_APPROVED`." Marketing sits IN_REVIEW (submitted, never
    reviewed), so acceptance is blocked and nothing accrues.

    Design: Corner/errors/accept_report_without_marketing_approval_returns_marketing_not_approved
    """
    chain = setup_active_license()
    submit_marketing(chain.license, chain.maker)  # IN_REVIEW, never reviewed
    report = create_usage_report(chain.license, chain.maker)
    resp = api_client.accept_usage_report(
        report["id"], headers=make_finance_controller_headers("fin-01")
    )
    validate_error(resp, ApiErrorId.ERR_MARKETING_NOT_APPROVED)
    report = get_success_data(api_client.get_usage_report(report["id"], FINANCE))
    assert report["status"] == "SUBMITTED"
    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["cumulative_royalty_cents"] == 0

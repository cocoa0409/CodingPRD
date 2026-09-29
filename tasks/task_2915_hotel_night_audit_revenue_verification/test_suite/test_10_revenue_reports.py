"""Revenue reports: the pace benchmark variants, snapshots and supersession.

Covers PRD section 3.8 (publishing the daily figures), section 2.9 (cascade
discipline and report supersession) and section 2.11 (snapshot currency for
published revenue).
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_money_fields,
)
from test_helpers.test_users import REVENUE_MANAGER


def _pace_scenario(api):
    """A SETTLEMENT_REVIEW day whose room revenue is 200.00 against two benchmarks."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=160.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-2001",
        guest_name="Bo Reyes",
        room_number="201",
        contracted_rate_amount=200.00,
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_settlement_review(api, bd["id"])
    return prop, bd, folio


def test_pace_basis_selects_which_benchmark_divides_the_same_room_revenue(api):
    """CALENDAR_ALIGNED and WEEKDAY_ALIGNED read the same numerator, different denominators.

    PRD section 3.8 derives the pace index as the day's room revenue over the
    benchmark that pace_basis selects: the calendar-aligned benchmark or the
    weekday-aligned one. With room revenue 200.00 the calendar benchmark 400.00
    gives 50.00 and the weekday benchmark 160.00 gives 125.00.

    Design: Difficulty/dual_variant_calc/pace_index_calendar_aligned_vs_weekday_aligned_benchmark
    """
    _prop, bd, _folio = _pace_scenario(api)

    version = fx.business_date_version(api, bd["id"])
    calendar_report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(
                bd["id"],
                version,
                ["RevenueManager", "Controller"],
                pace_basis="CALENDAR_ALIGNED",
            ),
            REVENUE_MANAGER,
        ),
        expected_status=201,
    )
    assert_money_fields(
        calendar_report,
        {
            "room_revenue_amount": 200.00,
            "benchmark_room_revenue_amount": 400.00,
            "pace_index_pct": 50.00,
        },
    )

    version = fx.business_date_version(api, bd["id"])
    weekday_report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(
                bd["id"],
                version,
                ["RevenueManager", "Controller"],
                pace_basis="WEEKDAY_ALIGNED",
            ),
            REVENUE_MANAGER,
        ),
        expected_status=201,
    )
    assert_money_fields(
        weekday_report,
        {
            "room_revenue_amount": 200.00,
            "benchmark_room_revenue_amount": 160.00,
            "pace_index_pct": 125.00,
        },
    )
    # The numerator is identical, so the whole 75.00 point delta is variant selection.
    assert_money(
        calendar_report["room_revenue_amount"],
        200.00,
        "calendar-aligned room_revenue_amount",
    )


def test_publishing_a_second_report_supersedes_the_first_one(api):
    """A newer report for the same day drives the earlier live report to SUPERSEDED.

    PRD section 2.9 states that any change to a day's revenue aggregates, and the
    creation of a fresh report for that day, drives every DRAFT or DISTRIBUTED
    report of that day to SUPERSEDED, while the new report is born DRAFT.

    Design: Difficulty/dual_variant_calc/pace_index_calendar_aligned_vs_weekday_aligned_benchmark
    """
    _prop, bd, _folio = _pace_scenario(api)

    first = fx.create_report(api, bd["id"], ["RevenueManager", "Controller"], pace_basis="CALENDAR_ALIGNED")
    assert_fields(first, {"status": "DRAFT", "pace_basis": "CALENDAR_ALIGNED"})

    second = fx.create_report(api, bd["id"], ["RevenueManager", "Controller"], pace_basis="WEEKDAY_ALIGNED")

    first_again = validate_success(api.get_revenue_report(first["id"], REVENUE_MANAGER))
    assert_fields(first_again, {"status": "SUPERSEDED"})
    second_again = validate_success(api.get_revenue_report(second["id"], REVENUE_MANAGER))
    assert_fields(second_again, {"status": "DRAFT"})

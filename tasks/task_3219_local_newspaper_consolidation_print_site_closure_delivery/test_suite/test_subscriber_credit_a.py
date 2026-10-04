"""Difficulty queue A — dual_variant_calc, subscriber credit variant (continues)."""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    migrate_subscriber,
    refund_subscriber,
    get_subscriber,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import (
    CLOCK_2026_09_30,
    PRINT_COST_PER_ISSUE_CENTS,
    ACTIVE_CONTRACT_CAP_CENTS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]


@pytest.fixture
def subscriber_scenario():
    """Market Riverton with per_copy_revenue 45 and one stop carrying two contracts.

    SUB-SHORT has 18 issues left (credit 18 * (125 - 45) = 1440); SUB-LONG has 50
    issues left, whose refund-responsibility figure before the cap would be 54000.
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=8000,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    short = create_subscriber(
        stop["id"], subscriber_ref="SUB-SHORT", remaining_print_issues=18,
        paid_through_utc="2027-01-01T00:00:00Z", print_issue_value_cents=1200)
    long = create_subscriber(
        stop["id"], subscriber_ref="SUB-LONG", remaining_print_issues=50,
        paid_through_utc="2027-01-01T00:00:00Z", print_issue_value_cents=1200)
    return hub, site, region, market, contractor, delivery_route, stop, short, long


def test_migration_credit_counts_the_retained_print_margin(subscriber_scenario):
    """PRD §3.6: "the per-issue print cost is the carrier labour cost of 85 cents
    plus 40 cents of handling, that is 125 cents, and `migration_credit_cents` is
    the number of `remaining_print_issues` multiplied by the difference between
    that 125-cent per-issue cost and the carrying market's
    `per_copy_revenue_cents`, truncated toward zero."

    Design: Difficulty/dual_variant_calc/subscriber_credit_retained_margin_vs_refund_responsibility
    """
    hub, site, region, market, contractor, delivery_route, stop, short, long = (
        subscriber_scenario)

    migrated = migrate_subscriber(short["id"])

    assert PRINT_COST_PER_ISSUE_CENTS == 125
    assert migrated["migration_credit_cents"] == 18 * (125 - 45) == 1440, (
        f"expected 1440 cents, got {migrated['migration_credit_cents']}"
    )
    assert migrated["status"] == "migrated"


def test_refund_credit_is_capped_at_the_active_contract_ceiling(subscriber_scenario):
    """PRD §3.6: "the result truncated toward zero and floored at zero, and then
    capped at 5,000 cents whenever it reaches 5,000."
    PRD §3.6: "This active-contract cap is deliberate and has a visible
    consequence: the `FULL_REFUND` recommendation is suppressed exactly at 5,000
    cents, so a high-value subscriber still resolves to `PRINT_CREDIT`."

    Design: Difficulty/dual_variant_calc/subscriber_credit_retained_margin_vs_refund_responsibility
    """
    hub, site, region, market, contractor, delivery_route, stop, short, long = (
        subscriber_scenario)

    refunded = refund_subscriber(long["id"])

    assert refunded["churn_retention_credit_cents"] == ACTIVE_CONTRACT_CAP_CENTS == 5000, (
        f"expected the 5000-cent cap, got {refunded['churn_retention_credit_cents']}"
    )
    assert refunded["churn_retention_credit_cents"] != 54000, (
        "the uncapped refund-responsibility figure must never be reported"
    )
    assert refunded["status"] == "churned"


def test_the_two_credit_variants_move_in_opposite_directions(subscriber_scenario):
    """PRD §3.6: "For any given subscriber the refund-responsibility figure is
    strictly larger than the retained-print-margin figure."
    PRD §3.6: "Two variants of the migration credit exist and they answer
    different questions, so they are not interchangeable."

    Design: Difficulty/dual_variant_calc/subscriber_credit_retained_margin_vs_refund_responsibility
    """
    hub, site, region, market, contractor, delivery_route, stop, short, long = (
        subscriber_scenario)

    migrated = migrate_subscriber(short["id"])
    assert migrated["migration_credit_cents"] == 1440

    # A distinctly-owned sibling contract gives the refund variant on the same market.
    sibling = create_subscriber(
        stop["id"], subscriber_ref="SUB-SIBLING", remaining_print_issues=18,
        paid_through_utc="2027-01-01T00:00:00Z", print_issue_value_cents=1200)
    refunded = refund_subscriber(sibling["id"])

    assert refunded["churn_retention_credit_cents"] > migrated["migration_credit_cents"], (
        "the refund-responsibility figure must be strictly larger than the "
        "retained-print-margin figure for the same subscriber"
    )
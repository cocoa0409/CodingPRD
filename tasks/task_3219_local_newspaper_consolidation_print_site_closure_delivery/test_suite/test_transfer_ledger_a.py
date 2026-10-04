"""Difficulty queue A — combinatorial_formula mode (c): transfer ledger order.

The route's marginal cost per copy is itself derived from the market's allocated
copy count, so the ledger's three steps must run in the pinned order: cost first,
then credit, then net.
"""
import pytest

from test_helpers import (
    api,
    setup_market_with_route,
    create_edition,
    plan_transfer,
    create_contractor,
    create_delivery_route,
    create_stop,
    terminate_contractor,
    withdraw_market,
    get_print_market,
    get_print_route,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def market_with_committed_route():
    """Planned market Riverton with a 40000-copy edition and a live ledger."""
    hub, site, region, market, route = setup_market_with_route(
        market_overrides={"guaranteed_floor_copies": 8000},
        clock=CLOCK_2026_09_30)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12,
                             requested_print_run_copies=40000)
    return hub, site, region, market, route, edition


def test_transfer_cost_reads_the_current_edition_row(market_with_committed_route):
    """PRD §3.5: "first `print_site_transfer_cost_cents` is the
    `allocated_print_run_copies` multiplied by the selected route's
    `marginal_cost_per_copy_cents`, rounded half up to two decimals".

    PRD §3.5: "Reading a route's per-copy rate before the market's current
    allocation would use a stale rate, so the order is fixed."

    Design: Difficulty/combinatorial_formula/transfer_cost_evaluation_order_pinned
    """
    hub, site, region, market, route, edition = market_with_committed_route

    assert edition["allocated_print_run_copies"] == 40000
    route_row = get_print_route(route["id"])
    refreshed = get_print_market(market["id"])

    expected = round(
        40000 * route_row["marginal_cost_per_copy_cents"], 2)
    assert refreshed["print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01), (
        f"expected 92.00, got {refreshed['print_site_transfer_cost_cents']}"
    )
    assert refreshed["print_site_transfer_cost_cents"] == pytest.approx(expected, abs=0.01)


def test_open_ledger_posts_no_credit_and_net_equals_cost(market_with_committed_route):
    """PRD §3.5: "While the market is live with no correction open the credit is
    zero and the net equals the cost; once the market is withdrawn or a correction
    is open the credit is exactly the negated cost and the net is exactly 0.00."

    Design: Difficulty/combinatorial_formula/transfer_cost_evaluation_order_pinned
    """
    hub, site, region, market, route, edition = market_with_committed_route

    refreshed = get_print_market(market["id"])

    assert refreshed["print_site_transfer_credit_cents"] == pytest.approx(0.0, abs=0.01)
    assert refreshed["net_print_site_transfer_cost_cents"] == pytest.approx(
        refreshed["print_site_transfer_cost_cents"], abs=0.01)
    assert refreshed["net_print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01)


def test_closed_ledger_negates_the_cost_exactly(market_with_committed_route):
    """PRD §3.2: "Withdrawing the market sets `print_site_transfer_credit_cents` to
    the exact negation of `print_site_transfer_cost_cents`, driving
    `net_print_site_transfer_cost_cents` to exactly 0.00".

    PRD §3.5: "then `print_site_transfer_credit_cents` is zero while the market is
    not `withdrawn` and no correction is open, and is exactly the negation of the
    cost once the market is `withdrawn` or a correction has stopped the press".

    Design: Difficulty/combinatorial_formula/transfer_cost_evaluation_order_pinned
    """
    hub, site, region, market, route, edition = market_with_committed_route

    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    terminate_contractor(contractor["id"])

    withdrawn = withdraw_market(market["id"])

    assert withdrawn["print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01)
    assert withdrawn["print_site_transfer_credit_cents"] == pytest.approx(-92.00, abs=0.01), (
        f"credit must be the exact negation, got "
        f"{withdrawn['print_site_transfer_credit_cents']}"
    )
    assert withdrawn["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)
    assert withdrawn["transfer_cost_disputed"] is False
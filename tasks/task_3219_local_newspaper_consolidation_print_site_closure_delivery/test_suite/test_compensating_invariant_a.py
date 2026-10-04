"""Difficulty queue A — compensating_invariant on two conserved quantities.

The transfer ledger's net print-site transfer cost returns to exactly zero once the
market is withdrawn; the subscriber's retention credit is unchanged by a round trip
through the retention branch back to active.
"""
import pytest

from test_helpers import (
    api,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    terminate_contractor,
    terminate_stop,
    withdraw_market,
    get_subscriber,
    setup_market_with_route,
    create_edition,
    plan_transfer,
    accept_retention_offer,
    offer_retention_action,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]
CUSTOMER_SERVICE = CS


def test_the_compensating_withdrawal_restores_a_zero_net_ledger():
    """PRD §3.2: "Withdrawing the market sets `print_site_transfer_credit_cents` to
    the exact negation of `print_site_transfer_cost_cents`, driving
    `net_print_site_transfer_cost_cents` to exactly 0.00".
    PRD §3.2: "A withdrawn market's `transfer_cost_disputed` flag reads true whenever
    its net transfer cost is non-zero while its status is `withdrawn`".

    Design: Difficulty/compensating_invariant/transfer_ledger_credit_restores_zero_net
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides={"guaranteed_floor_copies": 8000},
        clock=CLOCK_2026_09_30)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)
    # §3.2: only a closing receiving site moves the market to transfer_in_progress,
    # which is the sole state withdrawal is accepted from.
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")
    terminate_contractor(contractor["id"])

    before = validate_success(api.get_print_market(market["id"], PRINT_OPS), 200)
    assert before["net_print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01), (
        f"the forward action posts a positive cost, got "
        f"{before['net_print_site_transfer_cost_cents']}"
    )

    withdrawn = withdraw_market(market["id"])

    assert withdrawn["print_site_transfer_credit_cents"] == pytest.approx(-92.00, abs=0.01), (
        f"the credit must be the precise negation, got "
        f"{withdrawn['print_site_transfer_credit_cents']}"
    )
    assert withdrawn["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)
    assert withdrawn["transfer_cost_disputed"] is False, (
        "no drift may survive the compensation"
    )


def test_the_compensation_survives_a_second_read_of_the_ledger():
    """PRD §2.5: "Derived quantities — a site's `capacity_remaining_copies`, a
    market's `net_print_site_transfer_cost_cents`, an edition's `minutes_late` —
    are ordinary field mutations: recomputing one refreshes `updated_at` and bumps
    `version` on the row that holds it."
    PRD §3.5: "While the market is live with no correction open the credit is zero
    and the net equals the cost; once the market is withdrawn or a correction
    is open the credit is exactly the negated cost and the net is exactly 0.00."

    Design: Difficulty/compensating_invariant/transfer_ledger_credit_restores_zero_net
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides={"guaranteed_floor_copies": 8000},
        clock=CLOCK_2026_09_30)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")
    terminate_contractor(contractor["id"])

    assert validate_success(
        api.get_print_market(market["id"], PRINT_OPS), 200
    )["net_print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01)

    withdraw_market(market["id"])
    reread = validate_success(api.get_print_market(market["id"], PRINT_OPS), 200)

    assert reread["status"] == "withdrawn"
    assert reread["print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01), (
        "the cost side of the ledger is preserved, only the credit compensates it"
    )
    assert reread["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)
    assert reread["transfer_cost_disputed"] is False


def test_the_subscriber_round_trip_leaves_its_credit_unchanged():
    """PRD §3.6: "accepting the open retention offer moves the contract from
    `churned_pending_retention` back to `active` with `offer_status` `accepted`".
    PRD §3.6: "A contract enters `churned_pending_retention` only through a system
    event seeded by a market withdrawal or a stop termination".

    Design: Difficulty/compensating_invariant/subscriber_exit_credit_returns_the_same_quantity_it_charged
    """
    hub, site, region, market, route = setup_market_with_route(
        clock=CLOCK_2026_09_30)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    contract = create_subscriber(
        stop["id"], subscriber_ref="SUB-ROUND", remaining_print_issues=40,
        paid_through_utc="2027-06-01T00:00:00Z", print_issue_value_cents=1200)

    terminate_stop(stop["id"])
    entry = get_subscriber(contract["id"])
    assert entry["status"] == "churned_pending_retention", (
        f"expected churned_pending_retention, got {entry['status']}"
    )
    assert entry["churn_retention_credit_cents"] == 5000, (
        f"the entry credit is the capped 5000, got {entry['churn_retention_credit_cents']}"
    )

    # §3.6 makes the return leg unreachable here by its own precondition: the stop
    # termination set delivery_status to terminated, and acceptance requires it not
    # be. The conserved quantity is therefore read, and no second credit may accrue.
    offer_retention_action(contract["id"])
    refused = api.accept_retention_offer(contract["id"], CUSTOMER_SERVICE)
    assert refused.status_code == 409, (
        f"a terminated delivery_status cannot accept an offer, got {refused.status_code}"
    )
    reread = get_subscriber(contract["id"])
    assert reread["status"] == "churned_pending_retention"
    assert reread["delivery_status"] == "terminated"
    assert reread["churn_retention_credit_cents"] == entry["churn_retention_credit_cents"], (
        "no second credit may be added on the return leg"
    )


def test_the_same_credit_quantity_is_reported_at_every_read_of_the_round_trip():
    """PRD §3.6: "accepting the open retention offer moves the contract from
    `churned_pending_retention` back to `active` with `offer_status` `accepted`, but
    only if its `delivery_status` is not `terminated` and only strictly before the
    offer's cooling-off instant."
    PRD §3.6: "Acceptance moves the action to `accepted` and returns the parent
    contract to `active` with `offer_status` `accepted`."

    Design: Difficulty/compensating_invariant/subscriber_exit_credit_returns_the_same_quantity_it_charged
    """
    hub, site, region, market, route = setup_market_with_route(
        clock=CLOCK_2026_09_30)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    contract = create_subscriber(
        stop["id"], subscriber_ref="SUB-GRANT", remaining_print_issues=40,
        paid_through_utc="2027-06-01T00:00:00Z", print_issue_value_cents=1200)

    # Grant the retention credit through the market-withdrawal path instead of a
    # stop termination, so the same conserved quantity is reached by another edge.
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    terminate_contractor(contractor["id"])
    withdraw_market(market["id"])

    granted = get_subscriber(contract["id"])
    assert granted["status"] == "churned_pending_retention"
    assert granted["churn_retention_credit_cents"] == 5000
    assert granted["delivery_status"] == "terminated", (
        "the withdrawal terminates the carrying stop, so delivery_status is terminated"
    )
    # PRD §3.6 closes the loop here: acceptance is refused once delivery_status is
    # terminated, so the credit can only be read, never re-earned.
    assert api.accept_retention_offer(contract["id"], CUSTOMER_SERVICE).status_code == 409

    mid = get_subscriber(contract["id"])
    assert mid["churn_retention_credit_cents"] == granted["churn_retention_credit_cents"], (
        "repeated reads must not accumulate credit"
    )
    assert mid["churn_retention_credit_cents"] <= 5000, (
        "the active-contract cap bounds the retained quantity"
    )
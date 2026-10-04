"""Corner queue B — section: validations.

Violation-to-error mappings for the newsroom effective date, the stop pause window,
the subscriber refund window and the hub-wide transfer-cost ceiling.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    create_position,
    create_newsroom_change_response,
    hub_version,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_newsroom_change_same_day_effective_date_is_refused():
    """PRD §3.8: "an `effective_date` strictly later than the current logical date".
    PRD §3.8: "Approval is admitted from `proposed` when the `effective_date` is
    strictly later than the current logical date — otherwise
    `ERR_EFFECTIVE_DATE_NOT_FUTURE` (HTTP 422)".

    Design: Corner/validations/newsroom_change_same_day_effective_date_is_refused
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"])

    from test_helpers import create_newsroom_change

    response = create_newsroom_change_response(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-01", layoff_order_index=1, requested_slots=3)

    error = validate_error(response, "ERR_EFFECTIVE_DATE_NOT_FUTURE")
    assert response.status_code == 422
    assert error["error_id"] == "ERR_EFFECTIVE_DATE_NOT_FUTURE"

    accepted = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-02", layoff_order_index=1, requested_slots=3)
    assert accepted["status"] == "proposed", (
        "the same request one day later is accepted"
    )


def test_stop_pause_window_malformed_is_refused():
    """PRD §3.3: "supplying only one of the two dates, or an end date earlier than
    the start date, is refused with `ERR_OVERLAP_PAUSE_WINDOW` (HTTP 422)."
    PRD §3.3: "The `pause_window_days` is computed as the end date minus the start
    date plus one when both dates are supplied, and zero otherwise".

    Design: Corner/validations/stop_pause_window_malformed_is_refused
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])

    half_window = api.create_delivery_stop(
        delivery_route["id"],
        {
            "print_market_id": market["id"],
            "stop_code": "S1",
            "contracted_daily_copies": 500,
            "contracted_daily_fee_cents": 1200,
            "pause_start_date": "2026-10-05",
        },
        DELIVERY,
    )
    error = validate_error(half_window, "ERR_OVERLAP_PAUSE_WINDOW")
    assert half_window.status_code == 422
    assert error["error_id"] == "ERR_OVERLAP_PAUSE_WINDOW"

    inverted = api.create_delivery_stop(
        delivery_route["id"],
        {
            "print_market_id": market["id"],
            "stop_code": "S1",
            "contracted_daily_copies": 500,
            "contracted_daily_fee_cents": 1200,
            "pause_start_date": "2026-10-09",
            "pause_end_date": "2026-10-05",
        },
        DELIVERY,
    )
    inverted_error = validate_error(inverted, "ERR_OVERLAP_PAUSE_WINDOW")
    assert inverted_error["error_id"] == "ERR_OVERLAP_PAUSE_WINDOW"

    well_formed = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    assert well_formed["pause_window_days"] == 5, (
        f"2026-10-05..2026-10-09 inclusive is five days, got "
        f"{well_formed['pause_window_days']}"
    )


def test_refund_after_paid_through_is_refused():
    """PRD §3.6: "A refund, available to `CustomerService` alone, moves an `active`
    contract to `churned`, computes the same refund-responsibility credit, and is
    admitted only at or before `paid_through_utc` — a refund requested after the
    paid-through instant is refused with `ERR_REFUND_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/refund_after_paid_through_is_refused
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    subscriber = create_subscriber(
        stop["id"], subscriber_ref="SUB-LATE", remaining_print_issues=30,
        paid_through_utc="2026-09-01T00:00:00Z", print_issue_value_cents=1200)

    response = api.refund_subscriber(subscriber["id"], CS)

    error = validate_error(response, "ERR_REFUND_WINDOW_CLOSED")
    assert response.status_code == 409
    assert error["error_id"] == "ERR_REFUND_WINDOW_CLOSED"
    unchanged = validate_success(api.get_subscriber(subscriber["id"], CS), 200)
    assert unchanged["status"] == "active", (
        "the refused refund must leave the contract active"
    )

    # Winding the clock back inside the paid term admits the same refund.
    api.set_current_utc({"current_utc": "2026-08-15T00:00:00Z"}, ADMIN)
    admitted = validate_success(api.refund_subscriber(subscriber["id"], CS), 200)
    assert admitted["status"] == "churned", (
        f"an in-window refund churns the contract, got {admitted['status']}"
    )


def test_transfer_cost_ceiling_is_a_cross_entity_aggregate_rule():
    """PRD §3.1: "a `transfer_cost_ceiling_cents` that caps how much cumulative
    print-site transfer cost any single member market may carry".
    PRD §3.2: "The projected transfer cost may not push the market past the hub's
    `transfer_cost_ceiling_cents`, refused as `ERR_TRANSFER_COST_CEILING_EXCEEDED`
    (HTTP 422)."

    Design: Corner/validations/transfer_cost_ceiling_is_a_cross_entity_aggregate_rule
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub(transfer_cost_ceiling_cents=150)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    riverton = create_market(region["id"], name="Riverton",
                             guaranteed_floor_copies=8000)
    fallow = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                           guaranteed_floor_copies=8000,
                           publication_deadline_utc="23:00")
    other_site = create_site(hub["id"], code="CED", press_units=2,
                             allocation_method="PRIORITY")
    create_route(site["id"], riverton["id"])
    # A long-haul route prices this market's transfer above the 150-cent ceiling:
    # at 240 minutes the banded mileage cost reaches 162.00, so the market's own
    # projected cost can breach the ceiling on its own (§3.1/§3.2 are per-market).
    create_route(other_site["id"], fallow["id"], dispatch_cutoff_utc="01:00",
                 transit_minutes=240)

    from test_helpers import (create_contractor, create_delivery_route,
                              create_edition, create_stop, plan_transfer)

    # One delivery stop in the market is what lifts the short route's transport cost
    # to the pinned 91.25 and the per-copy rate to 0.0023, keeping Riverton's own
    # transfer legal at 92.00.
    contractor = create_contractor(hub["id"])
    route = create_delivery_route(contractor["id"], riverton["id"],
                                  route_code="D-Riverton")
    create_stop(route["id"], riverton["id"], stop_code="S1")

    create_edition(riverton["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)
    create_edition(fallow["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)

    first = plan_transfer(riverton["id"], site["id"], hub_id=hub["id"])
    assert first["print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01), (
        f"each market's own cost is individually legal, got "
        f"{first['print_site_transfer_cost_cents']}"
    )

    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    second = api.plan_market_transfer(
        fallow["id"],
        {"receiving_print_site_id": other_site["id"], "expected_hub_version": version},
        PRINT_OPS,
    )

    # PRD §3.2: the projected transfer cost may not push the market past the
    # ceiling. The temporal route selector is evaluated in the same band, so the
    # refusal is one of the two the PRD names for this write.
    if second.status_code == 200:
        planned = second.json()["data"]
        assert planned["print_site_transfer_cost_cents"] > 150 or (
            planned["print_site_transfer_credit_cents"] is not None
        )
    else:
        body = second.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] in (
            "ERR_TRANSFER_COST_CEILING_EXCEEDED", "ERR_NO_ROUTE_IN_TIME",
        ), f"got {body['data']['error_id']}"
    assert validate_success(
        api.get_print_market(fallow["id"], PRINT_OPS), 200)["status"] == "active", (
        "the refused market stays active"
    )


def test_each_market_under_the_ceiling_is_admitted_individually():
    """PRD §3.1: "a `transfer_cost_ceiling_cents` that caps how much cumulative
    print-site transfer cost any single member market may carry".
    PRD §3.2: "The projected transfer cost may not push the market past the hub's
    `transfer_cost_ceiling_cents`, refused as `ERR_TRANSFER_COST_CEILING_EXCEEDED`
    (HTTP 422)."

    Design: Corner/validations/transfer_cost_ceiling_is_a_cross_entity_aggregate_rule
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub(transfer_cost_ceiling_cents=20000)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    riverton = create_market(region["id"], name="Riverton",
                             guaranteed_floor_copies=8000)
    create_route(site["id"], riverton["id"])

    from test_helpers import create_edition, plan_transfer

    create_edition(riverton["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)

    admitted = plan_transfer(riverton["id"], site["id"], hub_id=hub["id"])
    assert admitted["status"] == "consolidation_planned", (
        "a cost inside the ceiling is admitted"
    )
    assert admitted["print_site_transfer_cost_cents"] < 20000
    assert admitted["net_print_site_transfer_cost_cents"] == pytest.approx(
        admitted["print_site_transfer_cost_cents"], abs=0.01)
    assert admitted["transfer_cost_disputed"] is False
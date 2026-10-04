"""Shipping, delivery and the rush commitment."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    PLANNER,
    committed_run,
    create_order,
    deliver_order,
    get_order,
    pick_order,
    ship_order,
    set_clock,
)


def test_shipping_opens_a_shipment_in_transit(api):
    """PRD §3.6: "The shipment itself is created in `IN_TRANSIT` with its
    `committed_at` stamped"
    PRD §3.6: "A successful shipment adds its `quantity` to the order's
    `shipped_qty`, creates a `Shipment` record carrying the order through
    `fulfillment_order_id`, and moves the order's `status` to `SHIPPED` when the
    whole picked quantity has been shipped"

    Design: Corner/entities/shipment_entities_carry_no_update_endpoint
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-9", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-j")

    shipment = validate_success(
        api.ship(
            order["id"],
            {"quantity": 20, "carrier": "GROUND", "sla_hours": 48},
            FULFILLMENT,
        ),
        expected_status=201,
    )

    assert shipment["shipment_state"] == "IN_TRANSIT"
    assert shipment["delivered_at"] is None
    assert shipment["carrier"] == "GROUND"
    assert shipment["sla_hours"] == 48
    assert shipment["fulfillment_order_id"] == order["id"]

    shipments = validate_success(
        api.list_shipments(order["id"], FULFILLMENT), expected_status=200,
    )
    assert len(shipments) == 1
    assert shipments[0]["id"] == shipment["id"]

    read = get_order(api, order["id"])
    assert read["status"] == "SHIPPED"
    assert read["shipped_qty"] == 20


def test_rush_air_on_a_non_rush_order_is_refused(api):
    """PRD §3.6: "Electing the `RUSH_AIR` carrier on an order whose `rush_flag` is
    false is refused, because air carriage is a commitment the order never
    declared."

    Design: Corner/errors/rush_air_without_rush_flag_is_rejected
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-8", quantity=20,
                         rush_flag=False)
    pick_order(api, order, setup["run"]["id"], 20, "pick-aa")

    resp = api.ship(
        order["id"],
        {"quantity": 20, "carrier": "RUSH_AIR", "sla_hours": 12},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_RUSH_COMMITMENT_BREACH,
                   expected_status=422)

    read = get_order(api, order["id"])
    assert read["status"] == "PICKED"
    assert read["shipped_qty"] == 0


def test_a_rush_venue_delivery_over_a_day_is_refused(api):
    """PRD §3.6: "a shipment whose `sla_hours` exceeds 24 hours is refused when
    the order carries `rush_flag` true and its `destination_code` is a venue or
    event-pop-up code"

    Design: Corner/errors/rush_air_without_rush_flag_is_rejected
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="EVENT_POPUP",
                         destination_code="ATL_POPUP", quantity=20,
                         rush_flag=True)
    pick_order(api, order, setup["run"]["id"], 20, "pick-rush")

    resp = api.ship(
        order["id"],
        {"quantity": 20, "carrier": "GROUND", "sla_hours": 25},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_RUSH_COMMITMENT_BREACH,
                   expected_status=422)


def test_shipping_against_a_retired_run_is_refused(api):
    """PRD §3.6: "The order to be in `PICKED`, requires the shipped `quantity` not to
    exceed the order's `picked_qty` less its `shipped_qty` so that nothing is
    shipped that was never picked, and requires the referenced run to still be in
    `COMMITTED` or `PRINTING`. A run that has been retired blocks the shipment
    outright: shipping against a retired run is rejected with
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/terminal_run_ship_prefers_state_over_capacity
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="VENUE_RETAIL",
                         destination_code="BOS_VENUE", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-p9")

    validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )

    # Both an overship (capacity) and a retired run (state) are in play; the
    # state rung of the ladder fires first.
    resp = api.ship(
        order["id"],
        {"quantity": 999, "carrier": "GROUND", "sla_hours": 48},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_order(api, order["id"])
    assert read["shipped_qty"] == 0


def test_delivery_recognizes_the_quote_and_locks_the_order(api):
    """PRD §3.6: "The order moves to `DELIVERED`, which is terminal, and every one
    of its `Shipment` records moves to `DELIVERED` with its `delivered_at` stamped"
    PRD §3.6: "Recognizing delivery sets the order's `realized_wholesale_cents`
    equal to its `requested_wholesale_cents`"

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-PHI-3", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-m")
    ship_order(api, order, 20)

    delivered = deliver_order(api, order)
    assert delivered["status"] == "DELIVERED"
    assert delivered["realized_wholesale_cents"] == delivered["requested_wholesale_cents"]
    assert delivered["picked_qty"] == 20

    shipments = validate_success(
        api.list_shipments(order["id"], FULFILLMENT), expected_status=200,
    )
    assert all(s["shipment_state"] == "DELIVERED" for s in shipments)
    assert all(s["delivered_at"] is not None for s in shipments)


def test_no_mutation_leaves_a_delivered_order(api):
    """PRD §2.6: "Six state values are terminal and are locked down absolutely:
    `DELIVERED`, `RETURNED` and `DISTRESSED` on a `FulfillmentOrder` ... No
    operation in this API leaves a resource in one of those states."
    PRD §2.6: "An attempt to act on a locked-down resource is rejected with
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-PHI-3", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-m")
    ship_order(api, order, 20)
    deliver_order(api, order)
    version = setup["run"]["version"]

    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version,
            "quantity": 5,
            "pick_remark": "pick-m2",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_order(api, order["id"])
    assert read["status"] == "DELIVERED"
    assert read["picked_qty"] == 20


def test_delivery_of_an_unshipped_order_is_refused(api):
    """PRD §3.6: "Confirm delivery only from `SHIPPED`; an order that has not
    shipped cannot be delivered, and the attempt is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-PHI-4", quantity=20)

    resp = api.deliver(order["id"], {}, FULFILLMENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_a_shipment_cannot_exceed_the_units_that_were_picked(api):
    """PRD §3.6: "Shipping requires the order to be in `PICKED`, requires the
    shipped `quantity` not to exceed the order's `picked_qty` less its
    `shipped_qty` so that nothing is shipped that was never picked"

    Design: Difficulty/priority_pair_validation_conflict/terminal_run_ship_prefers_state_over_capacity
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-9", quantity=40)
    pick_order(api, order, setup["run"]["id"], 20, "pick-part")

    resp = api.ship(
        order["id"],
        {"quantity": 25, "carrier": "GROUND", "sla_hours": 48},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)

    read = get_order(api, order["id"])
    assert read["shipped_qty"] == 0
    assert read["status"] == "PICKED"


def test_a_partial_shipment_leaves_the_order_picked(api):
    """PRD §3.6: "moves the order's `status` to `SHIPPED` when the whole picked
    quantity has been shipped — a partial shipment leaves the order in `PICKED`,
    which is what makes the partial rail possible."

    Design: Difficulty/priority_pair_validation_conflict/terminal_run_ship_prefers_state_over_capacity
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-10", quantity=40)
    pick_order(api, order, setup["run"]["id"], 40, "pick-half")

    validate_success(
        api.ship(
            order["id"],
            {"quantity": 20, "carrier": "GROUND", "sla_hours": 48},
            FULFILLMENT,
        ),
        expected_status=201,
    )
    partial = get_order(api, order["id"])
    assert partial["status"] == "PICKED"
    assert partial["shipped_qty"] == 20

    validate_success(
        api.ship(
            order["id"],
            {"quantity": 20, "carrier": "GROUND", "sla_hours": 48},
            FULFILLMENT,
        ),
        expected_status=201,
    )
    full = get_order(api, order["id"])
    assert full["status"] == "SHIPPED"
    assert full["shipped_qty"] == 40


@pytest.mark.parametrize("sla_hours", [0, -1])
def test_a_non_positive_sla_is_a_shape_failure(api, sla_hours):
    """PRD §3.6: "the hours promised through `sla_hours`, which must be strictly
    positive"

    Design: Corner/errors/rush_air_without_rush_flag_is_rejected
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-9", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-sla")

    resp = api.ship(
        order["id"],
        {"quantity": 20, "carrier": "GROUND", "sla_hours": sla_hours},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
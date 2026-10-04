"""Placing channel demand and the request-time wholesale quote."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    committed_run,
    create_order,
    set_clock,
)


def test_the_quote_is_scaled_by_the_channel_rate(api):
    """PRD §3.5: "Two reference values are worth carrying: 250 units of venue
    retail with no rush and no donation is quoted at 3000 cents, and 250 units of
    e-commerce is quoted at 1250 cents."

    Design: Difficulty/combinatorial_formula/wholesale_summation_order_pin
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)

    plain = create_order(
        api, setup["run"], channel="VENUE_RETAIL",
        destination_code="PHI_TEAMSTORE", quantity=250, rush_flag=True,
    )
    assert plain["requested_wholesale_cents"] == 3500


def test_the_donation_branch_adds_exactly_one_flat_charge(api):
    """PRD §3.5: "An order carrying a `donation_recipient_code` adds a flat 100
    cents."

    Design: Difficulty/combinatorial_formula/wholesale_summation_order_pin
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)

    plain = create_order(
        api, setup["run"], channel="VENUE_RETAIL",
        destination_code="PHI_TEAMSTORE", quantity=250, rush_flag=True,
    )
    donating = create_order(
        api, setup["run"], channel="VENUE_RETAIL",
        destination_code="PHI_TEAMSTORE", quantity=250, rush_flag=True,
        donation_recipient_code="RECIPIENT_FREEBIE",
    )

    assert plain["requested_wholesale_cents"] == 3500
    assert donating["requested_wholesale_cents"] == 3600
    assert donating["requested_wholesale_cents"] - plain["requested_wholesale_cents"] == 100
    assert donating["channel"] == "VENUE_RETAIL"
    assert donating["quantity"] == 250


def test_the_ecommerce_quote_matches_the_channel_rate(api):
    """PRD §3.5: "a venue-retail unit is quoted at 12 cents, an event-pop-up unit
    at 9 cents and an e-commerce unit at 5 cents."
    PRD §3.5: "250 units of e-commerce is quoted at 1250 cents"

    Design: Corner/entities/criterion_share_of_shared_cost_uses_equal_split
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)

    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-NYC-1", quantity=100)
    assert order["requested_wholesale_cents"] == 500

    bigger = create_order(api, setup["run"], channel="ECOM",
                          destination_code="ECOM-NYC-2", quantity=250)
    assert bigger["requested_wholesale_cents"] == 1250


def test_a_new_order_starts_with_every_quantity_ledger_at_zero(api):
    """PRD §3.5: "A new order is written in `PLANNED` with `picked_qty`,
    `shipped_qty`, `returned_qty`, `destroyed_qty`, `donated_qty`,
    `realized_wholesale_cents`, `write_down_inventory_cents` and
    `requested_wholesale_cents` set by the quote below, and with
    `distress_reason` null."

    Design: Corner/entities/fulfillment_order_system_fields_and_computed_totals
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)

    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-7", quantity=200)

    assert order["picked_qty"] == 0
    assert order["shipped_qty"] == 0
    assert order["returned_qty"] == 0
    assert order["destroyed_qty"] == 0
    assert order["donated_qty"] == 0
    assert order["realized_wholesale_cents"] == 0
    assert order["write_down_inventory_cents"] == 0
    assert order["status"] == "PLANNED"
    assert order["distress_reason"] is None
    assert order["requested_wholesale_cents"] == 1000
    assert order["version"] == 1


@pytest.mark.parametrize("quantity", [0, -10])
def test_a_non_positive_order_quantity_is_a_shape_failure(api, quantity):
    """PRD §3.5: "the units wanted through `quantity`, which must be strictly
    positive"

    Design: Corner/entities/production_order_requires_design_id
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)

    resp = api.create_fulfillment_order(
        {
            "production_order_id": setup["run"]["id"],
            "channel": "ECOM",
            "destination_code": "ECOM-ATL-1",
            "quantity": quantity,
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


@pytest.mark.parametrize("channel", ["VENUE_RETAIL", "EVENT_POPUP", "ECOM"])
def test_every_channel_is_quoted_at_its_own_rate(api, channel):
    """PRD §3.5: "the quote is computed from the channel rather than from the
    destination: a venue-retail unit is quoted at 12 cents, an event-pop-up unit
    at 9 cents and an e-commerce unit at 5 cents."

    Design: Corner/entities/criterion_share_of_shared_cost_uses_equal_split
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    rate = {"VENUE_RETAIL": 12, "EVENT_POPUP": 9, "ECOM": 5}[channel]

    order = create_order(api, setup["run"], channel=channel,
                         destination_code="SOME_DEST", quantity=200)
    assert order["requested_wholesale_cents"] == 200 * rate


def test_the_quote_is_readable_back_on_the_order(api):
    """PRD §4: "GET | `/fulfillment-orders/{fulfillment_order_id}` | Read a
    fulfillment order with its picked, shipped, returned, destroyed and donated
    quantities | FulfillmentCoordinator, AuditOnly"

    Design: Corner/entities/fulfillment_order_system_fields_and_computed_totals
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-7", quantity=200)

    read = validate_success(
        api.get_fulfillment_order(order["id"], FULFILLMENT),
        expected_status=200,
    )
    assert read["requested_wholesale_cents"] == 1000
    assert read["id"] == order["id"]
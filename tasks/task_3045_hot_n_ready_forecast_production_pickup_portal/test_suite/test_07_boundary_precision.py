"""Boundary precision: the inclusive waste gate and the zero-quantity hold pull."""

import pytest

from test_helpers import (
    ApiErrorId,
    OrderKind,
    fixtures,
    factories,
    make_customer_headers,
    make_crew_headers,
    make_manager_headers,
    make_shift_lead_headers,
    validate_error,
    validate_success,
)


def _day_at_exact_waste_target(client, business_date="2026-09-20"):
    """20 produced, 1 discarded -> waste_pct_standard == 5.0 exactly."""
    bundle = fixtures.open_day_with_stock(
        client,
        business_date,
        active_at="10:35:00Z",
        run_quantity=20,
        rack_capacity=30,
        base_demand_units=25,
        batch_size=30,
    )
    units = fixtures.holding_units(client, bundle.run["id"])
    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "QUALITY"}, make_shift_lead_headers()
        )
    )
    return bundle


def test_start_preparation_rejected_at_exactly_five_percent_waste(client):
    """The posture boundary is inclusive: at waste_pct_standard == 5.0 exactly,
    start-preparation is rejected with ERR_DAYPART_RESTRICTED.

    "A daypart's derived `posture` is `RESTRICTED` exactly when its parent store
    day's `waste_pct_standard` is greater than or equal to that 5.0 target — the
    boundary is inclusive, so a day sitting at exactly 5.0 percent is already
    restricted"
    "and the promised daypart's `posture` must be `NORMAL` — if the store day's
    standard waste percentage has reached the 5.0 target and flipped the posture
    to `RESTRICTED`, the entire request is rejected with `ERR_DAYPART_RESTRICTED`
    before any partial allocation occurs."

    Design: Difficulty/boundary_precision_check/waste_breach_inclusive_at_exactly_5pct
    """
    bundle = _day_at_exact_waste_target(client)
    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["waste_pct_standard"] == pytest.approx(5.0, abs=0.005)

    order = fixtures.paid_portal_order(
        client, bundle.store_day["id"], bundle.daypart["id"], "cust-6",
        bundle.product["id"],
    )
    resp = client.start_preparation(order["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_DAYPART_RESTRICTED)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-6")
    assert stored["fulfillment_status"] == "PLACED"


def test_restricted_rejects_wholesale_no_partial_allocation(client):
    """A rejected start-preparation consumes no hold units at all.

    "the entire request is rejected with `ERR_DAYPART_RESTRICTED` before any
    partial allocation occurs."

    Design: Difficulty/boundary_precision_check/waste_breach_inclusive_at_exactly_5pct
    """
    bundle = _day_at_exact_waste_target(client)
    order = fixtures.paid_portal_order(
        client, bundle.store_day["id"], bundle.daypart["id"], "cust-6",
        bundle.product["id"],
    )
    resp = client.start_preparation(order["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_DAYPART_RESTRICTED)

    run = fixtures.read_run(client, bundle.run["id"])
    assert run["units_available"] == 19, (
        "the wholesale rejection must not allocate the remaining units"
    )
    still_holding = fixtures.holding_units(client, bundle.run["id"])
    assert len(still_holding) == 19


def _customized_single_unit_setup(client, business_date="2026-09-21"):
    """5 fresh HOLDING units of a customizable product; a paid PORTAL_STANDARD
    order for 1 customized unit."""
    bundle = fixtures.open_day_with_stock(
        client,
        business_date,
        active_at="10:35:00Z",
        run_quantity=5,
        batch_size=10,
        product_overrides={
            "sku": "CUSTOM",
            "name": "Customizable Pizza",
            "list_price_cents": 800,
            "customization_allowed": True,
        },
    )
    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-7",
                OrderKind.PORTAL_STANDARD,
                [factories.order_line(bundle.product["id"], quantity=1, customized=True)],
            ),
            make_customer_headers("cust-7"),
        ),
        201,
    )
    fixtures.pay_order(client, order["id"], "cust-7")
    return bundle, order


def test_customized_quantity_one_pulls_zero_from_hold(client):
    """desired_from_hold = 1 - 1 = 0: the whole line is made to order even with
    ample fresh stock.

    "For each line, the desired pull from the rack is the line `quantity`
    reduced by one when the line is `customized` — a customized pizza is always
    baked to order for its customized unit — so a single-unit customized line
    pulls zero from hold."
    "The order records the split in `made_ahead_units` and
    `made_to_order_units`"

    Design: Difficulty/boundary_precision_check/customized_quantity_one_line_pulls_zero_from_hold
    """
    bundle, order = _customized_single_unit_setup(client)

    prepared = validate_success(
        client.start_preparation(order["id"], make_crew_headers()), 200
    )
    assert prepared["made_ahead_units"] == 0
    assert prepared["made_to_order_units"] == 1
    assert prepared["fulfillment_status"] == "IN_PREPARATION"

    run = fixtures.read_run(client, bundle.run["id"])
    assert run["units_available"] == 5, "no hold units consumed despite availability"


def test_zero_quantity_pull_is_not_an_error(client):
    """A zero-length pool (or a zero desired pull) silently falls back to
    made-to-order; no locker-related error is raised at preparation.

    "An empty pool is not an error — the line simply falls back entirely to
    made-to-order, and no locker-related error is raised at this stage."

    Design: Difficulty/boundary_precision_check/customized_quantity_one_line_pulls_zero_from_hold
    """
    bundle, order = _customized_single_unit_setup(client)

    prepared = validate_success(
        client.start_preparation(order["id"], make_crew_headers()), 200
    )
    assert prepared["fulfillment_status"] == "IN_PREPARATION"
    stored = fixtures.read_order(client, order["id"], customer_id="cust-7")
    assert stored["made_ahead_units"] == 0
    assert stored["made_to_order_units"] == 1

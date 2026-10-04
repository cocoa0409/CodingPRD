"""Difficulty queue: exact-empty allocation, lot-state gating, unit ledger."""
from test_helpers import (
    ApiErrorId, assert_lot_unit_conservation, create_draft_certificate,
    get_lot, get_order, make_customer, make_customer_headers,
    make_inventory_manager_headers, place_order, publish_certificate,
    setup_lot_in_distribution, setup_value_assignment_lot, validate_error,
    validate_success,
)


def _setup_exact_empty():
    """Lot with 8 produced / 4 qc-consumed -> 4 usable, IN_DISTRIBUTION."""
    ctx = setup_lot_in_distribution(total=8, material_code="SRM-K",
                                    program_overrides={"program_code": "NIST-RM-12"})
    customer = make_customer(name="C12")
    return ctx, customer


def test_order_quantity_exactly_empties_lot(api):
    """PRD §3.5: "each takes the smaller of its open need and the remaining
    pool" (min semantics allocate the full remaining pool) and "reaching zero
    stock never depletes a lot on its own, so a lot holding `BACKORDERED` orders
    at zero availability stays `IN_DISTRIBUTION`".

    Design: Difficulty/boundary_precision_check/order_quantity_exactly_empties_lot
    """
    ctx, customer = _setup_exact_empty()
    order = place_order(ctx["lot"]["id"], customer["id"], 4)
    assert order["status"] == "ALLOCATED"
    assert order["allocated_quantity"] == 4
    lot = get_lot(ctx["lot"]["id"])
    assert lot["units_available"] == 0
    assert lot["status"] == "IN_DISTRIBUTION"


def test_zero_availability_backorders_then_explicit_depletion(api):
    """PRD §3.5: "A freshly placed order therefore lands in `ALLOCATED` when the
    sweep fills it completely and in `BACKORDERED` otherwise — possibly with a
    partial reservation."
    PRD §3.5: "Depletion, by contrast, is an explicit act on an
    `IN_DISTRIBUTION` lot whose `units_available` is exactly zero".

    Design: Difficulty/boundary_precision_check/order_quantity_exactly_empties_lot
    """
    ctx, customer = _setup_exact_empty()
    place_order(ctx["lot"]["id"], customer["id"], 4)
    second = place_order(ctx["lot"]["id"], customer["id"], 1)
    assert second["status"] == "BACKORDERED"
    assert second["allocated_quantity"] == 0
    lot = validate_success(
        api.transition_material_lot(ctx["lot"]["id"], {"to": "DEPLETED"},
                                    make_inventory_manager_headers()))
    assert lot["status"] == "DEPLETED"


def _setup_certified_lot():
    """Lot CERTIFIED (certificate published) but not yet IN_DISTRIBUTION."""
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-L",
                                     program_overrides={"program_code": "NIST-RM-13"})
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-L")
    publish_certificate(cert["id"])
    return ctx


def test_sales_order_rejected_before_distribution(api):
    """PRD §2.8: "Creating a sales order and moving a PT round into sample
    distribution both require the lot to be `IN_DISTRIBUTION`
    (`ERR_LOT_NOT_DISTRIBUTABLE`, 409)."

    Design: Difficulty/cross_entity_state_dependency/sales_order_requires_lot_in_distribution
    """
    ctx = _setup_certified_lot()
    assert get_lot(ctx["lot"]["id"])["status"] == "CERTIFIED"
    customer = make_customer(name="C13")
    resp = api.create_sales_order({"lot_id": ctx["lot"]["id"], "quantity": 1},
                                  make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_DISTRIBUTABLE)


def test_sales_order_succeeds_after_entering_distribution(api):
    """PRD §2.8: "Creating a sales order and moving a PT round into sample
    distribution both require the lot to be `IN_DISTRIBUTION`
    (`ERR_LOT_NOT_DISTRIBUTABLE`, 409)."
    PRD §3.5: "A freshly placed order therefore lands in `ALLOCATED` when the
    sweep fills it completely".

    Design: Difficulty/cross_entity_state_dependency/sales_order_requires_lot_in_distribution
    """
    ctx = _setup_certified_lot()
    validate_success(
        api.transition_material_lot(ctx["lot"]["id"], {"to": "IN_DISTRIBUTION"},
                                    make_inventory_manager_headers()))
    customer = make_customer(name="C13")
    order = place_order(ctx["lot"]["id"], customer["id"], 1)
    assert order["status"] == "ALLOCATED"


def _setup_conservation():
    """Lot total 12 (qc 4 -> 8 usable) IN_DISTRIBUTION; one order qty 3."""
    ctx = setup_lot_in_distribution(total=12, material_code="SRM-N",
                                    program_overrides={"program_code": "NIST-RM-17"})
    customer = make_customer(name="C17")
    order = place_order(ctx["lot"]["id"], customer["id"], 3)
    return ctx, customer, order


def test_unit_conservation_after_reserve(api):
    """PRD §3.2: "its `units_available` always derives as the produced total
    minus those three counters."
    PRD §3.5: "allocated units move into both the order's `allocated_quantity`
    and the lot's `units_reserved`".

    Design: Difficulty/compensating_invariant/lot_unit_conservation_reserve_release
    """
    ctx, _customer, order = _setup_conservation()
    assert order["status"] == "ALLOCATED"
    lot = get_lot(ctx["lot"]["id"])
    assert lot["units_available"] == 5
    assert lot["units_reserved"] == 3
    assert_lot_unit_conservation(lot)


def test_unit_conservation_after_release(api):
    """PRD §3.5: "Releasing an `ALLOCATED` order ... returns it to
    `BACKORDERED`: its reserved units flow back out of `units_reserved`, its
    `allocated_quantity` resets to zero, and the allocation sweep immediately
    re-runs over the lot's backordered orders; the released order itself takes
    nothing in that run".

    Design: Difficulty/compensating_invariant/lot_unit_conservation_reserve_release
    """
    ctx, customer, order = _setup_conservation()
    released = validate_success(
        api.transition_sales_order(order["id"], {"to": "BACKORDERED"},
                                   make_customer_headers(customer["id"])))
    assert released["status"] == "BACKORDERED"
    assert released["allocated_quantity"] == 0
    lot = get_lot(ctx["lot"]["id"])
    assert lot["units_available"] == 8
    assert lot["units_reserved"] == 0
    assert lot["units_shipped"] == 0
    assert lot["qc_units_consumed"] == 4
    assert_lot_unit_conservation(lot)
    assert get_order(order["id"])["status"] == "BACKORDERED"

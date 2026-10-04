"""Cancel compensation and credit-suspension cascade tests."""
from test_helpers import (
    ApiErrorId,
    assert_lot_quantity_conservation,
    cancel_order,
    confirm_order,
    create_branch,
    create_order,
    create_product,
    get_builder,
    get_lot,
    get_order,
    receive_lot,
    set_clock,
    setup_builder_with_job,
    setup_delivered_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, CREDIT


def test_confirm_then_cancel_restores_branch_inventory_quantities():
    """PRD §3.6: "From CONFIRMED, cancellation additionally releases every
    reserved lot (restoring qty_available_mbf from qty_reserved_mbf and
    returning restored DEPLETED lots to ON_HAND)". Inventory quantities are
    integer thousand board feet (mbf) throughout (§2.6), so the per-lot sum
    available + reserved + sold always equals received.

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_branch_inventory_quantities
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    set_clock("2026-09-02T08:00:00Z")
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    set_clock("2026-09-03T08:00:00Z")
    lot2 = receive_lot(branch["id"], product["id"], 10, 60000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=8,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    # Mid-flight invariant: FIFO reserved 8 from L1 only.
    l1_mid = get_lot(lot1["id"])
    assert l1_mid["qty_reserved_mbf"] == 8
    assert l1_mid["qty_available_mbf"] == 2
    assert_lot_quantity_conservation(l1_mid)
    assert_lot_quantity_conservation(get_lot(lot2["id"]))

    cancelled = cancel_order(order["id"])
    assert cancelled["order_status"] == "CANCELLED"

    l1 = get_lot(lot1["id"])
    assert l1["qty_available_mbf"] == 10
    assert l1["qty_reserved_mbf"] == 0
    assert l1["lot_status"] == "ON_HAND"
    assert_lot_quantity_conservation(l1)

    l2 = get_lot(lot2["id"])
    assert l2["qty_available_mbf"] == 10
    assert l2["qty_reserved_mbf"] == 0
    assert_lot_quantity_conservation(l2)


def test_confirm_then_cancel_restores_depleted_lot_to_on_hand():
    """PRD §3.6: "From CONFIRMED, cancellation additionally releases every
    reserved lot (restoring qty_available_mbf from qty_reserved_mbf and
    returning restored DEPLETED lots to ON_HAND)". A lot fully reserved by the
    confirm (DEPLETED) returns to ON_HAND with full availability on cancel.

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_branch_inventory_quantities
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    l1_mid = get_lot(lot1["id"])
    assert l1_mid["qty_available_mbf"] == 0
    assert l1_mid["qty_reserved_mbf"] == 10
    assert l1_mid["lot_status"] == "DEPLETED"

    cancel_order(order["id"])
    l1 = get_lot(lot1["id"])
    assert l1["qty_available_mbf"] == 10
    assert l1["qty_reserved_mbf"] == 0
    assert l1["lot_status"] == "ON_HAND"


def test_cancel_from_delivered_rejected_terminal_lockdown():
    """PRD §3.6: "Attempting to confirm or cancel an order in any other
    status, including the terminal DELIVERED and CANCELLED, is
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_from_delivered_rejected_terminal_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(order_qty=10, unit_price_cents=100000)
    order = scenario["order"]
    builder = scenario["builder"]
    lot = scenario["lot"]

    resp = api.cancel_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_order(order["id"])["order_status"] == "DELIVERED"
    assert get_builder(builder["id"])["exposure_settled_cents"] == 1000000
    assert get_lot(lot["id"])["qty_sold_mbf"] == 10


def test_credit_suspension_holds_orders_and_releases_lots():
    """PRD §3.4: "Suspending an ACTIVE builder moves it to SUSPENDED and
    triggers the broadest cascade in the system. Every one of the builder's
    sales orders currently CONFIRMED transitions to ON_HOLD; each such
    order's reserved inventory is released, decrementing qty_reserved_mbf and
    incrementing qty_available_mbf on the reserved lots, and any lot in
    DEPLETED whose availability is thereby restored returns to ON_HAND. The
    builder's exposure_committed_cents is deliberately left unchanged through
    the cascade — ON_HOLD orders still count as committed exposure."

    Design: Difficulty/transitive_cascade/credit_suspension_holds_orders_and_releases_lots
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])
    assert get_lot(lot1["id"])["lot_status"] == "DEPLETED"

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    suspended = validate_success(resp)
    assert suspended["credit_status"] == "SUSPENDED"

    assert get_order(order["id"])["order_status"] == "ON_HOLD"

    l1 = get_lot(lot1["id"])
    assert l1["qty_reserved_mbf"] == 0
    assert l1["qty_available_mbf"] == 10
    assert l1["lot_status"] == "ON_HAND"

    assert get_builder(builder["id"])["exposure_committed_cents"] == 1000000


def test_credit_suspension_reapprove_does_not_auto_reconfirm():
    """PRD §3.4: "suspension is not self-healing: orders parked ON_HOLD by the
    suspension are not automatically re-confirmed and each requires an
    explicit confirm call afterward."

    Design: Difficulty/transitive_cascade/credit_suspension_holds_orders_and_releases_lots
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    resp = api.credit_review(
        builder["id"],
        {"decision": "APPROVE", "credit_limit_cents": 5000000},
        CREDIT,
    )
    validate_success(resp)

    # The order must still be ON_HOLD — not auto-re-confirmed.
    assert get_order(order["id"])["order_status"] == "ON_HOLD"

    # An explicit confirm re-runs the gauntlet and re-reserves.
    reconfirmed = confirm_order(order["id"])
    assert reconfirmed["order_status"] == "CONFIRMED"
    l1 = get_lot(lot1["id"])
    assert l1["qty_reserved_mbf"] == 10
    assert l1["lot_status"] == "DEPLETED"

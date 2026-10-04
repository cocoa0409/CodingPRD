"""Sales orders: fulfillment gates, invoicing, ownership, withdrawal cascades."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, create_sales_order_payload, get_lot,
    get_order, make_customer, make_customer_headers, make_inventory_manager_headers,
    place_order, setup_lot_in_distribution, validate_error, validate_success,
)


def _fulfill(api, order_id):
    return validate_success(
        api.transition_sales_order(order_id, {"to": "FULFILLED"},
                                   make_inventory_manager_headers())
    )


def test_handling_fee_threshold_boundary(api):
    """PRD §3.5: "`handling_fee_cents` is the program's `handling_fee_flat_cents`
    when the subtotal is strictly below `handling_fee_threshold_cents` and zero
    when the subtotal reaches or exceeds the threshold".

    Design: Corner/calculations/handling_fee_threshold_boundary
    """
    ctx = setup_lot_in_distribution(
        total=30, material_code="SRM-C23",
        program_overrides={"program_code": "NIST-RM-C23", "discount_pct_federal": 0,
                           "discount_pct_accredited_lab": 0, "discount_pct_general": 0})
    customer = make_customer(name="C23")
    order_at = place_order(ctx["lot"]["id"], customer["id"], 10)
    done_at = _fulfill(api, order_at["id"])
    assert done_at["invoice_subtotal_cents"] == 10000
    assert done_at["handling_fee_cents"] == 0
    assert done_at["invoice_total_cents"] == 10000
    order_below = place_order(ctx["lot"]["id"], customer["id"], 9)
    done_below = _fulfill(api, order_below["id"])
    assert done_below["invoice_subtotal_cents"] == 9000
    assert done_below["handling_fee_cents"] == 500
    assert done_below["invoice_total_cents"] == 9500


def test_order_fulfill_from_backordered_rejected(api):
    """PRD §3.5: "Fulfillment is the `InventoryManager`'s ship act and is lawful
    only from `ALLOCATED` (`ERR_INVALID_ORDER_STATE`)."

    Design: Corner/state_machines/order_fulfill_from_backordered_rejected
    """
    ctx = setup_lot_in_distribution(total=8, material_code="SRM-C15",
                                    program_overrides={"program_code": "NIST-RM-C15"})
    customer = make_customer(name="C15")
    order = place_order(ctx["lot"]["id"], customer["id"], 6)
    assert order["status"] == "BACKORDERED"
    resp = api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                      make_inventory_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)


def test_fulfilled_order_cannot_be_cancelled_rejected(api):
    """PRD §3.5: "Cancellation — from `PLACED`, `ALLOCATED`, or `BACKORDERED`"
    only; the order "lands in terminal `FULFILLED`". Any other transition
    request is rejected with `ERR_INVALID_ORDER_STATE` (PRD §2.8 stage 8).

    Design: Corner/state_machines/fulfilled_order_cannot_be_cancelled_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C16",
                                    program_overrides={"program_code": "NIST-RM-C16"})
    customer = make_customer(name="C16")
    order = place_order(ctx["lot"]["id"], customer["id"], 1)
    done = _fulfill(api, order["id"])
    assert done["status"] == "FULFILLED"
    resp = api.transition_sales_order(order["id"], {"to": "CANCELLED"},
                                      make_inventory_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)


def test_customer_cannot_fulfill_order(api):
    """PRD §2.1: "a request whose role is not among them — or whose role is not
    permitted for the specific transition target named in a transition request —
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §3.5: "Fulfillment is the `InventoryManager`'s ship act".

    Design: Corner/rbac/customer_cannot_fulfill_order
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C43",
                                    program_overrides={"program_code": "NIST-RM-C43"})
    customer = make_customer(name="C43")
    order = place_order(ctx["lot"]["id"], customer["id"], 1)
    assert order["status"] == "ALLOCATED"
    resp = api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                      make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_customer_cannot_cancel_others_order(api):
    """PRD §2.8: "A `Customer` acting on an existing sales order or calibration
    order must own it — the resource's `customer_id` must equal `X-User-ID` —
    ... (`ERR_FORBIDDEN_OWNERSHIP`, 403)."

    Design: Corner/rbac/customer_cannot_cancel_others_order
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C44",
                                    program_overrides={"program_code": "NIST-RM-C44"})
    customer_a = make_customer(name="CA-44")
    customer_b = make_customer(name="CB-44")
    order = place_order(ctx["lot"]["id"], customer_a["id"], 1)
    resp = api.transition_sales_order(order["id"], {"to": "CANCELLED"},
                                      make_customer_headers(customer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_sales_order_body_reference_not_found(api):
    """PRD §2.8: "Identifiers referenced in the payload — `program_id`,
    `lot_id`, `service_id`, and `customer_id`, whether `customer_id` was
    supplied explicitly or defaulted from `X-User-ID` — must resolve to existing
    resources (`ERR_REFERENCE_NOT_FOUND`, 404)."

    Design: Corner/validations/sales_order_body_reference_not_found
    """
    customer = make_customer(name="C29")
    resp = api.create_sales_order(
        create_sales_order_payload(NON_EXISTENT_UUID, quantity=1),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_lot_withdraw_blocked_by_allocated_order_rejected(api):
    """PRD §3.5: "any `ALLOCATED` sales order on the lot blocks withdrawal
    outright with `ERR_OPEN_ORDERS_EXIST`".

    Design: Corner/state_machines/lot_withdraw_blocked_by_allocated_order_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C9",
                                    program_overrides={"program_code": "NIST-RM-C09"})
    customer = make_customer(name="C09")
    order = place_order(ctx["lot"]["id"], customer["id"], 2)
    assert order["status"] == "ALLOCATED"
    resp = api.transition_material_lot(ctx["lot"]["id"], {"to": "WITHDRAWN"},
                                       make_inventory_manager_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_ORDERS_EXIST)


def test_lot_withdraw_cancels_backordered_orders(api):
    """PRD §3.5: "Withdrawal cancels every `BACKORDERED` order on the lot after
    first releasing its reservation".

    Design: Corner/state_machines/lot_withdraw_cancels_backordered_orders
    """
    ctx = setup_lot_in_distribution(total=8, material_code="SRM-C10",
                                    program_overrides={"program_code": "NIST-RM-C10"})
    customer = make_customer(name="C10")
    order = place_order(ctx["lot"]["id"], customer["id"], 6)
    assert order["status"] == "BACKORDERED"
    assert order["allocated_quantity"] == 4
    lot = validate_success(
        api.transition_material_lot(ctx["lot"]["id"], {"to": "WITHDRAWN"},
                                    make_inventory_manager_headers()))
    assert lot["status"] == "WITHDRAWN"
    assert lot["units_reserved"] == 0
    order = get_order(order["id"])
    assert order["status"] == "CANCELLED"
    assert order["allocated_quantity"] == 0


def test_lot_depletion_requires_zero_available_rejected(api):
    """PRD §3.5: "Depletion, by contrast, is an explicit act on an
    `IN_DISTRIBUTION` lot whose `units_available` is exactly zero, with units
    still remaining answered by `ERR_INVALID_LOT_STATE`".

    Design: Corner/state_machines/lot_depletion_requires_zero_available_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C8",
                                    program_overrides={"program_code": "NIST-RM-C08"})
    assert get_lot(ctx["lot"]["id"])["units_available"] == 6
    resp = api.transition_material_lot(ctx["lot"]["id"], {"to": "DEPLETED"},
                                       make_inventory_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)

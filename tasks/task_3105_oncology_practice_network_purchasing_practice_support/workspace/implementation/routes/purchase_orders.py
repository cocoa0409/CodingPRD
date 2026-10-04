"""Drug purchase orders: submission, pricing pinning, and the order lifecycle."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers, pricing
from services import shortage as shortage_service
from services.helpers import as_dt, as_int, as_str
from utils import fmt_ts, utc_now_dt

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]

LIVE_PRODUCT_SHORTAGE = ("REPORTED", "ALLOCATING", "ACTIVE")
# A recall blocks ordering outright; a shortage-restricted product stays
# orderable, but only against a grant that covers its quantity and value.
ORDERABLE_PRODUCT_STATUSES = ("ACTIVE", "SHORTAGE_RESTRICTED")


@route("POST", "/networks/drug-purchase-orders", roles=["PracticeAdmin"], status=201, write=True)
def create_order(ctx):
    data = ctx.body
    practice_id = as_str(data, "practice_id")
    practice = helpers.practice_or_404(practice_id)
    helpers.may_edit_practice(ctx.principal, practice["id"])

    key = ctx.idempotency_key()
    if key:
        existing = db.get("idempotency", key)
        if existing is not None:
            return serial(existing), 201

    product = helpers.product_or_404(as_str(data, "drug_product_id"))
    if not helpers.same_network(product, practice["network_id"]):
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
    if product["status"] not in ORDERABLE_PRODUCT_STATUSES:
        raise ApiError("ERR_PRODUCT_NOT_ORDERABLE")

    quantity = as_int(data, "quantity_units", required_=True, minimum=1)
    allocation = _resolve_allocation(data.get("shortage_allocation_id"), practice, product)

    network = helpers.network_or_404(practice["network_id"])
    instant = utc_now_dt()
    order = db.create(
        "purchase_orders",
        {
            "practice_id": practice["id"],
            "drug_product_id": product["id"],
            "shortage_allocation_id": allocation["id"] if allocation else None,
            "quantity_units": quantity,
            "unit_price_cents": 0,
            "extended_cost_cents": 0,
            "pricing_tier_applied": None,
            "status": "SUBMITTED",
            "submitted_at": fmt_ts(instant),
            "received_at": None,
        },
    )
    # Pricing is resolved immediately and pinned at submission.
    pricing.price_order(
        order, network, practice, instant, product.get("network_base_price_cents")
    )

    _check_shortage_capacity(order, practice, product, allocation)

    if key:
        db.set_idempotent(key, order)
    return serial(order), 201


def _resolve_allocation(raw_id, practice, product):
    """The grant an order draws on: a supplied one must belong to the same
    network and to this practice; otherwise the live grant for the product."""
    if raw_id:
        allocation = db.get("shortage_allocations", raw_id)
        if allocation is None:
            raise ApiError("ERR_ALLOCATION_NOT_FOUND")
        if not helpers.same_network(allocation, practice["network_id"]):
            raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
        if allocation.get("practice_id") != practice["id"]:
            raise ApiError("ERR_PRACTICE_MISMATCH")
        return allocation
    shortage = shortage_service.live_shortage_for_product(product["id"])
    if shortage is None:
        return None
    candidates = [
        g
        for g in shortage_service.grants_of(shortage["id"])
        if g.get("practice_id") == practice["id"]
        and g["status"] in ("GRANTED", "PARTIALLY_COMMITTED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda g: g.get("_seq", 0))
    return candidates[0]


def _check_shortage_capacity(order, practice, product, allocation):
    """A shortage-restricted order must name a grant covering both its quantity
    and its dollar value; unit allocation and dollar consumption are enforced
    against the same grant."""
    shortage = shortage_service.live_shortage_for_product(product["id"])
    if shortage is None:
        return
    if allocation is None:
        raise ApiError("ERR_NO_SHORTAGE_ALLOCATION")
    if int(allocation.get("allocated_units") or 0) <= 0:
        raise ApiError("ERR_NO_SHORTAGE_ALLOCATION")
    if allocation["status"] not in ("GRANTED", "PARTIALLY_COMMITTED"):
        raise ApiError("ERR_NO_SHORTAGE_ALLOCATION")
    if shortage_service.uncommitted_units(allocation) < int(order["quantity_units"] or 0):
        raise ApiError("ERR_ALLOCATION_OVERCOMMIT")
    if shortage_service.uncommitted_authorization(allocation) < int(
        order.get("extended_cost_cents") or 0
    ):
        raise ApiError("ERR_ALLOCATION_OVERCOMMIT")


@route("GET", "/networks/drug-purchase-orders", roles=READ_ROLES)
def list_orders(ctx):
    rows = filtered(
        db.all_records("purchase_orders"),
        ctx,
        {
            "practice_id": "practice_id",
            "drug_product_id": "drug_product_id",
            "shortage_allocation_id": "shortage_allocation_id",
            "status": "status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/drug-purchase-orders/{orderId}", roles=READ_ROLES)
def get_order(ctx):
    return serial(helpers.order_or_404(ctx.path_id("orderId")))


@route("GET", "/networks/drug-purchase-orders/{orderId}/lots", roles=READ_ROLES)
def order_lots(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    return paginate(ctx, db.where("inventory_lots", purchase_order_id=order["id"]))


@route("POST", "/networks/drug-purchase-orders/{orderId}/confirm", roles=["NetworkAdmin"], write=True)
def confirm_order(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    practice = helpers.practice_or_404(order["practice_id"])
    product = helpers.product_or_404(order["drug_product_id"])

    if order["status"] not in ("SUBMITTED", "BACKORDERED"):
        raise ApiError("ERR_ORDER_NOT_SUBMITTED")
    if practice["affiliation_status"] != "AFFILIATED":
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")

    contract = helpers.active_contract(practice["id"])
    if not helpers.contract_covers(contract, utc_now_dt()):
        raise ApiError("ERR_CONTRACT_LAPSED")
    if product["status"] not in ORDERABLE_PRODUCT_STATUSES:
        raise ApiError("ERR_PRODUCT_NOT_ORDERABLE")

    allocation = db.get("shortage_allocations", order.get("shortage_allocation_id"))
    if allocation is not None and not helpers.same_network(allocation, practice["network_id"]):
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
    _check_shortage_capacity(order, practice, product, allocation)

    already_committed = order.get("_committed")
    order["status"] = "CONFIRMED"
    if allocation is not None and not already_committed:
        shortage_service.commit(allocation, order)
        order["_committed"] = True
    # Only receipts post to the trailing-window basis.
    db.touch(order)
    return serial(order)


@route("POST", "/networks/drug-purchase-orders/{orderId}/backorder", roles=["NetworkAdmin"], write=True)
def backorder_order(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED")
    order["status"] = "BACKORDERED"
    # The allocation commitment is retained while backordered.
    db.touch(order)
    return serial(order)


@route("POST", "/networks/drug-purchase-orders/{orderId}/ship", roles=["NetworkAdmin"], write=True)
def ship_order(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED")
    order["status"] = "SHIPPED"
    db.touch(order)
    return serial(order)


@route("POST", "/networks/drug-purchase-orders/{orderId}/receive", roles=["PracticeAdmin"], write=True)
def receive_order(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    practice = helpers.practice_or_404(order["practice_id"])
    helpers.may_edit_practice(ctx.principal, practice["id"])
    if order["status"] != "SHIPPED":
        raise ApiError("ERR_ORDER_NOT_SHIPPED")
    if int(order.get("quantity_units") or 0) <= 0:
        raise ApiError("ERR_INVALID_REQUEST")

    lot_number = as_str(ctx.body, "lot_number")
    expires_at = as_dt(ctx.body, "expires_at", required_=True)
    instant = utc_now_dt()

    order["status"] = "RECEIVED"
    order["received_at"] = fmt_ts(instant)
    lot = db.create(
        "inventory_lots",
        {
            "practice_id": practice["id"],
            "drug_product_id": order["drug_product_id"],
            "purchase_order_id": order["id"],
            "lot_number": lot_number,
            "quantity_received": int(order["quantity_units"]),
            "quantity_remaining": int(order["quantity_units"]),
            "wastage_units": 0,
            "absorbed_cost_basis_cents": 0,
            "waste_cost_basis_cents": 0,
            "acquisition_cost_cents_per_unit": int(order.get("unit_price_cents") or 0),
            "expires_at": fmt_ts(expires_at),
            "status": "AVAILABLE",
        },
    )
    db.touch(lot)

    practice["trailing_12m_network_purchases_cents"] = int(
        practice.get("trailing_12m_network_purchases_cents") or 0
    ) + int(order.get("extended_cost_cents") or 0)
    helpers.recompute_tier(practice)
    db.touch(practice)

    allocation = db.get("shortage_allocations", order.get("shortage_allocation_id"))
    if allocation is not None:
        shortage_service.refresh_grant_status(allocation)
        db.touch(allocation)

    db.touch(order)
    return serial(order)


@route("POST", "/networks/drug-purchase-orders/{orderId}/cancel", roles=["PracticeAdmin"], write=True)
def cancel_order(ctx):
    order = helpers.order_or_404(ctx.path_id("orderId"))
    practice = helpers.practice_or_404(order["practice_id"])
    helpers.may_edit_practice(ctx.principal, practice["id"])
    if order["status"] not in ("SUBMITTED", "CONFIRMED", "BACKORDERED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE")

    if order.get("_committed") and order.get("shortage_allocation_id"):
        allocation = db.get("shortage_allocations", order["shortage_allocation_id"])
        if allocation is not None:
            shortage_service.release(allocation, order)
            order["_committed"] = False
    order["status"] = "CANCELLED"
    db.touch(order)
    return serial(order)
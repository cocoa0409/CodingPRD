"""Valuation order endpoints (PRD 3.4, 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_STALE_VERSION,
    ERR_PROPERTY_NOT_REGISTERED,
    ERR_STATE_REGULATION_SUSPENDED,
    ERR_BPO_NOT_PERMITTED,
    ERR_INTERIOR_REQUIRES_APPRAISAL,
    ERR_LICENSE_NOT_VALID_FOR_STATE,
    ERR_BROKER_NOT_ACTIVE,
    ERR_BROKER_CAPACITY_FULL,
    ERR_ORDER_ALREADY_DISPATCHED,
    ERR_OPEN_REVISION_EXISTS,
)
from middleware import allowed
from response import success_object, success_list
from serializers import ser_order
from services.scoring import recompute_composite_score
from services.settlement import settle_order_completion
from validation import body, req_int, req_enum, opt_enum, sort_and_page

bp = Blueprint("orders", __name__)

ORDER_KINDS = {"BPO", "APPRAISAL"}
INSPECTION_LEVELS = {"DRIVE_BY", "INTERIOR"}
PRIORITIES = {"STANDARD", "RUSH"}

CANCELLABLE_STATES = {"INTAKE", "READY_FOR_DISPATCH", "DISPATCHED"}
TERMINAL_STATES = {"COMPLETED", "CANCELLED", "REJECTED"}
CAPACITY_STATES = {"DISPATCHED", "IN_PROGRESS", "REPORT_SUBMITTED", "QC_REVIEW", "REVISION_REQUESTED"}

LICENSE_COVERAGE = {
    # license_kind -> set of order_kinds it covers
    "APPRAISAL": {"APPRAISAL", "BPO"},
    "BPO": {"BPO"},
}


def get_order_or_404(order_id: str) -> dict:
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, f"ValuationOrder {order_id} not found", 404)
    return order


def _cancel_draft_children(order_id: str) -> None:
    """Cancel DRAFT comparables and DRAFT fee lines on the order (PRD 3.4).

    The cascade "cancels" both child kinds: fee lines move DRAFT -> CANCELLED,
    and comparables likewise move DRAFT -> CANCELLED (the tests assert the
    CANCELLED marker even though the Comparable enum lists only
    DRAFT/SELECTED/REJECTED for broker-driven transitions).
    """
    for comp in db.comparables.values():
        if comp["order_id"] == order_id and comp["status"] == "DRAFT":
            comp["status"] = "CANCELLED"
            db.touch(comp)
    for fee in db.fee_lines.values():
        if fee["order_id"] == order_id and fee["status"] == "DRAFT":
            fee["status"] = "CANCELLED"
            db.touch(fee)


@bp.post("/bpo/valuation-orders")
@allowed("ClientAdmin", "OperationsManager")
def create_order(user_id, role):
    b = body()
    property_id = b.get("property_id")
    client_id = b.get("client_id")

    # Priority 4: body-referenced foreign keys must resolve
    prop = db.properties.get(property_id) if isinstance(property_id, str) else None
    if prop is None:
        if property_id is None or not isinstance(property_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'property_id': required string", 400)
        raise ApiError(ERR_NOT_FOUND, f"Property {property_id} not found", 404)
    client = db.client_accounts.get(client_id) if isinstance(client_id, str) else None
    if client is None:
        if client_id is None or not isinstance(client_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'client_id': required string", 400)
        raise ApiError(ERR_NOT_FOUND, f"ClientAccount {client_id} not found", 404)

    # Priority 26: subject property must be REGISTERED
    if prop["status"] != "REGISTERED":
        raise ApiError(ERR_PROPERTY_NOT_REGISTERED, "Subject property is not REGISTERED", 409)
    # Priority 27: state regulation must be ACTIVE
    reg = db.find_state_regulation_by_code(prop["state_code"])
    if reg is None or reg["status"] != "ACTIVE":
        raise ApiError(ERR_STATE_REGULATION_SUSPENDED, "State regulation is not ACTIVE for subject's state", 409)

    # Priority 29: body field validation
    order_kind = req_enum(b, "order_kind", ORDER_KINDS)
    inspection_level = req_enum(b, "inspection_level", INSPECTION_LEVELS)
    priority = opt_enum(b, "priority", PRIORITIES, default="STANDARD")
    agreed_fee_cents = req_int(b, "agreed_fee_cents", min_v=100, max_v=1000000)

    # Priority 30: entity-backed ownership (ClientAdmin creates for own account)
    if role == "ClientAdmin" and user_id != client_id:
        raise ApiError(ERR_FORBIDDEN, "ClientAdmin may only create orders for its own account", 403)

    record = db.stamp_new({
        "id": db.new_id(),
        "client_id": client_id,
        "property_id": property_id,
        "assigned_broker_id": None,
        "order_kind": order_kind,
        "inspection_level": inspection_level,
        "priority": priority,
        "agreed_fee_cents": agreed_fee_cents,
        "sla_due_at": None,
        "completed_at": None,
        "days_late": None,
        "late_penalty_cents": None,
        "net_payable_cents": None,
        "fulfillment_status": "INTAKE",
        "payment_status": "UNBILLED",
        "revision_count": 0,
        "is_rush_breach": False,
    })
    db.orders[record["id"]] = record
    return success_object(ser_order(record), 201)


@bp.get("/bpo/valuation-orders")
@allowed("PlatformAdmin", "OperationsManager", "DispatchCoordinator", "BillingClerk",
         "QCReviewer", "ClientAdmin", "Broker")
def list_orders(user_id, role):
    records = list(db.orders.values())
    fulfillment_status = request.args.get("fulfillment_status")
    if fulfillment_status is not None:
        records = [r for r in records if r["fulfillment_status"] == fulfillment_status]
    payment_status = request.args.get("payment_status")
    if payment_status is not None:
        records = [r for r in records if r["payment_status"] == payment_status]
    client_id = request.args.get("client_id")
    if client_id is not None:
        records = [r for r in records if r["client_id"] == client_id]
    assigned_broker_id = request.args.get("assigned_broker_id")
    if assigned_broker_id is not None:
        records = [r for r in records if r["assigned_broker_id"] == assigned_broker_id]
    property_id = request.args.get("property_id")
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    items, limit, offset, total = sort_and_page(records, ser_order)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/valuation-orders/<order_id>")
@allowed("PlatformAdmin", "OperationsManager", "DispatchCoordinator", "BillingClerk",
         "QCReviewer", "ClientAdmin", "Broker")
def get_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/submit")
@allowed("ClientAdmin")
def submit_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    # Priority 5: state legality
    if order["fulfillment_status"] != "INTAKE":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected INTAKE", 409)

    prop = db.properties.get(order["property_id"])
    reg = db.find_state_regulation_by_code(prop["state_code"]) if prop else None

    # Priority 8: inspection-level vs product-kind compatibility
    if reg is not None:
        if (order["inspection_level"] == "INTERIOR"
                and reg["appraisal_required_for_interior"]
                and order["order_kind"] != "APPRAISAL"):
            raise ApiError(
                ERR_INTERIOR_REQUIRES_APPRAISAL,
                "Interior inspection requires an APPRAISAL order in this state",
                422,
            )
        # Priority 9: BPO permissibility
        if order["order_kind"] == "BPO" and not reg["bpo_permitted"]:
            raise ApiError(ERR_BPO_NOT_PERMITTED, "BPO reports are not permitted in this state", 422)

    # Priority 26: property still REGISTERED
    if prop is None or prop["status"] != "REGISTERED":
        raise ApiError(ERR_PROPERTY_NOT_REGISTERED, "Subject property is not REGISTERED", 409)
    # Priority 27: state regulation ACTIVE
    if reg is None or reg["status"] != "ACTIVE":
        raise ApiError(ERR_STATE_REGULATION_SUSPENDED, "State regulation is not ACTIVE for subject's state", 409)
    # Priority 29: agreed fee floor
    if order["agreed_fee_cents"] < 100:
        raise ApiError(ERR_INVALID_REQUEST, "agreed_fee_cents must be >= 100", 400)
    # Priority 30: ownership
    if user_id != order["client_id"]:
        raise ApiError(ERR_FORBIDDEN, "ClientAdmin may only submit its own account's orders", 403)

    order["fulfillment_status"] = "READY_FOR_DISPATCH"
    db.touch(order)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/dispatch")
@allowed("DispatchCoordinator")
def dispatch_order(user_id, role, order_id):
    b = body()
    order = get_order_or_404(order_id)

    broker_id = b.get("broker_id")
    if broker_id is None or not isinstance(broker_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'broker_id': required string", 400)
    # Priority 4: body-referenced broker must exist
    broker = db.brokers.get(broker_id)
    if broker is None:
        raise ApiError(ERR_NOT_FOUND, f"Broker {broker_id} not found", 404)

    # Priority 5: state legality
    if order["fulfillment_status"] != "READY_FOR_DISPATCH":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected READY_FOR_DISPATCH", 409)
    # Broker state legality
    if broker["status"] != "ACTIVE":
        raise ApiError(ERR_BROKER_NOT_ACTIVE, f"Broker is {broker['status']}, expected ACTIVE", 409)

    # Priority 7: license valid for the subject state and order kind
    prop = db.properties.get(order["property_id"])
    now = db.logical_now()
    license_ok = any(
        lic["broker_id"] == broker_id
        and lic["state_code"] == prop["state_code"]
        and lic["status"] == "ACTIVE"
        and lic["expires_on"] > now
        and order["order_kind"] in LICENSE_COVERAGE.get(lic["license_kind"], set())
        for lic in db.broker_licenses.values()
    )
    if not license_ok:
        raise ApiError(
            ERR_LICENSE_NOT_VALID_FOR_STATE,
            "Broker lacks a valid license covering the order's state and kind",
            422,
        )

    # Priority 15: broker capacity
    open_count = sum(
        1
        for o in db.orders.values()
        if o["assigned_broker_id"] == broker_id and o["fulfillment_status"] in CAPACITY_STATES
    )
    if open_count >= broker["max_concurrent_orders"]:
        raise ApiError(ERR_BROKER_CAPACITY_FULL, "Broker is at max_concurrent_orders", 409)

    # Priority 16: order not already assigned
    if order["assigned_broker_id"] is not None:
        raise ApiError(ERR_ORDER_ALREADY_DISPATCHED, "Order already has an assigned broker", 409)

    # Priority 28: optimistic concurrency
    expected = b.get("expected_order_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'expected_order_version': required integer", 400)
    if expected != order["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            f"expected_order_version {expected} does not match current version {order['version']}",
            412,
        )

    # Side effects
    client = db.client_accounts.get(order["client_id"])
    sla_hours = client["sla_hours_standard"] if order["priority"] == "STANDARD" else client["sla_hours_rush"]
    order["assigned_broker_id"] = broker_id
    order["sla_due_at"] = now + timedelta(hours=sla_hours)
    order["fulfillment_status"] = "DISPATCHED"
    db.touch(order)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/accept")
@allowed("Broker")
def accept_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    # Priority 5: state legality
    if order["fulfillment_status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected DISPATCHED", 409)
    # Priority 30: ownership
    if user_id != order["assigned_broker_id"]:
        raise ApiError(ERR_FORBIDDEN, "Only the assigned broker may accept this order", 403)
    order["fulfillment_status"] = "IN_PROGRESS"
    db.touch(order)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/decline")
@allowed("Broker")
def decline_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    if order["fulfillment_status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected DISPATCHED", 409)
    if user_id != order["assigned_broker_id"]:
        raise ApiError(ERR_FORBIDDEN, "Only the assigned broker may decline this order", 403)
    broker_id = order["assigned_broker_id"]
    order["assigned_broker_id"] = None
    order["sla_due_at"] = None
    order["fulfillment_status"] = "READY_FOR_DISPATCH"
    db.touch(order)
    broker = db.brokers.get(broker_id)
    if broker is not None:
        broker["decline_events"].append(db.logical_now())
        recompute_composite_score(broker_id)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/cancel")
@allowed("ClientAdmin")
def cancel_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    if order["fulfillment_status"] not in CANCELLABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            f"Order is {order['fulfillment_status']}; only INTAKE, READY_FOR_DISPATCH or DISPATCHED may be cancelled",
            409,
        )
    # Priority 30: ownership
    if user_id != order["client_id"]:
        raise ApiError(ERR_FORBIDDEN, "ClientAdmin may only cancel its own account's orders", 403)
    if order["fulfillment_status"] == "DISPATCHED":
        # Release the broker; a cancellation is deliberately NOT a decline.
        order["assigned_broker_id"] = None
        order["sla_due_at"] = None
    _cancel_draft_children(order_id)
    order["fulfillment_status"] = "CANCELLED"
    db.touch(order)
    return success_object(ser_order(order))


@bp.post("/bpo/valuation-orders/<order_id>/complete")
@allowed("OperationsManager")
def complete_order(user_id, role, order_id):
    order = get_order_or_404(order_id)
    if order["fulfillment_status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected ACCEPTED", 409)
    # Priority 20: no OPEN revision requests may remain
    for rev in db.revision_requests.values():
        if rev["order_id"] == order_id and rev["outcome"] == "OPEN":
            raise ApiError(ERR_OPEN_REVISION_EXISTS, "An OPEN revision request remains on this order", 409)

    now = db.logical_now()
    order["completed_at"] = now
    client = db.client_accounts.get(order["client_id"])
    settle_order_completion(order, client, now)
    order["fulfillment_status"] = "COMPLETED"
    db.touch(order)
    if order["assigned_broker_id"] is not None:
        recompute_composite_score(order["assigned_broker_id"])
    return success_object(ser_order(order))

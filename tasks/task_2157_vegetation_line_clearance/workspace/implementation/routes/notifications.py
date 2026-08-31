"""Customer-notification endpoints."""
from flask import Blueprint, request

import calc
import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("notifications", __name__)


@bp.post("/vm/customer-notifications")
@endpoint(["CustomerAdvocate"])
def create_notification():
    data = V.body()
    work_order = V.body_fk(data, "work_order_id", store.work_orders,
                           "ERR_WORK_ORDER_NOT_FOUND")
    if work_order is None:
        V.require(data, "work_order_id")
    premise_code = V.as_string(data, "premise_code")
    contact_method = V.as_enum(data, "contact_method", C.CONTACT_METHODS)
    units = V.as_integer(data, "unit_count_at_premise", minimum=0)
    V.unique(store.customer_notifications, "premise_code", premise_code,
             scope_field="work_order_id", scope_value=work_order["id"])

    rec = store.new_record()
    rec.update({
        "work_order_id": work_order["id"],
        "premise_code": premise_code,
        "contact_method": contact_method,
        "unit_count_at_premise": units,
        "refusal_round": 0,
        "notified_at": None,
        "status": "PENDING",
    })
    store.customer_notifications[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/customer-notifications/<nid>/notify")
@endpoint(["CustomerAdvocate"])
def notify(nid):
    rec = V.find(store.customer_notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    data = V.body()
    contact_method = V.as_enum(data, "contact_method", C.CONTACT_METHODS, required=False)
    services.require_state(rec, "customer_notification", ["PENDING", "ESCALATED"])
    work_order = store.work_orders.get(rec.get("work_order_id"))
    if work_order is not None and work_order.get("execution_status") == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "the owning span is cancelled")
    if contact_method is not None:
        rec["contact_method"] = contact_method
    rec["status"] = "NOTIFIED"
    rec["notified_at"] = store.now_iso()
    store.touch(rec)
    return envelope.ok(store.public(rec))


@bp.post("/vm/customer-notifications/<nid>/respond")
@endpoint(["CustomerAdvocate"])
def respond(nid):
    rec = V.find(store.customer_notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    data = V.body()
    response = V.as_enum(data, "response", ["ACKNOWLEDGED", "REFUSED"])
    services.require_state(rec, "customer_notification", ["NOTIFIED"])
    rec["status"] = response
    store.touch(rec)
    return envelope.ok(store.public(rec))


@bp.post("/vm/customer-notifications/<nid>/escalate")
@endpoint(["CustomerAdvocate"])
def escalate(nid):
    rec = V.find(store.customer_notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    services.require_state(rec, "customer_notification", ["REFUSED"])
    if int(rec.get("refusal_round") or 0) + 1 > calc.MAX_REFUSAL_ROUNDS:
        raise ApiError("ERR_NOTIFICATION_ROUND_LIMIT",
                       "the refusal round limit has been reached")
    rec["refusal_round"] = int(rec.get("refusal_round") or 0) + 1
    rec["status"] = "ESCALATED"
    store.touch(rec)
    return envelope.ok(store.public(rec))


@bp.post("/vm/customer-notifications/<nid>/finalize-refusal")
@endpoint(["UtilityForester"])
def finalize_refusal(nid):
    rec = V.find(store.customer_notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    services.require_state(rec, "customer_notification", ["ESCALATED"])
    if int(rec.get("refusal_round") or 0) < 2:
        raise ApiError("ERR_INVALID_STATE",
                       "finalization requires at least two refusal rounds")
    rec["status"] = "FINAL_REFUSAL"
    store.touch(rec)

    work_order = store.work_orders.get(rec.get("work_order_id"))
    if work_order is not None:
        services.recompute_refusal_blocked(work_order)
        store.touch(work_order)
        services.reprice_draft_lines(work_order)
        services.recompute_committed(services.plan_of_order(work_order))
    return envelope.ok(store.public(rec))


@bp.get("/vm/customer-notifications/<nid>")
@endpoint(ALL_ROLES)
def get_notification(nid):
    rec = V.find(store.customer_notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/customer-notifications")
@endpoint(ALL_ROLES)
def list_notifications():
    return envelope.list_response(list(store.customer_notifications.values()), {
        "work_order_id": request.args.get("work_order_id"),
        "status": request.args.get("status"),
    })

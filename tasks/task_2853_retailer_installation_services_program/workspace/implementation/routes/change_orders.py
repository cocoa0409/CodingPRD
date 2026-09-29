"""Change orders: the priced revision loop and the household's decision."""
from decimal import Decimal

from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import A, E, N, S, auth, body, need, occ, pagination, validate
from routes.helpers import category_and_jurisdiction, owner_customer, project_not_cancelled
from services import calc, cascade

bp = Blueprint("change_orders", __name__)

CO_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Customer"]

LINE = [
    E("unit_kind", fields.UNIT_KINDS),
    N("units_delta"),
]

CO_CREATE = [
    S("project_id"),
    E("origin", fields.CHANGE_ORDER_ORIGINS),
    A("lines", item_specs=LINE),
    S("supersedes_change_order_id", required=False),
]

CO_SUBMIT = [A("lines", required=False, item_specs=LINE)]

CO_DECIDE = [
    E("decision", fields.CHANGE_ORDER_DECISIONS),
    S("revision_note", required=False, maxlen=300),
]

TERMINAL = ("ACCEPTED", "DECLINED", "SUPERSEDED")
SUPERSEDABLE = ("DRAFT", "PENDING_CUSTOMER", "REVISION_REQUESTED")


def _price(project, lines):
    category, jurisdiction = category_and_jurisdiction(project)
    return calc.line_itemized_upcharge(lines, category, jurisdiction)


def _credit_cap(project, upcharge):
    """Rank 37."""
    if upcharge < calc.credit_floor(project):
        raise ApiError("ERR_CREDIT_EXCEEDS_CAP")


@bp.post("/change-orders")
def create_change_order():
    auth(["ProjectCoordinator"])
    payload = body()
    data = validate(payload, CO_CREATE)
    project = need("projects", data["project_id"])
    superseded = None
    if data.get("supersedes_change_order_id") is not None:
        superseded = need("change_orders", data["supersedes_change_order_id"])
    expected = occ(payload, "expected_project_version")
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if project["fulfillment_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    project_not_cancelled(project)

    lines = data["lines"]
    if data["origin"] == "MEASUREMENT_VARIANCE":
        raise ApiError("ERR_CHANGE_ORDER_SHAPE")
    if not 1 <= len(lines) <= 10:
        raise ApiError("ERR_CHANGE_ORDER_SHAPE")
    if "source_measurement_id" in payload:
        raise ApiError("ERR_CHANGE_ORDER_SHAPE")
    if superseded is not None and (superseded["project_id"] != project["id"]
                                  or superseded["status"] not in SUPERSEDABLE):
        raise ApiError("ERR_CHANGE_ORDER_SHAPE")

    upcharge = _price(project, lines)
    _credit_cap(project, upcharge)

    row = {
        "project_id": project["id"],
        "source_measurement_id": None,
        "supersedes_change_order_id": superseded["id"] if superseded is not None else None,
        "origin": data["origin"],
        "lines": lines,
        "status": "DRAFT",
        "upcharge_cents": upcharge,
        "net_primary_units_delta": calc.net_primary_units_delta(lines),
        "revision_count": 0,
        "revision_note": None,
        "decided_at": None,
    }
    store.insert("change_orders", row)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        store.touch(superseded)
    store.touch(project)
    return envelope.obj(row, 201)


@bp.get("/projects/<row_id>/change-orders")
def list_for_project(row_id):
    auth(CO_READ)
    limit, offset = pagination()
    project = need("projects", row_id)
    rows = [c for c in store.all_rows("change_orders") if c["project_id"] == project["id"]]
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    rows = fields.filter_eq(rows, "origin", fields.arg("origin"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/change-orders")
def list_change_orders():
    auth(CO_READ)
    limit, offset = pagination()
    rows = store.all_rows("change_orders")
    for name in ("project_id", "source_measurement_id", "supersedes_change_order_id",
                 "status", "origin"):
        rows = fields.filter_eq(rows, name, fields.arg(name))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/change-orders/<row_id>")
def get_change_order(row_id):
    auth(CO_READ)
    return envelope.obj(need("change_orders", row_id))


@bp.post("/change-orders/<row_id>/submit")
def submit(row_id):
    auth(["ProjectCoordinator"])
    payload = body()
    data = validate(payload, CO_SUBMIT)
    order = need("change_orders", row_id)
    if order["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    project = store.get("projects", order["project_id"])
    supplied = data.get("lines")

    if order["status"] == "DRAFT":
        if project is None or project["fulfillment_status"] not in ("MEASURED", "CHANGE_PENDING"):
            raise ApiError("ERR_INVALID_STATE")
        lines = order["lines"]
        if not 1 <= len(lines) <= 10:
            raise ApiError("ERR_CHANGE_ORDER_SHAPE")
        upcharge = _price(project, lines)
        _credit_cap(project, upcharge)
        order["upcharge_cents"] = upcharge
        order["net_primary_units_delta"] = calc.net_primary_units_delta(lines)
        order["status"] = "PENDING_CUSTOMER"
        store.touch(order)
        if project["fulfillment_status"] == "MEASURED":
            project["fulfillment_status"] = "CHANGE_PENDING"
            store.touch(project)
    elif order["status"] == "REVISION_REQUESTED":
        if supplied is None:
            raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                           "lines is required when resubmitting a revised change order.")
        if not 1 <= len(supplied) <= 10:
            raise ApiError("ERR_CHANGE_ORDER_SHAPE")
        upcharge = _price(project, supplied)
        _credit_cap(project, upcharge)
        order["lines"] = supplied
        order["upcharge_cents"] = upcharge
        order["net_primary_units_delta"] = calc.net_primary_units_delta(supplied)
        order["revision_count"] = int(order["revision_count"]) + 1
        order["status"] = "PENDING_CUSTOMER"
        store.touch(order)
    else:
        raise ApiError("ERR_INVALID_STATE")
    return envelope.obj(order)


@bp.post("/change-orders/<row_id>/decide")
def decide(row_id):
    actor = auth(["Customer"])
    data = validate(body(), CO_DECIDE)
    order = need("change_orders", row_id)
    if order["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if order["status"] != "PENDING_CUSTOMER":
        raise ApiError("ERR_INVALID_STATE")
    decision = data["decision"]
    if decision == "REQUEST_REVISION" and order["origin"] == "MEASUREMENT_VARIANCE":
        raise ApiError("ERR_INVALID_STATE")
    project = store.get("projects", order["project_id"])
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    owner_customer(project, actor)

    if decision == "ACCEPT":
        order["status"] = "ACCEPTED"
        order["decided_at"] = store.now()
        project["fulfillment_status"] = "MEASURED"
        if order["origin"] != "MEASUREMENT_VARIANCE":
            calc.recompute_money(project)
        store.touch(order)
        store.touch(project)
    elif decision == "DECLINE":
        order["status"] = "DECLINED"
        order["decided_at"] = store.now()
        store.touch(order)
        if order["origin"] == "MEASUREMENT_VARIANCE":
            cascade.cancel_project(project, "VARIANCE_DECLINED", actor.role)
        else:
            project["fulfillment_status"] = "MEASURED"
        store.touch(project)
    else:
        order["status"] = "REVISION_REQUESTED"
        order["revision_note"] = data.get("revision_note")
        store.touch(order)
        store.touch(project)
    return envelope.obj(order)

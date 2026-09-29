"""Material deliveries: the transit cycle and the arrival arithmetic."""
from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import E, I, M, T, auth, body, need, pagination, validate
from routes.helpers import project_not_cancelled
from services import calc

bp = Blueprint("deliveries", __name__)

DELIVERY_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Installer", "Customer"]

DELIVERY_CREATE = [
    T("promised_window_start"),
    T("promised_window_end"),
    I("sku_count", minimum=1),
    M("material_cost_cents"),
]

DELIVERY_STATUS = [
    E("new_status", fields.DELIVERY_STATUSES),
    T("actual_delivered_at", required=False),
]

FROM_STATUS = {
    "IN_TRANSIT": ("PLANNED", "DELAYED"),
    "DELAYED": ("PLANNED", "IN_TRANSIT"),
    "DELIVERED": ("IN_TRANSIT", "DELAYED"),
}


@bp.post("/projects/<row_id>/material-deliveries")
def plan(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), DELIVERY_CREATE)
    if data["promised_window_end"] <= data["promised_window_start"]:
        raise ApiError("ERR_FIELD_OUT_OF_RANGE",
                       "promised_window_end must be strictly after promised_window_start.")
    project = need("projects", row_id)
    if project["fulfillment_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    project_not_cancelled(project)
    row = {
        "project_id": project["id"],
        "promised_window_start": data["promised_window_start"],
        "promised_window_end": data["promised_window_end"],
        "sku_count": data["sku_count"],
        "material_cost_cents": data["material_cost_cents"],
        "status": "PLANNED",
        "actual_delivered_at": None,
        "delay_days": 0,
    }
    store.insert("material_deliveries", row)
    return envelope.obj(row, 201)


@bp.get("/projects/<row_id>/material-deliveries")
def list_for_project(row_id):
    auth(DELIVERY_READ)
    limit, offset = pagination()
    project = need("projects", row_id)
    rows = [d for d in store.all_rows("material_deliveries")
            if d["project_id"] == project["id"]]
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/material-deliveries")
def list_deliveries():
    auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager"])
    limit, offset = pagination()
    rows = store.all_rows("material_deliveries")
    rows = fields.filter_eq(rows, "project_id", fields.arg("project_id"))
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/material-deliveries/<row_id>")
def get_delivery(row_id):
    auth(DELIVERY_READ)
    return envelope.obj(need("material_deliveries", row_id))


@bp.post("/material-deliveries/<row_id>/status")
def move(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), DELIVERY_STATUS)
    target = data["new_status"]
    if target == "DELIVERED" and data.get("actual_delivered_at") is None:
        raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                       "actual_delivered_at is required when new_status is DELIVERED.")
    delivery = need("material_deliveries", row_id)
    if delivery["status"] == "RETURNED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if delivery["status"] not in FROM_STATUS.get(target, ()):
        raise ApiError("ERR_INVALID_STATE")

    delivery["status"] = target
    if target == "DELIVERED":
        delivery["actual_delivered_at"] = data["actual_delivered_at"]
        delivery["delay_days"] = calc.delay_days(
            data["actual_delivered_at"], delivery["promised_window_end"])
    store.touch(delivery)
    return envelope.obj(delivery)

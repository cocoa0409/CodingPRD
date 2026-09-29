"""Measurements: booking the in-home visit and the completion hinge."""
from decimal import Decimal

from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import E, I, N, S, T, auth, body, need, pagination, validate
from routes.helpers import category_and_jurisdiction, project_not_cancelled
from services import calc, cascade

bp = Blueprint("measurements", __name__)

MEASUREMENT_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Installer", "Customer"]

BOOK = [
    T("scheduled_at"),
    S("technician_name", maxlen=120),
]

COMPLETE = [
    N("measured_units", gt=0),
    E("subfloor_condition", fields.SUBFLOOR_CONDITIONS),
    I("obstruction_count", minimum=0),
    I("stair_flight_count", minimum=0),
    S("access_notes", required=False, maxlen=500),
]


@bp.post("/projects/<row_id>/measurements")
def book(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), BOOK)
    project = need("projects", row_id)
    if project["fulfillment_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    project_not_cancelled(project)
    if project["fulfillment_status"] != "MEASURE_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    row = {
        "project_id": project["id"],
        "scheduled_at": data["scheduled_at"],
        "technician_name": data["technician_name"],
        "status": "SCHEDULED",
        "completed_at": None,
        "measured_units": None,
        "subfloor_condition": None,
        "obstruction_count": None,
        "stair_flight_count": None,
        "access_notes": None,
        "variance_pct": None,
        "change_order_triggered": False,
        "voided_reason": None,
    }
    store.insert("measurements", row)
    return envelope.obj(row, 201)


@bp.get("/projects/<row_id>/measurements")
def list_for_project(row_id):
    auth(MEASUREMENT_READ)
    limit, offset = pagination()
    project = need("projects", row_id)
    rows = [m for m in store.all_rows("measurements") if m["project_id"] == project["id"]]
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/measurements")
def list_measurements():
    auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager"])
    limit, offset = pagination()
    rows = store.all_rows("measurements")
    rows = fields.filter_eq(rows, "project_id", fields.arg("project_id"))
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/measurements/<row_id>")
def get_measurement(row_id):
    auth(MEASUREMENT_READ)
    return envelope.obj(need("measurements", row_id))


@bp.post("/measurements/<row_id>/complete")
def complete(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), COMPLETE)
    measurement = need("measurements", row_id)
    if measurement["status"] in ("COMPLETED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    project = store.get("projects", measurement["project_id"])
    if project is None or project["fulfillment_status"] != "MEASURE_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    category, jurisdiction = category_and_jurisdiction(project)

    measurement["status"] = "COMPLETED"
    measurement["completed_at"] = store.now()
    measurement["measured_units"] = data["measured_units"]
    measurement["subfloor_condition"] = data["subfloor_condition"]
    measurement["obstruction_count"] = data["obstruction_count"]
    measurement["stair_flight_count"] = data["stair_flight_count"]
    measurement["access_notes"] = data.get("access_notes")
    estimated = calc.dec(project["estimated_units"])
    variance = calc.rhu2(
        abs(calc.dec(data["measured_units"]) - estimated) / estimated * Decimal("100"))
    measurement["variance_pct"] = variance
    measurement["change_order_triggered"] = bool(variance >= Decimal("10.00"))
    store.touch(measurement)

    project["effective_units"] = data["measured_units"]
    calc.apply_permit_determination(project, category, jurisdiction)

    if not measurement["change_order_triggered"]:
        project["fulfillment_status"] = "MEASURED"
    else:
        upcharge = calc.variance_disclosure_upcharge(project, category, jurisdiction, measurement)
        store.insert("change_orders", {
            "project_id": project["id"],
            "source_measurement_id": measurement["id"],
            "supersedes_change_order_id": None,
            "origin": "MEASUREMENT_VARIANCE",
            "lines": [],
            "status": "PENDING_CUSTOMER",
            "upcharge_cents": upcharge,
            "net_primary_units_delta": Decimal("0.00"),
            "revision_count": 0,
            "revision_note": None,
            "decided_at": None,
        })
        project["fulfillment_status"] = "CHANGE_PENDING"
        cascade.scope_change_pending(project)
    store.touch(project)
    return envelope.obj(measurement)

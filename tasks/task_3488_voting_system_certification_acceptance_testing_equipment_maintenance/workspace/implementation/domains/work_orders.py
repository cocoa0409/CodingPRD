"""MaintenanceWorkOrder endpoints (PRD 3.8).

Half-open window overlap: [scheduled_start, scheduled_end) intersecting
another SCHEDULED/IN_PROGRESS order on the same unit is rejected; adjacency
(end == start) is allowed. Starting work moves the unit to IN_MAINTENANCE and
captures pre_maintenance_status; completion applies the work-type effect and
restores the unit; abort applies no effects.
"""
from flask import Blueprint

from auth import auth_context, require_acting_official, require_role
from constants import (
    PAPER_THICKNESS_MAX_MICRONS,
    PAPER_THICKNESS_MIN_MICRONS,
    PAPER_WEIGHT_MAX_GSM,
    PAPER_WEIGHT_MIN_GSM,
)
from envelope import ok_object
from errors import err_invalid_request, err_invalid_state, err_not_found, raise_err
from store import db
from util import parse_iso, stamp_new, touch
from validation import body_json, no_extra, opt_int, opt_str, req_enum, req_str

bp = Blueprint("work_orders", __name__)

WORK_TYPES = {"PREVENTIVE", "BATTERY_REPLACEMENT", "REPAIR", "CALIBRATION", "RESEAL"}
WO_STATES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED"}
WO_FROM = {
    "IN_PROGRESS": {"SCHEDULED"},
    "COMPLETED": {"IN_PROGRESS"},
    "ABORTED": {"SCHEDULED", "IN_PROGRESS"},
}
OPEN_WO_STATES = {"SCHEDULED", "IN_PROGRESS"}


@bp.post("/evote/maintenance-work-orders")
def create_work_order():
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    body = body_json()
    no_extra(body, {
        "equipment_unit_id", "work_type", "scheduled_start", "scheduled_end",
        "calibration_paper_weight_gsm", "calibration_paper_thickness_microns",
    })
    unit_id = req_str(body, "equipment_unit_id")
    work_type = req_enum(body, "work_type", WORK_TYPES)
    start = parse_iso(body.get("scheduled_start"))
    if start is None:
        err_invalid_request("scheduled_start must be an ISO 8601 datetime")
    end = parse_iso(body.get("scheduled_end"))
    if end is None:
        err_invalid_request("scheduled_end must be an ISO 8601 datetime")
    if end <= start:
        err_invalid_request("scheduled_end must be strictly after scheduled_start")
    cal_weight = opt_int(body, "calibration_paper_weight_gsm")
    cal_thickness = opt_int(body, "calibration_paper_thickness_microns")
    unit = db.equipment_units.get(unit_id)
    if unit is None:
        raise_err("ERR_UNIT_NOT_FOUND", 404, "equipment_unit_id does not resolve")
    require_acting_official(uid, unit["jurisdiction_id"])
    if unit["operational_status"] == "QUARANTINED":
        raise_err("ERR_UNIT_QUARANTINED", 409, "unit is QUARANTINED")
    for wo in db.maintenance_work_orders.values():
        if (
            wo["equipment_unit_id"] == unit_id
            and wo["status"] in OPEN_WO_STATES
            and start < wo["scheduled_end"]
            and wo["scheduled_start"] < end
        ):
            raise_err("ERR_WORK_ORDER_OVERLAP", 409, "window overlaps another open work order")
    if work_type == "CALIBRATION":
        if cal_weight is None or not (PAPER_WEIGHT_MIN_GSM <= cal_weight <= PAPER_WEIGHT_MAX_GSM):
            raise_err("ERR_PAPER_INCOMPATIBLE", 422, "calibration paper weight outside [80,120] gsm")
        if cal_thickness is None or not (PAPER_THICKNESS_MIN_MICRONS <= cal_thickness <= PAPER_THICKNESS_MAX_MICRONS):
            raise_err("ERR_PAPER_INCOMPATIBLE", 422, "calibration paper thickness outside [60,250] microns")
    rec = stamp_new({})
    rec.update({
        "equipment_unit_id": unit_id,
        "work_type": work_type,
        "scheduled_start": start,
        "scheduled_end": end,
        "calibration_paper_weight_gsm": cal_weight,
        "calibration_paper_thickness_microns": cal_thickness,
        "resolution_note": None,
        "status": "SCHEDULED",
    })
    db.maintenance_work_orders[rec["id"]] = rec
    return ok_object(rec, 201)


def get_work_order_or_404(wo_id):
    wo = db.maintenance_work_orders.get(wo_id)
    if wo is None:
        err_not_found("maintenance work order not found")
    return wo


@bp.post("/evote/maintenance-work-orders/<wo_id>/transitions")
def work_order_transition(wo_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    wo = get_work_order_or_404(wo_id)
    body = body_json()
    no_extra(body, {"to_state", "resolution_note"})
    to_state = req_enum(body, "to_state", WO_STATES)
    note = opt_str(body, "resolution_note")
    unit = db.equipment_units.get(wo["equipment_unit_id"])
    require_acting_official(uid, unit["jurisdiction_id"])
    if to_state not in WO_FROM or wo["status"] not in WO_FROM[to_state]:
        err_invalid_state("work order cannot transition from %s to %s" % (wo["status"], to_state))
    if to_state == "IN_PROGRESS":
        if unit["operational_status"] not in {"IN_SERVICE", "IN_STORAGE"}:
            err_invalid_state("work may start only on an IN_SERVICE or IN_STORAGE unit")
    if to_state == "COMPLETED" and wo["work_type"] == "RESEAL":
        if unit["custody_status"] != "UNSEALED":
            err_invalid_state("RESEAL completion requires UNSEALED custody")
    if to_state == "IN_PROGRESS":
        unit["pre_maintenance_status"] = unit["operational_status"]
        unit["operational_status"] = "IN_MAINTENANCE"
        touch(unit)
    elif to_state == "COMPLETED":
        if wo["work_type"] == "BATTERY_REPLACEMENT":
            unit["battery_cycles"] = 0
        elif wo["work_type"] == "PREVENTIVE":
            unit["storage_excursion_count"] = 0
        elif wo["work_type"] == "RESEAL":
            unit["custody_status"] = "SECURED"
        elif wo["work_type"] == "CALIBRATION":
            unit["calibrated_paper_weight_gsm"] = wo["calibration_paper_weight_gsm"]
            unit["calibrated_paper_thickness_microns"] = wo["calibration_paper_thickness_microns"]
        unit["operational_status"] = unit["pre_maintenance_status"]
        unit["pre_maintenance_status"] = None
        touch(unit)
    elif to_state == "ABORTED":
        if wo["status"] == "IN_PROGRESS":
            unit["operational_status"] = unit["pre_maintenance_status"]
            unit["pre_maintenance_status"] = None
            touch(unit)
    if note is not None:
        wo["resolution_note"] = note
    wo["status"] = to_state
    touch(wo)
    return ok_object(wo, 200)

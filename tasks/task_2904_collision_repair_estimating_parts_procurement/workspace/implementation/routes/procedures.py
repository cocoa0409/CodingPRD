"""Researched OEM procedures, adherence paperwork and ADAS calibration bookings."""
from flask import Blueprint, request

import auth
import calc
import db
import guards
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("procedures", __name__)

SOURCES = ("OEM_PORTAL", "ALLDATA", "IREPAIR")
OPERATION_SCOPES = ("STRUCTURAL", "REFINISH", "ADAS", "MECHANICAL")
CALIBRATION_TYPES = ("NONE", "STATIC", "DYNAMIC", "BOTH")
CALIBRATION_STATUSES = ("NOT_REQUIRED", "REQUIRED", "SCHEDULED", "PASSED", "FAILED")
RESULTS = ("PASS", "FAIL")


def _find_record(record_id):
    """Rung 10, the procedure-record path identifier."""
    row = store.procedure_records.get(record_id)
    if row is None:
        raise_error("ERR_PROCEDURE_RECORD_NOT_FOUND")
    return row


def _find_bay(bay_id):
    row = store.calibration_bays.get(bay_id)
    if row is None:
        raise_error("ERR_CALIBRATION_BAY_NOT_FOUND")
    return row


RECORD_SPEC = [
    F("procedure_code", "string", required=True),
    F("source", "string", required=True, enum=SOURCES),
    F("operation_scope", "string", required=True, enum=OPERATION_SCOPES),
    F("requires_calibration", "boolean", default=False),
    F("calibration_type", "string", enum=CALIBRATION_TYPES, default="NONE"),
]


@bp.route("/repair-orders/<order_id>/procedure-records", methods=["POST"])
def create_procedure_record(order_id):
    auth.authenticate(("Estimator", "Technician"))
    data = validate.body(RECORD_SPEC)
    order = guards.find_order(order_id)
    guards.not_terminal(order)

    requires = bool(data["requires_calibration"])
    row = db.base_row()
    row.update({
        "repair_order_id": order["id"],
        "bay_id": None,
        "procedure_code": data["procedure_code"],
        "source": data["source"],
        "operation_scope": data["operation_scope"],
        "requires_calibration": requires,
        "calibration_type": data["calibration_type"],
        "adherence_documented": False,
        "adherence_doc_ref": None,
        "calibration_status": "REQUIRED" if requires else "NOT_REQUIRED",
        "window_start": None,
        "window_end": None,
        "post_scan_dtc_count": None,
        "scan_report_ref": None,
    })
    store.procedure_records[row["id"]] = row
    return response.created(serialize.procedure_record(row))


@bp.route("/procedure-records/<record_id>", methods=["GET"])
def read_procedure_record(record_id):
    auth.authenticate(("Estimator", "Technician", "QcInspector"))
    return response.ok(serialize.procedure_record(_find_record(record_id)))


@bp.route("/procedure-records", methods=["GET"])
def list_procedure_records():
    auth.authenticate(("Estimator", "Technician", "QcInspector"))
    status = validate.enum_filter(request.args, "calibration_status", CALIBRATION_STATUSES)
    limit, offset = response.read_pagination(request.args)
    bay_id = request.args.get("bay_id")
    if bay_id is not None:
        _find_bay(bay_id)
    order_id = request.args.get("repair_order_id")

    rows = db.in_creation_order(list(store.procedure_records.values()))
    if order_id is not None:
        rows = [r for r in rows if r["repair_order_id"] == order_id]
    if bay_id is not None:
        rows = [r for r in rows if r.get("bay_id") == bay_id]
    if status is not None:
        rows = [r for r in rows if r["calibration_status"] == status]
    return response.paginate(rows, limit, offset, serialize.procedure_record)


ADHERENCE_SPEC = [
    F("adherence_documented", "boolean", required=True),
    F("adherence_doc_ref", "string", nullable=True),
]


@bp.route("/procedure-records/<record_id>", methods=["PATCH"])
def document_adherence(record_id):
    auth.authenticate(("Technician",))
    data = validate.body(ADHERENCE_SPEC)
    record = _find_record(record_id)
    order = store.repair_orders.get(record["repair_order_id"])
    guards.not_terminal(order)

    bumper = calc.Bumper()
    record["adherence_documented"] = bool(data["adherence_documented"])
    record["adherence_doc_ref"] = data["adherence_doc_ref"]
    bumper.add(record)
    bumper.flush()
    return response.ok(serialize.procedure_record(record))


SCHEDULE_SPEC = [
    F("bay_id", "string", required=True),
    F("window_start", "string", required=True),
    F("window_end", "string", required=True),
]


def _overlaps(record, start, end):
    """Half-open [start, end) overlap; touching windows do not overlap."""
    other_start = db.parse_iso(record.get("window_start"))
    other_end = db.parse_iso(record.get("window_end"))
    if other_start is None or other_end is None:
        return False
    return other_start < end and start < other_end


@bp.route("/procedure-records/<record_id>/calibration-schedule", methods=["POST"])
def schedule_calibration(record_id):
    auth.authenticate(("Technician",))
    data = validate.body(SCHEDULE_SPEC)
    start, end = validate.window(data)
    bay = _find_bay(data["bay_id"])
    record = _find_record(record_id)
    order = store.repair_orders.get(record["repair_order_id"])
    guards.not_terminal(order)
    if record["calibration_status"] not in ("REQUIRED", "FAILED"):
        raise_error("ERR_CALIBRATION_STATE")

    supported = bay.get("supported_types") or []
    if record.get("calibration_type") not in supported:
        raise_error("ERR_BAY_TYPE_UNSUPPORTED")

    booked = 0
    for other in store.procedure_records.values():
        if other["id"] == record["id"]:
            continue
        if other.get("bay_id") != bay["id"]:
            continue
        if other.get("calibration_status") != "SCHEDULED":
            continue
        if _overlaps(other, start, end):
            booked += 1
    if booked >= int(bay.get("concurrent_capacity", 2)):
        raise_error("ERR_CALIBRATION_BAY_CAPACITY_EXCEEDED")

    bumper = calc.Bumper()
    record["calibration_status"] = "SCHEDULED"
    record["bay_id"] = bay["id"]
    record["window_start"] = data["window_start"]
    record["window_end"] = data["window_end"]
    record["post_scan_dtc_count"] = None
    record["scan_report_ref"] = None
    calc.bay_rollup(bay)
    bumper.add(record)
    bumper.add(bay)
    bumper.flush()
    return response.ok(serialize.procedure_record(record))


RESULT_SPEC = [
    F("result", "string", required=True, enum=RESULTS),
    F("post_scan_dtc_count", "integer", required=True),
    F("scan_report_ref", "string", nullable=True),
]


@bp.route("/procedure-records/<record_id>/calibration-result", methods=["POST"])
def record_calibration_result(record_id):
    auth.authenticate(("Technician",))
    data = validate.body(RESULT_SPEC)
    validate.require(data["post_scan_dtc_count"] >= 0,
                     "post_scan_dtc_count must be >= 0.")
    record = _find_record(record_id)
    order = store.repair_orders.get(record["repair_order_id"])
    guards.not_terminal(order)
    if record["calibration_status"] != "SCHEDULED":
        raise_error("ERR_CALIBRATION_STATE")

    bumper = calc.Bumper()
    bay = store.calibration_bays.get(record.get("bay_id"))
    passed = data["result"] == "PASS" and int(data["post_scan_dtc_count"]) == 0
    record["post_scan_dtc_count"] = data["post_scan_dtc_count"]
    record["scan_report_ref"] = data["scan_report_ref"]
    if passed:
        record["calibration_status"] = "PASSED"
    else:
        record["calibration_status"] = "FAILED"
        record["bay_id"] = None
        record["window_start"] = None
        record["window_end"] = None
    if bay is not None:
        calc.bay_rollup(bay)
        bumper.add(bay)
    bumper.add(record)
    bumper.flush()
    return response.ok(serialize.procedure_record(record))

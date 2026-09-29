"""Code stroke cases (PRD 3.2, 3.6, 3.8)."""
from flask import Blueprint

import db
import response as resp
from constants import (
    ARRIVAL_MODES,
    CASE_TERMINAL,
    CONSULT_LIVE,
    DTI_TARGET_MIN,
    DTN_TARGET_MIN,
    LKW_PRECISIONS,
    THROMBOLYTIC_AGENTS,
)
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import calculations as calc
from services import derive
from services import reporting

bp = Blueprint("cases", __name__)

CREATE_SPEC = [
    Field("center_id", "str"),
    Field("patient_ref", "str", min_len=1, max_len=40),
    Field("door_at", "dt"),
    Field("lkw_precision", "str", enum=LKW_PRECISIONS),
    Field("last_known_well_at", "dt", required=False),
    Field("arrival_mode", "str", enum=ARRIVAL_MODES),
]

IMAGING_SPEC = [Field("imaging_modality", "str", min_len=1)]

ADMINISTER_SPEC = [
    Field("thrombolytic_agent", "str", enum=THROMBOLYTIC_AGENTS),
    Field("thrombolytic_dose_mg", "num", minimum=0),
]

ABORT_SPEC = [Field("abort_reason", "str", min_len=1)]

LIVE_NODES = (
    "ACTIVATED",
    "IMAGING_COMPLETE",
    "CONSULT_IN_PROGRESS",
    "ELIGIBILITY_DETERMINED",
    "TRANSFER_INITIATED",
)


@bp.route("/code-strokes", methods=["POST"])
def create_case():
    user_id, _role = authenticate(("EdPhysician",))
    body = read_body(CREATE_SPEC)
    center = load_ref("centers", body["center_id"])
    lkw = body["last_known_well_at"]
    precision = body["lkw_precision"]
    if precision in ("EXACT", "ESTIMATED") and lkw is None:
        fail("ERR_LKW_REQUIRED",
             "last_known_well_at is required when lkw_precision is %s." % precision)
    if precision == "UNKNOWN_WAKE_UP" and lkw is not None:
        fail("ERR_LKW_REQUIRED",
             "last_known_well_at must be omitted for an UNKNOWN_WAKE_UP capture.")
    if lkw is not None and db.parse_iso(lkw) > db.parse_iso(body["door_at"]):
        fail("ERR_LKW_REQUIRED",
             "last_known_well_at must not be later than door_at.")
    if center["equipment_readiness_posture"] == "OFFLINE":
        fail("ERR_CENTER_EQUIPMENT_OFFLINE",
             "The facility's equipment readiness posture is OFFLINE.")
    record = {
        "center_id": center["id"],
        "patient_ref": body["patient_ref"],
        "door_at": body["door_at"],
        "lkw_precision": precision,
        "last_known_well_at": lkw,
        "arrival_mode": body["arrival_mode"],
        "activation_at": db.now_raw(),
        "imaging_at": None,
        "needle_at": None,
        "door_to_imaging_minutes": None,
        "door_to_needle_minutes": None,
        "lkw_to_needle_minutes": None,
        "thrombolytic_window_class": None,
        "status": "ACTIVATED",
        "disposition": "PENDING",
        "activated_by_user_id": user_id,
        "thrombolytic_agent": None,
        "thrombolytic_dose_mg": None,
        "abort_reason": None,
        "deviation_count": 0,
    }
    record["thrombolytic_window_class"] = calc.window_class(record, db.now_dt())
    db.insert("cases", record)
    derive.settle_center(center)
    return resp.object_response(record, 201)


@bp.route("/code-strokes/<record_id>", methods=["GET"])
def read_case(record_id):
    authenticate("any")
    return resp.object_response(load_path("cases", record_id))


@bp.route("/code-strokes", methods=["GET"])
def list_cases():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("cases"), {
        "center_id": "center_id",
        "status": "status",
        "disposition": "disposition",
        "thrombolytic_window_class": "thrombolytic_window_class",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/code-strokes/<record_id>/imaging-complete", methods=["POST"])
def imaging_complete(record_id):
    authenticate(("EdPhysician",))
    record = load_path("cases", record_id)
    read_body(IMAGING_SPEC)
    if record["status"] not in ("ACTIVATED", "CONSULT_IN_PROGRESS"):
        fail("ERR_CASE_NOT_ACTIVE",
             "No imaging transition is declared from %s." % record["status"])
    center = db.get("centers", record["center_id"])
    if center is None or not center["ct_scanner_ready"]:
        fail("ERR_CENTER_EQUIPMENT_OFFLINE", "The facility's CT scanner is not ready.")
    record["imaging_at"] = db.now_raw()
    record["door_to_imaging_minutes"] = db.floor_minutes(
        db.parse_iso(record["door_at"]), db.now_dt())
    if record["status"] == "ACTIVATED":
        record["status"] = "IMAGING_COMPLETE"
    db.touch(record)
    if record["door_to_imaging_minutes"] > DTI_TARGET_MIN:
        derive.open_system_deviation(
            record, "DTI_EXCEEDED", "MINOR",
            "Door-to-imaging time of %d minutes exceeded the %d minute target."
            % (record["door_to_imaging_minutes"], DTI_TARGET_MIN))
    return resp.object_response(record)


@bp.route("/code-strokes/<record_id>/administer-thrombolytic", methods=["POST"])
def administer(record_id):
    authenticate(("EdPhysician",))
    record = load_path("cases", record_id)
    body = read_body(ADMINISTER_SPEC)
    if record["status"] != "ELIGIBILITY_DETERMINED":
        fail("ERR_CASE_NOT_ACTIVE",
             "No thrombolytic administration is declared from %s." % record["status"])
    checklist = reporting.checklist_for_case(record["id"])
    absolute_count = checklist["absolute_contraindication_count"] if checklist else 0
    if absolute_count > 0:
        fail("ERR_ABSOLUTE_CONTRAINDICATION",
             "The checklist documents %d absolute contraindication(s)." % absolute_count)
    if (checklist is None
            or checklist["determination_status"] not in
            ("ELIGIBLE", "ELIGIBLE_WITH_RELATIVE_OVERRIDE")
            or checklist["documentation_status"] != "DOCUMENTED"):
        fail("ERR_ELIGIBILITY_NOT_DETERMINED",
             "The case's checklist has not been determined eligible.")
    if record["imaging_at"] is None:
        fail("ERR_CASE_NOT_ACTIVE",
             "The case has no imaging_at; the patient has not been scanned.")
    # Rule 21: the window is re-derived against the clock as it now stands, and
    # the refusal still persists that fresh classification.
    record["thrombolytic_window_class"] = calc.window_class(record, db.now_dt())
    if record["thrombolytic_window_class"] == "OUT_OF_WINDOW":
        fail("ERR_THROMBOLYTIC_WINDOW_EXPIRED",
             "The thrombolytic window has expired against the current clock.")
    center = db.get("centers", record["center_id"])
    if center is None or center["equipment_readiness_posture"] == "OFFLINE":
        fail("ERR_CENTER_EQUIPMENT_OFFLINE",
             "The facility's equipment readiness posture is OFFLINE.")
    needle_raw = db.now_raw()
    record["needle_at"] = needle_raw
    record["thrombolytic_agent"] = body["thrombolytic_agent"]
    record["thrombolytic_dose_mg"] = db.q1(body["thrombolytic_dose_mg"])
    record["door_to_needle_minutes"] = db.floor_minutes(
        db.parse_iso(record["door_at"]), db.now_dt())
    if record["last_known_well_at"] is not None:
        record["lkw_to_needle_minutes"] = db.floor_minutes(
            db.parse_iso(record["last_known_well_at"]), db.now_dt())
    record["status"] = "THROMBOLYSIS_ADMINISTERED"
    record["disposition"] = "TREATED_LOCAL"
    db.touch(record)
    if record["door_to_needle_minutes"] > DTN_TARGET_MIN:
        derive.open_system_deviation(
            record, "DTN_EXCEEDED", "MAJOR",
            "Door-to-needle time of %d minutes exceeded the %d minute target."
            % (record["door_to_needle_minutes"], DTN_TARGET_MIN))
    return resp.object_response(record)


@bp.route("/code-strokes/<record_id>/close", methods=["POST"])
def close_case(record_id):
    authenticate(("EdPhysician", "QualityAbstractor"))
    record = load_path("cases", record_id)
    read_body([])
    if record["status"] == "THROMBOLYSIS_ADMINISTERED":
        disposition = "TREATED_LOCAL"
    elif record["status"] == "ELIGIBILITY_DETERMINED":
        checklist = reporting.checklist_for_case(record["id"])
        if checklist is None or checklist["determination_status"] != "INELIGIBLE":
            fail("ERR_CASE_NOT_ACTIVE",
                 "An eligible case is treated or transferred, never closed directly.")
        disposition = "NO_TREATMENT"
    else:
        fail("ERR_CASE_NOT_ACTIVE",
             "No close transition is declared from %s." % record["status"])
    for consult in reporting.consults_for_case(record["id"]):
        if consult["status"] in CONSULT_LIVE:
            fail("ERR_CASE_NOT_ACTIVE",
                 "A live telestroke consult holds the case open.")
    record["status"] = "CLOSED"
    record["disposition"] = disposition
    db.touch(record)
    center = db.get("centers", record["center_id"])
    if center is not None:
        derive.settle_center(center)
    return resp.object_response(record)


@bp.route("/code-strokes/<record_id>/abort", methods=["POST"])
def abort_case(record_id):
    authenticate(("EdPhysician",))
    record = load_path("cases", record_id)
    body = read_body(ABORT_SPEC)
    if record["status"] not in LIVE_NODES:
        fail("ERR_CASE_NOT_ACTIVE",
             "No abort transition is declared from %s." % record["status"])
    record["status"] = "ABORTED"
    record["disposition"] = "NO_TREATMENT"
    record["abort_reason"] = body["abort_reason"]
    db.touch(record)
    # Hop 1: cancel live consults (no CONSULT_UNFILLED deviation) and every
    # PROPOSED or ACCEPTED transfer. Hop 2 runs inside cancel_consult.
    for consult in reporting.consults_for_case(record["id"]):
        if consult["status"] in CONSULT_LIVE:
            derive.cancel_consult(consult, "case aborted", False)
    destinations = []
    for transfer in db.all_of("transfers"):
        if transfer["case_id"] != record["id"]:
            continue
        if transfer["status"] not in ("PROPOSED", "ACCEPTED"):
            continue
        gives_back = transfer["status"] == "ACCEPTED"
        transfer["status"] = "CANCELLED"
        transfer["cancellation_reason"] = "case aborted"
        db.touch(transfer)
        if gives_back:
            destination = db.get("centers", transfer["destination_center_id"])
            if destination is not None and destination not in destinations:
                destinations.append(destination)
    # Hop 3: every open_case_count decrement lands before any posture moves.
    origin = db.get("centers", record["center_id"])
    if origin is not None:
        derive.recompute_open_case_count(origin)
    for destination in destinations:
        derive.recompute_open_case_count(destination)
    # Hop 4: postures, origin first and then each affected destination.
    if origin is not None:
        derive.recompute_ems_posture(origin)
    for destination in destinations:
        derive.recompute_ems_posture(destination)
    return resp.object_response(record)

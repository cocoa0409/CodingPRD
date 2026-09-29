"""Densitometer registry, precision certification, phantom QC, cross-calibration."""
from decimal import Decimal
from flask import Blueprint, request

import calc
import cascades
import queries
import validate
from db import base_record, db, now_iso, public, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PROGRAM_ADMIN, QUALITY_REVIEWER,
                        SCHEDULER, TECHNOLOGIST, actor_id, endpoint)
from response import created, ok, paginated
from util import dec

bp = Blueprint("devices", __name__)

MANUFACTURERS = ("HOLOGIC", "GE_LUNAR", "NORLAND")
SCAN_MODES = ("ARRAY", "FAST_ARRAY", "HIGH_DEFINITION")
QC_PURPOSES = ("DAILY_QC", "CROSS_CAL_BASELINE", "CROSS_CAL_NEW")
CHANGE_TYPES = ("DETECTOR_REPLACEMENT", "SOFTWARE_UPGRADE",
                "XRAY_TUBE_REPLACEMENT", "DEVICE_REPLACEMENT")


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


@bp.post("/densitometers")
@endpoint(PROGRAM_ADMIN)
def create_densitometer():
    body = validate.body()
    serial_number = validate.string(body, "serial_number", min_len=1, max_len=32)
    manufacturer = validate.enum(body, "manufacturer", MANUFACTURERS)
    model = validate.string(body, "model", min_len=1, max_len=64)
    site_code = validate.string(body, "site_code", min_len=1, max_len=16)
    baseline_bmd = validate.number(body, "phantom_baseline_bmd_g_cm2", minimum=0,
                                   maximum=2, min_exclusive=True, max_places=4)
    baseline_sd = validate.number(body, "phantom_baseline_sd_g_cm2", minimum=0,
                                  maximum="0.2", min_exclusive=True, max_places=4)
    buffer_minutes = validate.integer(body, "appointment_buffer_minutes", required=False,
                                      default=15, minimum=0, maximum=120)
    capacity = validate.integer(body, "daily_scan_capacity", required=False,
                                default=12, minimum=1, maximum=60)

    for row in db.densitometers.values():
        if row["serial_number"] == serial_number:
            raise ApiError("ERR_SERIAL_NUMBER_TAKEN", "That serial_number is already registered.")

    record = base_record()
    record.update({
        "serial_number": serial_number,
        "manufacturer": manufacturer,
        "model": model,
        "site_code": site_code,
        "status": "ACTIVE",
        "phantom_baseline_bmd_g_cm2": baseline_bmd,
        "phantom_baseline_sd_g_cm2": baseline_sd,
        "appointment_buffer_minutes": buffer_minutes,
        "daily_scan_capacity": capacity,
        "last_qc_result": None,
        "last_qc_run_at": None,
        "consecutive_qc_pass_count": 0,
        "qc_hold_started_at": None,
        "qc_hold_reason_code": None,
        "rms_sd_g_cm2": None,
        "precision_degrees_of_freedom": None,
        "lsc_g_cm2": None,
        "precision_technologist_user_id": None,
        "precision_certified_at": None,
        "cross_cal_factor": Decimal("1.0"),
        "calibration_generation": 1,
    })
    db.densitometers[record["id"]] = record
    return created(public(record))


@bp.get("/densitometers/<densitometer_id>")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def get_densitometer(densitometer_id):
    return ok(public(queries.device(densitometer_id)))


@bp.get("/densitometers")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def list_densitometers():
    rows = _filtered(list(db.densitometers.values()),
                     {"status": "status", "site_code": "site_code"})
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return paginated(rows, public)


@bp.post("/densitometers/<densitometer_id>/precision-assessment")
@endpoint(PROGRAM_ADMIN)
def precision_assessment(densitometer_id):
    body = validate.body()
    expected_version = validate.integer(body, "expected_densitometer_version")
    technologist_user_id = validate.string(body, "technologist_user_id", min_len=1)
    patient_count = validate.integer(body, "patient_count", minimum=1)
    scans_per_patient = validate.integer(body, "scans_per_patient", minimum=1)
    rms_sd = validate.number(body, "rms_sd_g_cm2", minimum=0, min_exclusive=True)

    device = queries.device(densitometer_id)
    if expected_version != device["version"]:
        raise ApiError("ERR_STALE_DENSITOMETER_VERSION",
                       "expected_densitometer_version does not match the device's version.")
    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is retired.")

    degrees_of_freedom, lsc = calc.precision_lsc(patient_count, scans_per_patient, rms_sd)
    if lsc is None:
        raise ApiError("ERR_PRECISION_STUDY_UNDERPOWERED",
                       "The precision study carries too few degrees of freedom.")
    device["rms_sd_g_cm2"] = rms_sd
    device["precision_degrees_of_freedom"] = degrees_of_freedom
    device["lsc_g_cm2"] = lsc
    device["precision_technologist_user_id"] = technologist_user_id
    device["precision_certified_at"] = now_iso()
    touch(device)
    return ok(public(device))


@bp.post("/densitometers/<densitometer_id>/retire")
@endpoint(PROGRAM_ADMIN)
def retire_densitometer(densitometer_id):
    device = queries.device(densitometer_id)
    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is already retired.")
    cascades.retire_device(device)
    return ok(public(device))


def _apply_qc_effects(device, run):
    """PRD 3.3: the four device rules, first match wins."""
    entered_hold = False
    result = run["result"]
    if result == "FAIL" or run["shift_detected"]:
        reason = "OUT_OF_CONTROL_FAIL" if result == "FAIL" else "SUSTAINED_SHIFT"
        if device["status"] == "ACTIVE":
            device["status"] = "QC_HOLD"
            entered_hold = True
        if device["status"] == "QC_HOLD":
            device["qc_hold_reason_code"] = reason
            device["qc_hold_started_at"] = run["performed_at_utc"]
        device["consecutive_qc_pass_count"] = 0
    elif result == "WARN":
        device["consecutive_qc_pass_count"] = 0
    else:
        device["consecutive_qc_pass_count"] += 1
        if device["status"] == "QC_HOLD" and \
                device["consecutive_qc_pass_count"] >= calc.QC_RELEASE_PASS_STREAK:
            device["status"] = "ACTIVE"
            device["qc_hold_started_at"] = None
            device["qc_hold_reason_code"] = None
    return entered_hold


@bp.post("/densitometers/<densitometer_id>/qc-runs")
@endpoint(TECHNOLOGIST, PROGRAM_ADMIN)
def create_qc_run(densitometer_id):
    body = validate.body()
    purpose = validate.enum(body, "purpose", QC_PURPOSES)
    phantom_bmd = validate.number(body, "phantom_bmd_g_cm2", minimum=0, maximum=2,
                                  min_exclusive=True, max_places=4)
    scan_mode = validate.enum(body, "scan_mode", SCAN_MODES)
    event_id = validate.string(body, "calibration_event_id", required=False)
    if purpose == "DAILY_QC":
        if event_id is not None:
            validate.bad("calibration_event_id must be absent for a DAILY_QC run.")
    elif event_id is None:
        validate.bad("calibration_event_id is required for a cross-calibration run.")

    device = queries.device(densitometer_id)
    event = queries.fetch("calibration_events", event_id) if event_id is not None else None
    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is retired.")

    deviation, sd_units, result = calc.score_phantom_run(device, phantom_bmd)
    shift_detected = False
    if purpose == "DAILY_QC":
        preceding = queries.qc_runs_of_device(densitometer_id, "DAILY_QC")
        preceding.sort(key=lambda row: (row["performed_at_utc"], row["created_at"], row["_seq"]),
                       reverse=True)
        shift_detected = calc.detect_shift(sd_units, preceding)

    record = base_record(versioned=False)
    record.update({
        "densitometer_id": densitometer_id,
        "calibration_event_id": event_id,
        "purpose": purpose,
        "scan_mode": scan_mode,
        "phantom_bmd_g_cm2": phantom_bmd,
        "performed_by_user_id": actor_id(),
        "performed_at_utc": now_iso(),
        "deviation_g_cm2": deviation,
        "deviation_sd_units": sd_units,
        "result": result,
        "shift_detected": shift_detected,
    })
    db.qc_runs[record["id"]] = record

    if purpose == "DAILY_QC":
        entered_hold = _apply_qc_effects(device, record)
        device["last_qc_result"] = result
        device["last_qc_run_at"] = record["performed_at_utc"]
        touch(device)
        if entered_hold:
            cascades.cascade_b_qc_hold(device)
    elif event is not None:
        field = "baseline_run_count" if purpose == "CROSS_CAL_BASELINE" else "new_run_count"
        event[field] += 1
        touch(event)
    return created(public(record))


@bp.get("/qc-runs/<qc_run_id>")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER)
def get_qc_run(qc_run_id):
    return ok(public(queries.fetch("qc_runs", qc_run_id)))


@bp.get("/qc-runs")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER)
def list_qc_runs():
    rows = _filtered(list(db.qc_runs.values()), {
        "densitometer_id": "densitometer_id",
        "calibration_event_id": "calibration_event_id",
        "purpose": "purpose",
        "result": "result",
    })
    rows.sort(key=lambda row: (row["performed_at_utc"], row["created_at"], row["_seq"]),
              reverse=True)
    return paginated(rows, public)


@bp.post("/densitometers/<densitometer_id>/calibration-events")
@endpoint(PROGRAM_ADMIN)
def open_calibration_event(densitometer_id):
    body = validate.body()
    change_type = validate.enum(body, "change_type", CHANGE_TYPES)
    change_note = validate.string(body, "change_note", required=False, max_len=240)

    device = queries.device(densitometer_id)
    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is retired.")
    if device["status"] not in ("ACTIVE", "QC_HOLD"):
        raise ApiError("ERR_DENSITOMETER_NOT_ACTIVE",
                       "The densitometer is already awaiting cross-calibration.")
    if queries.events_of_device(densitometer_id, ("OPEN", "PHANTOM_SET_COMPLETE")):
        raise ApiError("ERR_DENSITOMETER_NOT_ACTIVE",
                       "A calibration event on this densitometer is still open.")

    record = base_record()
    record.update({
        "densitometer_id": densitometer_id,
        "change_type": change_type,
        "change_note": change_note,
        "status": "OPEN",
        "required_phantom_runs": calc.REQUIRED_PHANTOM_RUNS[change_type],
        "baseline_run_count": 0,
        "new_run_count": 0,
        "baseline_mean_bmd_g_cm2": None,
        "new_mean_bmd_g_cm2": None,
        "percent_difference": None,
        "proposed_cross_cal_factor": None,
        "outcome_code": None,
        "closed_at_utc": None,
        "adjudicated_at_utc": None,
    })
    db.calibration_events[record["id"]] = record
    device["status"] = "CROSS_CAL_PENDING"
    device["consecutive_qc_pass_count"] = 0
    touch(device)
    return created(public(record))


@bp.post("/calibration-events/<event_id>/close")
@endpoint(PROGRAM_ADMIN)
def close_calibration_event(event_id):
    event = queries.fetch("calibration_events", event_id)
    if event["status"] != "OPEN":
        raise ApiError("ERR_CALIBRATION_EVENT_NOT_OPEN", "The calibration event is not OPEN.")
    required = event["required_phantom_runs"]
    if event["baseline_run_count"] < required or event["new_run_count"] < required:
        raise ApiError("ERR_PHANTOM_SET_INCOMPLETE",
                       "Both phantom sets must hold the required number of runs.")
    baseline_values = [row["phantom_bmd_g_cm2"]
                       for row in queries.qc_runs_of_event(event_id, "CROSS_CAL_BASELINE")]
    new_values = [row["phantom_bmd_g_cm2"]
                  for row in queries.qc_runs_of_event(event_id, "CROSS_CAL_NEW")]
    baseline_mean, new_mean, percent, factor, outcome = calc.cross_calibration(
        baseline_values, new_values)
    event["status"] = "PHANTOM_SET_COMPLETE"
    event["closed_at_utc"] = now_iso()
    event["baseline_mean_bmd_g_cm2"] = baseline_mean
    event["new_mean_bmd_g_cm2"] = new_mean
    event["percent_difference"] = percent
    event["proposed_cross_cal_factor"] = factor
    event["outcome_code"] = outcome
    touch(event)
    return ok(public(event))


@bp.post("/calibration-events/<event_id>/adjudicate")
@endpoint(PROGRAM_ADMIN)
def adjudicate_calibration_event(event_id):
    event = queries.fetch("calibration_events", event_id)
    if event["status"] != "PHANTOM_SET_COMPLETE":
        raise ApiError("ERR_CALIBRATION_EVENT_NOT_CLOSED",
                       "The calibration event is not PHANTOM_SET_COMPLETE.")
    device = db.densitometers.get(event["densitometer_id"])
    if abs(dec(event["percent_difference"])) <= calc.CROSS_CAL_MAX_PCT:
        cascades.cascade_c_approve(event, device)
    else:
        event["status"] = "REJECTED"
        event["outcome_code"] = "REJECTED_EXCESSIVE_DRIFT"
        event["adjudicated_at_utc"] = now_iso()
        touch(event)
    return ok(public(event))


@bp.get("/calibration-events/<event_id>")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def get_calibration_event(event_id):
    return ok(public(queries.fetch("calibration_events", event_id)))


@bp.get("/densitometers/<densitometer_id>/calibration-events")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def list_calibration_events(densitometer_id):
    queries.device(densitometer_id)
    rows = _filtered(queries.events_of_device(densitometer_id), {"status": "status"})
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]), reverse=True)
    return paginated(rows, public)

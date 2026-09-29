"""Scan orders, payer frequency screening, and slot booking onto a device."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import cascades
import queries
import validate
from db import base_record, db, now, now_iso, public, today, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER, PROGRAM_ADMIN,
                        SCHEDULER, TECHNOLOGIST, actor_id, endpoint,
                        enforce_patient_scope, is_portal)
from response import created, ok, paginated
from util import fmt_date, fmt_instant, parse_instant

bp = Blueprint("scheduling", __name__)

INDICATIONS = ("BASELINE_SCREENING", "SERIAL_MONITORING",
               "TREATMENT_MONITORING", "HIGH_RISK_CASE_FINDING")
SITE_CODES = ("LUMBAR_SPINE", "FEMORAL_NECK", "TOTAL_HIP", "FOREARM_33")
SERIAL_INDICATIONS = ("SERIAL_MONITORING", "TREATMENT_MONITORING")
MAX_APPOINTMENT_MINUTES = 240


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


def _required_densitometer(patient, indication):
    """PRD 3.4: serial work is pinned to the instrument behind the baseline report."""
    if indication not in SERIAL_INDICATIONS:
        return None
    baseline_id = patient["baseline_report_id"]
    if baseline_id is None:
        return None
    report = db.diagnostic_reports.get(baseline_id)
    if report is None:
        return None
    session = db.scan_sessions.get(report["scan_session_id"])
    if session is None:
        return None
    return session["densitometer_id"]


@bp.post("/scan-orders")
@endpoint(SCHEDULER, INTERPRETING_PHYSICIAN)
def create_scan_order():
    body = validate.body()
    patient_id = validate.string(body, "patient_id")
    indication = validate.enum(body, "indication", INDICATIONS)
    requested_sites = validate.enum_array(body, "requested_sites", SITE_CODES)
    requested_scan_date = validate.date_field(body, "requested_scan_date")
    vfa_requested = validate.boolean(body, "vfa_requested", required=False, default=False)
    if requested_scan_date < today():
        validate.bad("requested_scan_date must not be in the past.")

    patient = queries.patient(patient_id)
    policy = queries.policy_of(patient)

    verdict, earliest = calc.frequency_eligibility(patient, policy, requested_scan_date)
    floor_months = calc.payer_floor_months(policy, indication)
    status = "REQUESTED"
    denial_reason_code = None
    if verdict == "INELIGIBLE_TOO_SOON":
        if not policy["appeal_allowed"]:
            raise ApiError("ERR_PAYER_FREQUENCY_LIMIT",
                           "The requested date falls inside the payer's minimum interval.",
                           402)
        status = "DENIED"
        denial_reason_code = "PAYER_FREQUENCY_LIMIT"
    elif verdict == "INELIGIBLE_LIFETIME_CAP":
        if not policy["appeal_allowed"]:
            raise ApiError("ERR_LIFETIME_SCAN_CAP_EXCEEDED",
                           "The patient has reached the policy's lifetime screening cap.",
                           402)
        status = "DENIED"
        denial_reason_code = "LIFETIME_CAP_EXCEEDED"

    record = base_record()
    record.update({
        "patient_id": patient_id,
        "indication": indication,
        "requested_sites": requested_sites,
        "requested_scan_date": fmt_date(requested_scan_date),
        "vfa_requested": vfa_requested,
        "ordered_by_user_id": actor_id(),
        "ordered_at_utc": now_iso(),
        "status": status,
        "required_densitometer_id": _required_densitometer(patient, indication),
        "frequency_eligibility": verdict,
        "earliest_allowed_date": earliest,
        "payer_floor_months": floor_months,
        "reschedule_required": False,
        "denial_reason_code": denial_reason_code,
    })
    db.scan_orders[record["id"]] = record
    return created(public(record))


@bp.get("/scan-orders/<scan_order_id>")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
          PATIENT_PORTAL_USER)
def get_scan_order(scan_order_id):
    record = queries.order(scan_order_id)
    if is_portal():
        enforce_patient_scope(record["patient_id"])
    return ok(public(record))


@bp.get("/scan-orders")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
          PATIENT_PORTAL_USER)
def list_scan_orders():
    if is_portal():
        wanted = request.args.get("patient_id")
        if wanted:
            enforce_patient_scope(wanted)
    rows = _filtered(list(db.scan_orders.values()), {
        "patient_id": "patient_id",
        "required_densitometer_id": "required_densitometer_id",
        "status": "status",
        "indication": "indication",
    })
    if is_portal():
        rows = [row for row in rows if row["patient_id"] == actor_id()]
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return paginated(rows, public)


def _patient_of_appointment(appointment):
    order = db.scan_orders.get(appointment["scan_order_id"])
    return None if order is None else order["patient_id"]


def _assign_slot_indexes(new_appointment):
    """Positional slot_index over the device's day; the new row is not re-touched."""
    target_date = cascades.slot_date(new_appointment)
    siblings = [
        row for row in queries.appointments_of_device(
            new_appointment["densitometer_id"], cascades.LIVE_SLOT_STATUSES)
        if cascades.slot_date(row) == target_date
    ]
    siblings.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    for index, row in enumerate(siblings, start=1):
        if row is new_appointment:
            row["slot_index"] = index
        elif row["slot_index"] != index:
            row["slot_index"] = index
            touch(row)


@bp.post("/scan-appointments")
@endpoint(SCHEDULER)
def create_scan_appointment():
    body = validate.body()
    scan_order_id = validate.string(body, "scan_order_id")
    densitometer_id = validate.string(body, "densitometer_id")
    start_utc = validate.instant_field(body, "start_utc")
    end_utc = validate.instant_field(body, "end_utc")
    if end_utc > start_utc:
        minutes = int((end_utc - start_utc).total_seconds() // 60)
        if (end_utc - start_utc).total_seconds() > MAX_APPOINTMENT_MINUTES * 60:
            validate.bad("The appointment window may not exceed %d minutes."
                         % MAX_APPOINTMENT_MINUTES)
    else:
        minutes = 0

    order = queries.order(scan_order_id)
    device = queries.device(densitometer_id)

    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is retired.")
    if order["status"] != "REQUESTED" or order["frequency_eligibility"] not in (
            "ELIGIBLE", "ELIGIBLE_WITH_GRACE"):
        raise ApiError("ERR_ORDER_NOT_SCHEDULABLE", "That order cannot be scheduled.")
    if order["required_densitometer_id"] is not None and \
            order["required_densitometer_id"] != densitometer_id:
        raise ApiError("ERR_SERIAL_DEVICE_MISMATCH",
                       "Serial work must be booked onto the baseline instrument.")
    if end_utc <= start_utc:
        raise ApiError("ERR_INVALID_INTERVAL", "end_utc must be strictly after start_utc.")
    if start_utc <= now():
        raise ApiError("ERR_APPOINTMENT_IN_PAST",
                       "start_utc must be after the current logical clock.")

    buffer_minutes = device["appointment_buffer_minutes"]
    buffer = timedelta(minutes=buffer_minutes)
    for row in queries.appointments_of_device(densitometer_id, ("BOOKED", "CHECKED_IN")):
        existing_start = parse_instant(row["start_utc"])
        existing_end = parse_instant(row["end_utc"])
        if start_utc < existing_end + buffer and existing_start < end_utc + buffer:
            raise ApiError("ERR_DEVICE_SLOT_CONFLICT",
                           "The window collides with an existing slot on this device.")

    target_date = start_utc.date()
    for row in db.scan_appointments.values():
        if row["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        if _patient_of_appointment(row) != order["patient_id"]:
            continue
        if cascades.slot_date(row) == target_date:
            raise ApiError("ERR_PATIENT_DOUBLE_BOOKED",
                           "The patient already holds a slot on that calendar date.")

    same_day = [
        row for row in queries.appointments_of_device(
            densitometer_id, cascades.LIVE_SLOT_STATUSES)
        if cascades.slot_date(row) == target_date
    ]
    if len(same_day) >= device["daily_scan_capacity"]:
        raise ApiError("ERR_DEVICE_DAILY_CAPACITY_FULL",
                       "The device has no remaining capacity on that date.")

    record = base_record()
    record.update({
        "scan_order_id": scan_order_id,
        "densitometer_id": densitometer_id,
        "start_utc": fmt_instant(start_utc),
        "end_utc": fmt_instant(end_utc),
        "scheduled_duration_minutes": minutes,
        "status": "BOOKED",
        "cancellation_reason_code": None,
        "slot_index": None,
        "cancelled_at_utc": None,
    })
    db.scan_appointments[record["id"]] = record
    _assign_slot_indexes(record)

    order["status"] = "SCHEDULED"
    order["reschedule_required"] = False
    touch(order)
    patient = db.patients.get(order["patient_id"])
    if patient is not None:
        patient["open_scheduled_order_count"] += 1
        touch(patient)
    return created(public(record))


@bp.post("/scan-appointments/<appointment_id>/cancel")
@endpoint(SCHEDULER)
def cancel_scan_appointment(appointment_id):
    appointment = queries.appointment(appointment_id)
    if appointment["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_BOOKED", "The appointment is not BOOKED.")
    target_date = cascades.slot_date(appointment)
    cascades.cancel_appointment(appointment, "PATIENT_REQUEST", False)
    cascades.recompute_slot_indexes(appointment["densitometer_id"], [target_date])
    return ok(public(appointment))


@bp.get("/scan-appointments/<appointment_id>")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, INTERPRETING_PHYSICIAN)
def get_scan_appointment(appointment_id):
    return ok(public(queries.appointment(appointment_id)))


@bp.get("/scan-appointments")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, INTERPRETING_PHYSICIAN)
def list_scan_appointments():
    rows = _filtered(list(db.scan_appointments.values()), {
        "scan_order_id": "scan_order_id",
        "densitometer_id": "densitometer_id",
        "status": "status",
    })
    from_utc = request.args.get("from_utc")
    to_utc = request.args.get("to_utc")
    for raw in (from_utc, to_utc):
        if raw not in (None, "") and parse_instant(raw) is None:
            validate.bad("Query instant windows must be valid ISO 8601 instants.")
    if from_utc:
        rows = [row for row in rows
                if parse_instant(row["start_utc"]) >= parse_instant(from_utc)]
    if to_utc:
        rows = [row for row in rows
                if parse_instant(row["start_utc"]) < parse_instant(to_utc)]
    rows.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    return paginated(rows, public)

"""Dose orders (PRD 3.3)."""
from flask import Blueprint, request

import db
from constants import MEDICATIONS
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_order, path_patient
from services import entity, patient_flow
from validation import bool_field, num_field, text_field

bp = Blueprint("dose_orders", __name__)

READ_ROLES = ["ProgramAdministrator", "Physician", "Nurse", "MedicalDirector", "RegulatoryAuditor"]


@bp.route("/otp/dose-orders", methods=["POST"])
def create_dose_order():
    context(["Physician"])
    body = request.get_json(silent=True) or {}
    patient_id = text_field(body, "patient_id")
    patient = path_patient(patient_id)
    medication = text_field(body, "medication")
    if medication not in MEDICATIONS:
        raise ApiError("ERR_INVALID_REQUEST", "medication must be METHADONE or BUPRENORPHINE")
    ordered = num_field(body, "ordered_daily_mg")
    if ordered < 0:
        raise ApiError("ERR_INVALID_REQUEST", "ordered_daily_mg must not be negative")
    program = db.programs.get(patient.get("program_id"))
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")
    if medication == "METHADONE":
        ceiling = program.get("max_daily_mg_methadone") or 0.0
    else:
        ceiling = program.get("max_daily_mg_buprenorphine") or 0.0
    if ordered > ceiling:
        raise ApiError(
            "ERR_DOSE_EXCEEDS_MEDICATION_CEILING",
            "ordered_daily_mg exceeds the program's medication ceiling",
        )
    # Priority 14 is enforced at creation as well as at activation. The titration
    # ceiling is read from the ordered milligrams in force immediately before this
    # order — the patient's previous order — so a patient's first order has no
    # prior figure and the incremental rule is vacuous for it.
    prior = latest_prior_order(patient_id, exclude=None)
    previous = prior.get("ordered_daily_mg") if prior else 0.0
    if prior is not None and ordered > previous + 10.0:
        raise ApiError(
            "ERR_DOSE_TITRATION_TOO_FAST",
            "ordered_daily_mg exceeds the previous ordered dose by more than 10.0 mg",
        )
    row = entity.make_dose_order(
        patient, medication, ordered, bool_field(body, "split_dose_authorized", False), ceiling
    )
    row["previous_ordered_daily_mg"] = previous
    row["_has_prior_order"] = prior is not None
    db.dose_orders[row["id"]] = row
    patient_flow.supersede_orders(patient, row["id"])
    return ok_object(entity.serialize_dose_order(row), 201)


def latest_prior_order(patient_id, exclude=None):
    rows = [
        r
        for r in db.dose_orders.values()
        if r.get("patient_id") == patient_id and (exclude is None or r["id"] != exclude)
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (str(r.get("created_at", "")), str(r.get("id", ""))))
    return rows[-1]


@bp.route("/otp/dose-orders", methods=["GET"])
def list_dose_orders():
    context(READ_ROLES)
    rows = list(db.dose_orders.values())
    for name in ("patient_id", "program_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_dose_order(r) for r in page], limit, offset, total)


@bp.route("/otp/dose-orders/<order_id>", methods=["GET"])
def read_dose_order(order_id):
    context(READ_ROLES)
    row = path_order(order_id)
    return ok_object(entity.serialize_dose_order(row))


@bp.route("/otp/dose-orders/<order_id>/activate", methods=["POST"])
def activate(order_id):
    actor = context(["Physician"])
    row = path_order(order_id)
    patient_flow.activate_dose_order(row, actor)
    return ok_object(entity.serialize_dose_order(row))


@bp.route("/otp/dose-orders/<order_id>/suspend", methods=["POST"])
def suspend(order_id):
    context(["Physician"])
    row = path_order(order_id)
    if row.get("status") != "ACTIVE":
        raise ApiError("ERR_DOSE_ORDER_NOT_ACTIVE", "DoseOrder is not ACTIVE")
    row["status"] = "SUSPENDED"
    for dose in db.dose_dispenses.values():
        if dose.get("dose_order_id") != row["id"]:
            continue
        if dose.get("status") == "SCHEDULED":
            dose["status"] = "CANCELLED"
            dose["completed_at"] = db.fmt_dt(db.clock_dt())
            db.stamp(dose)
    db.stamp(row)
    return ok_object(entity.serialize_dose_order(row))


@bp.route("/otp/dose-orders/<order_id>/discontinue", methods=["POST"])
def discontinue(order_id):
    context(["Physician"])
    row = path_order(order_id)
    if row.get("status") == "DISCONTINUED":
        raise ApiError("ERR_DOSE_ORDER_NOT_DISCONTINUABLE", "DoseOrder is already DISCONTINUED")
    if row.get("status") not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_DOSE_ORDER_NOT_DISCONTINUABLE", "DoseOrder is not discontinuable")
    row["status"] = "DISCONTINUED"
    for dose in db.dose_dispenses.values():
        if dose.get("dose_order_id") != row["id"]:
            continue
        if dose.get("status") == "SCHEDULED":
            dose["status"] = "CANCELLED"
            dose["completed_at"] = db.fmt_dt(db.clock_dt())
            db.stamp(dose)
    db.stamp(row)
    return ok_object(entity.serialize_dose_order(row))
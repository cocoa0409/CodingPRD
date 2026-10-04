"""Dose dispenses: scheduling, check-in, verification, dispensing and completion."""
from flask import Blueprint, request

import db
from constants import MEDICATIONS, SOURCES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_dose, path_lot, path_order, path_patient
from services import (
    carry,
    dose as dose_svc,
    entity,
    guest as guest_svc,
    inventory,
    privilege as privilege_svc,
    program as program_svc,
)
from validation import bool_field, date_field, datetime_field, text_field

bp = Blueprint("dose_dispenses", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "Counselor",
    "MedicalDirector",
    "RegulatoryAuditor",
]

FILTERS = (
    "dose_order_id",
    "patient_id",
    "program_id",
    "privilege_id",
    "guest_arrangement_id",
    "inventory_lot_id",
    "source_type",
    "status",
    "dose_date",
)


@bp.route("/otp/dose-dispenses", methods=["POST"])
def schedule_dose():
    context(["Nurse", "ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    order_id = text_field(body, "dose_order_id")
    order = path_order(order_id)
    patient = path_patient(order["patient_id"])
    dose_date = date_field(body, "dose_date")
    scheduled_datetime = datetime_field(body, "scheduled_datetime")
    source_type = text_field(body, "source_type", "OBSERVED_CLINIC")
    if source_type not in SOURCES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "source_type must be one of %s" % ", ".join(SOURCES),
        )

    inventory_lot_id = body.get("inventory_lot_id")
    if inventory_lot_id:
        path_lot(inventory_lot_id)
    guest_arrangement_id = body.get("guest_arrangement_id")
    privilege_id = body.get("privilege_id")

    # The payload's guest/privilege fields must match the declared source type.
    if source_type == "GUEST_OBSERVED":
        if not guest_arrangement_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "guest_arrangement_id is required when source_type is GUEST_OBSERVED",
            )
        if privilege_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "privilege_id must be absent unless source_type is TAKE_HOME_ISSUANCE",
            )
    elif source_type == "TAKE_HOME_ISSUANCE":
        if not privilege_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "privilege_id is required when source_type is TAKE_HOME_ISSUANCE",
            )
        if guest_arrangement_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "guest_arrangement_id must be absent unless source_type is GUEST_OBSERVED",
            )
    else:
        if guest_arrangement_id or privilege_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "guest_arrangement_id and privilege_id are only valid for the matching source type",
            )

    program = db.programs.get(order.get("program_id"))
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")

    # Priority 8: scheduling is blocked while the clinic is FROZEN.
    program_svc.ensure_not_frozen(program)
    # Priority 10: diversion control.
    if patient.get("diversion_standing") == "CONFIRMED_DIVERSION":
        raise ApiError(
            "ERR_DIVERSIONS_OR_FINDINGS_OPEN",
            "A patient under confirmed diversion may not be scheduled a dose",
        )
    # Priority 13: the clinic-day rules.
    dose_svc.check_clinic_day(program, dose_date, scheduled_datetime, patient["id"])
    # Priority 23: the guest token.
    if source_type == "GUEST_OBSERVED":
        arrangement = db.guest_dosing_arrangements.get(guest_arrangement_id)
        if arrangement is None:
            raise ApiError(
                "ERR_ARRANGEMENT_NOT_FOUND", "No GuestDosingArrangement with the supplied id"
            )
        guest_svc.redeem_token(arrangement, arrangement.get("dose_authorization_token"))

    if source_type == "TAKE_HOME_ISSUANCE":
        privilege = privilege_svc.privilege_of(privilege_id)
        # A take-home dose may only be issued under a granted privilege, and it
        # draws from the lot its privilege's issued doses are committed to.
        if privilege.get("decision") not in ("APPROVED", "APPROVED_WITH_EXCEPTION"):
            raise ApiError(
                "ERR_PRIVILEGE_NOT_ACTIVE",
                "The referenced privilege is not APPROVED or APPROVED_WITH_EXCEPTION",
            )
        if not inventory_lot_id:
            committed = _committed_lot_for_privilege(privilege_id)
            if committed is not None:
                row_lot = committed
            else:
                row_lot = inventory.select_lot_for_privilege(privilege, patient)
            inventory_lot_id = row_lot
        row = entity.make_dose_dispense(
            order,
            patient,
            dose_date,
            scheduled_datetime,
            source_type=source_type,
            inventory_lot_id=inventory_lot_id,
            guest_arrangement_id=guest_arrangement_id,
            privilege_id=privilege_id,
        )
        ledger = carry.ensure_ledger_for_patient(patient)
        row["carries_before"] = ledger.get("carries_used") or 0
        row["carries_after"] = row["carries_before"] + row["carry_count"]
        db.dose_dispenses[row["id"]] = row
        return ok_object(entity.serialize_dose_dispense(row), 201)

    row = entity.make_dose_dispense(
        order,
        patient,
        dose_date,
        scheduled_datetime,
        source_type=source_type,
        inventory_lot_id=inventory_lot_id,
        guest_arrangement_id=guest_arrangement_id,
        privilege_id=privilege_id,
    )
    db.dose_dispenses[row["id"]] = row
    return ok_object(entity.serialize_dose_dispense(row), 201)


def _committed_lot_for_privilege(privilege_id):
    """The lot already committed to this privilege's take-home doses, if any."""
    for row in db.dose_dispenses.values():
        if row.get("privilege_id") == privilege_id and row.get("inventory_lot_id"):
            return row["inventory_lot_id"]
    return None


@bp.route("/otp/dose-dispenses", methods=["GET"])
def list_doses():
    context(READ_ROLES)
    rows = list(db.dose_dispenses.values())
    for name in FILTERS:
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if str(r.get(name)) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_dose_dispense(r) for r in page], limit, offset, total)


@bp.route("/otp/dose-dispenses/<dose_id>", methods=["GET"])
def read_dose(dose_id):
    context(READ_ROLES)
    row = path_dose(dose_id)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/check-in", methods=["POST"])
def check_in(dose_id):
    actor = context(["Nurse"])
    row = path_dose(dose_id)
    dose_svc.check_in(row, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/verify", methods=["POST"])
def verify(dose_id):
    actor = context(["Nurse"])
    row = path_dose(dose_id)
    body = request.get_json(silent=True) or {}
    identity_matched = bool_field(body, "identity_matched", True)
    dose_svc.verify(row, identity_matched, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/dispense", methods=["POST"])
def dispense(dose_id):
    actor = context(["Nurse"])
    row = path_dose(dose_id)
    body = request.get_json(silent=True) or {}
    dose_svc.dispense(row, body, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/complete", methods=["POST"])
def complete(dose_id):
    actor = context(["Nurse"])
    row = path_dose(dose_id)
    body = request.get_json(silent=True) or {}
    dose_svc.complete(row, body, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/refuse", methods=["POST"])
def refuse(dose_id):
    actor = context(["Nurse"])
    row = path_dose(dose_id)
    dose_svc.refuse(row, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/cancel", methods=["POST"])
def cancel(dose_id):
    actor = context(["Nurse", "Physician"])
    row = path_dose(dose_id)
    dose_svc.cancel(row, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/reschedule", methods=["POST"])
def reschedule(dose_id):
    actor = context(["Nurse", "ProgramAdministrator"])
    row = path_dose(dose_id)
    body = request.get_json(silent=True) or {}
    dose_svc.reschedule(row, body, actor)
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/mark-missed", methods=["POST"])
def mark_missed(dose_id):
    context(["Nurse", "Physician"])
    row = path_dose(dose_id)
    if row.get("status") != "SCHEDULED":
        raise ApiError("ERR_DOSE_NOT_SCHEDULED", "DoseDispense is not SCHEDULED")
    dose_svc.apply_miss(row, db.clock_dt())
    return ok_object(entity.serialize_dose_dispense(row))


@bp.route("/otp/dose-dispenses/<dose_id>/charge-preview", methods=["GET"])
def charge_preview(dose_id):
    context(["ProgramAdministrator", "RegulatoryAuditor"])
    row = path_dose(dose_id)
    order = db.dose_orders.get(row.get("dose_order_id"))
    program = db.programs.get(row.get("program_id"))
    patient = db.patients.get(row.get("patient_id"))
    if order is None or program is None:
        raise ApiError("ERR_DOSE_ORDER_NOT_FOUND", "No DoseOrder with the supplied id")
    per_component, sum_then_round = inventory.dose_tariff_both(row, order, program, patient)
    return ok_object(
        {
            "total_charge_per_component_rounded": per_component,
            "total_charge_sum_then_round": sum_then_round,
            "per_component_delta": round(per_component - sum_then_round, 2),
        }
    )
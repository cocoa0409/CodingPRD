"""Inventory lots, movements and period reconciliation."""
from flask import Blueprint, request

import db
from constants import MEDICATIONS, TRANSACTION_TYPES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_lot, path_patient, path_program, path_transaction
from services import entity, inventory, program as program_svc
from validation import bool_field, date_field, num_field, text_field

bp = Blueprint("inventory", __name__)

READ_ROLES = ["ProgramAdministrator", "Physician", "Nurse", "MedicalDirector", "RegulatoryAuditor"]
TX_ROLES = ["ProgramAdministrator", "Nurse", "RegulatoryAuditor"]


@bp.route("/otp/inventory-lots", methods=["POST"])
def create_lot():
    context(["ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    path_program(program_id)
    medication = text_field(body, "medication")
    if medication not in MEDICATIONS:
        raise ApiError("ERR_INVALID_REQUEST", "medication must be METHADONE or BUPRENORPHINE")
    lot_number = text_field(body, "lot_number")
    for existing in db.inventory_lots.values():
        if (
            existing.get("program_id") == program_id
            and existing.get("medication") == medication
            and existing.get("lot_number") == lot_number
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "lot_number must be unique within its program and medication",
            )
    quantity = num_field(body, "quantity_received_mg")
    if quantity < 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity_received_mg must not be negative")
    potency = num_field(body, "dose_potency_mg_per_unit", 1.0)
    row = entity.make_lot(
        {
            "program_id": program_id,
            "medication": medication,
            "lot_number": lot_number,
            "expiration_date": date_field(body, "expiration_date"),
            "quantity_received_mg": quantity,
            "dose_potency_mg_per_unit": potency,
            "reusable_for_take_home": bool_field(body, "reusable_for_take_home", False),
        }
    )
    db.inventory_lots[row["id"]] = row
    program_svc.refresh_program_by_id(program_id, bump=False)
    return ok_object(entity.serialize_lot(row), 201)


@bp.route("/otp/inventory-lots", methods=["GET"])
def list_lots():
    context(READ_ROLES)
    rows = list(db.inventory_lots.values())
    for name in ("program_id", "medication", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_lot(r) for r in page], limit, offset, total)


@bp.route("/otp/inventory-lots/<lot_id>", methods=["GET"])
def read_lot(lot_id):
    context(READ_ROLES)
    row = path_lot(lot_id)
    return ok_object(entity.serialize_lot(row))


@bp.route("/otp/inventory-lots/<lot_id>/quarantine", methods=["POST"])
def quarantine(lot_id):
    context(["ProgramAdministrator", "RegulatoryAuditor"])
    row = path_lot(lot_id)
    if row.get("status") not in ("RECEIVED", "IN_USE"):
        raise ApiError("ERR_LOT_NOT_QUARANTINABLE", "InventoryLot is not RECEIVED or IN_USE")
    row["status"] = "QUARANTINED"
    db.stamp(row)
    return ok_object(entity.serialize_lot(row))


@bp.route("/otp/inventory-lots/<lot_id>/release-quarantine", methods=["POST"])
def release_quarantine(lot_id):
    context(["ProgramAdministrator"])
    row = path_lot(lot_id)
    if row.get("status") != "QUARANTINED":
        raise ApiError("ERR_LOT_NOT_QUARANTINED", "InventoryLot is not QUARANTINED")
    # Releasing returns the lot to RECEIVED; it must re-enter use through the
    # ordinary first-transaction path.
    row["status"] = "RECEIVED"
    db.stamp(row)
    inventory.recompute_lot(row, bump=True)
    return ok_object(entity.serialize_lot(row))


@bp.route("/otp/inventory-lots/<lot_id>/destroy", methods=["POST"])
def destroy(lot_id):
    actor = context(["ProgramAdministrator"])
    row = path_lot(lot_id)
    body = request.get_json(silent=True) or {}
    witness = body.get("witness_staff_id")
    # Priority 7 then 17 then the emptiness check.
    if row.get("status") not in ("RECEIVED", "IN_USE", "DEPLETED"):
        raise ApiError("ERR_LOT_NOT_EMPTY", "InventoryLot cannot be destroyed in its status")
    if not witness or str(witness) == str(actor.user_id):
        raise ApiError(
            "ERR_WITNESS_REQUIRED",
            "A destruction requires a witness distinct from the acting staff member",
        )
    if inventory.eff(row.get("running_on_hand_mg")) != 0.0:
        raise ApiError("ERR_LOT_NOT_EMPTY", "InventoryLot still holds milligrams")
    inventory.append_transaction(row, "DESTRUCTION", 0, witness_staff_id=witness)
    row["status"] = "DESTROYED"
    db.stamp(row)
    return ok_object(entity.serialize_lot(row))


# ---------------------------------------------------------------------------
# Inventory transactions
# ---------------------------------------------------------------------------
@bp.route("/otp/inventory-transactions", methods=["POST"])
def create_transaction():
    actor = context(["ProgramAdministrator", "Nurse"])
    body = request.get_json(silent=True) or {}
    lot_id = text_field(body, "lot_id")
    lot = path_lot(lot_id)
    transaction_type = text_field(body, "transaction_type")
    if transaction_type not in TRANSACTION_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "transaction_type must be one of %s" % ", ".join(TRANSACTION_TYPES),
        )
    quantity = num_field(body, "quantity_mg")
    patient_id = body.get("patient_id")
    if patient_id:
        path_patient(patient_id)
    dose_dispense_id = body.get("dose_dispense_id")
    if dose_dispense_id and dose_dispense_id not in db.dose_dispenses:
        raise ApiError("ERR_DOSE_NOT_FOUND", "No DoseDispense with the supplied id")
    witness = body.get("witness_staff_id")

    # Sign convention is part of the contract.
    if transaction_type in ("RECEIPT", "RETURN") and quantity < 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity_mg must be positive for %s" % transaction_type)
    if transaction_type in ("DISPENSE", "WASTE", "DESTRUCTION") and quantity > 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity_mg must be negative for %s" % transaction_type)

    # Priority 17: waste and destruction require a distinct witness.
    if transaction_type in ("WASTE", "DESTRUCTION"):
        if not witness or str(witness) == str(actor.user_id):
            raise ApiError(
                "ERR_WITNESS_REQUIRED",
                "A wasted or destroyed milligram requires a distinct witness",
            )
    # Priority 21: the ceiling against the lot's running on-hand.
    if quantity < 0:
        if inventory.eff(lot.get("running_on_hand_mg")) < abs(quantity):
            raise ApiError(
                "ERR_INVENTORY_CEILING_EXCEEDED",
                "The requested milligrams exceed the lot's running_on_hand_mg",
            )
    # Priority 22: lot usability.
    if lot.get("status") == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "The lot is QUARANTINED")
    if transaction_type == "DISPENSE":
        if inventory.lot_is_expired(lot):
            raise ApiError("ERR_LOT_EXPIRED", "The lot is expired")

    row = inventory.append_transaction(
        lot,
        transaction_type,
        quantity,
        patient_id=patient_id,
        dose_dispense_id=dose_dispense_id,
        witness_staff_id=witness,
    )
    program_svc.refresh_program_by_id(lot.get("program_id"), bump=False)
    return ok_object(entity.serialize_transaction(row), 201)


@bp.route("/otp/inventory-transactions", methods=["GET"])
def list_transactions():
    context(READ_ROLES)
    rows = list(db.inventory_transactions.values())
    for name in (
        "lot_id",
        "program_id",
        "patient_id",
        "dose_dispense_id",
        "transaction_type",
        "reconciliation_period",
        "status",
    ):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged(
        [entity.serialize_transaction(r) for r in page], limit, offset, total
    )


@bp.route("/otp/inventory-transactions/<transaction_id>", methods=["GET"])
def read_transaction(transaction_id):
    context(TX_ROLES)
    row = path_transaction(transaction_id)
    return ok_object(entity.serialize_transaction(row))


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
@bp.route("/otp/inventory-reconciliations/<period>/close", methods=["POST"])
def close_period(period):
    context(["ProgramAdministrator", "RegulatoryAuditor"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    program = path_program(program_id)
    figures = inventory.reconciliation_figures(program, period, variant="delivered")

    period_dispensed = figures["period_dispensed_mg"]
    tolerance = max(50.0, 0.02 * period_dispensed)
    variance = figures["program_variance_mg"]
    flagged = abs(variance) > tolerance

    # Every transaction belonging to the closed period becomes RECONCILED.
    start_text = str(period)
    for row in db.inventory_transactions.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("reconciliation_period") == start_text:
            row["status"] = "RECONCILED"
            db.stamp(row)

    cumulative = program.get("cumulative_write_off_mg") or 0.0
    write_off = max(0.0, -variance - cumulative)
    if flagged:
        adjustment_lot = _program_adjustment_lot(program)
        if adjustment_lot is not None:
            adjustment = entity.make_transaction(
                adjustment_lot, "ADJUSTMENT", 0.0, status="FLAGGED"
            )
            adjustment["residual_variance_mg"] = round(variance, 2)
            adjustment["cumulative_write_off_mg"] = round(cumulative + write_off, 2)
            db.inventory_transactions[adjustment["id"]] = adjustment
            inventory.recompute_lot(adjustment_lot, bump=True)
            for row in db.inventory_transactions.values():
                if row.get("program_id") == program["id"] and row.get(
                    "transaction_type"
                ) == "ADJUSTMENT":
                    row["cumulative_write_off_mg"] = round(cumulative + write_off, 2)

    program["latest_inventory_variance_mg"] = round(variance, 2)
    program["cumulative_write_off_mg"] = round(cumulative + write_off, 2)
    if program["cumulative_write_off_mg"] < 0.0:
        program["cumulative_write_off_mg"] = 0.0

    # The write-off is applied to the variance, leaving no residual.
    if write_off > 0:
        program["latest_inventory_variance_mg"] = 0.0

    program_svc.refresh_program(program, bump=True)
    return ok_object(
        {
            "period": period,
            "reconciled_on_hand_mg": figures["reconciled_on_hand_mg"],
            "delivered_on_hand_mg": figures["delivered_on_hand_mg"],
            "program_variance_mg": variance,
            "tolerance_mg": round(tolerance, 2),
            "flagged": flagged,
            "write_off_mg": round(write_off, 2),
        }
    )


def _program_adjustment_lot(program):
    lots = sorted(
        [lot for lot in db.inventory_lots.values() if lot.get("program_id") == program["id"]],
        key=lambda lot: (str(lot.get("created_at", "")), str(lot.get("id", ""))),
    )
    return lots[0] if lots else None


@bp.route("/otp/inventory-reconciliations", methods=["GET"])
def reconciliation_worksheet():
    context(["ProgramAdministrator", "RegulatoryAuditor"])
    program_id = request.args.get("program_id")
    period = request.args.get("period")
    if not program_id or not period:
        raise ApiError("ERR_INVALID_REQUEST", "program_id and period are required")
    program = path_program(program_id)
    # The worksheet reports the expired-retained variant: expired stock is not
    # netted out, so delivered equals reconciled and the variance omits that term.
    figures = inventory.reconciliation_figures(program, period, variant="retained")
    return ok_object(
        {
            "period": figures["period"],
            "reconciled_on_hand_mg": figures["reconciled_on_hand_mg"],
            "delivered_on_hand_mg": figures["delivered_on_hand_mg"],
            "program_variance_mg": figures["program_variance_mg"],
        }
    )
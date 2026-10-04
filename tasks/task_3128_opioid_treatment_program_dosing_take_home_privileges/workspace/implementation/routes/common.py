"""Shared route helpers: identity resolution and common lookups."""
import db
from errors import ApiError
from middleware import acting_actor, require_role

ALL_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "Counselor",
    "MedicalDirector",
    "RegulatoryAuditor",
]


def context(allowed):
    """Priority 1 then priority 2: authenticate, then authorise."""
    actor = acting_actor()
    require_role(actor, allowed)
    return actor


def path_program(program_id):
    row = db.programs.get(program_id)
    if row is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")
    return row


def path_patient(patient_id):
    row = db.patients.get(patient_id)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "No Patient with the supplied id")
    return row


def path_user(user_id):
    row = db.users.get(user_id)
    if row is None:
        raise ApiError("ERR_USER_NOT_FOUND", "No User with the supplied id")
    return row


def path_order(order_id):
    row = db.dose_orders.get(order_id)
    if row is None:
        raise ApiError("ERR_DOSE_ORDER_NOT_FOUND", "No DoseOrder with the supplied id")
    return row


def path_dose(dose_id):
    row = db.dose_dispenses.get(dose_id)
    if row is None:
        raise ApiError("ERR_DOSE_NOT_FOUND", "No DoseDispense with the supplied id")
    return row


def path_lot(lot_id):
    row = db.inventory_lots.get(lot_id)
    if row is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "No InventoryLot with the supplied id")
    return row


def path_transaction(transaction_id):
    row = db.inventory_transactions.get(transaction_id)
    if row is None:
        raise ApiError("ERR_TRANSACTION_NOT_FOUND", "No InventoryTransaction with the supplied id")
    return row


def path_ledger(ledger_id):
    row = db.take_home_carry_ledgers.get(ledger_id)
    if row is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", "No TakeHomeCarryLedger with the supplied id")
    return row


def require_patient_version(patient, expected):
    """Priority 6: optimistic concurrency on the patient's current version."""
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_patient_version is required")
    if int(expected) != int(patient.get("version") or 0):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_patient_version does not equal the patient's current version",
        )


def require_privilege_version(privilege, expected):
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_privilege_version is required")
    if int(expected) != int(privilege.get("version") or 0):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_privilege_version does not match the privilege's current version",
        )


def filters(args, names):
    out = {}
    for name in names:
        value = args.get(name)
        if value is not None and str(value).strip() != "":
            out[name] = str(value)
    return out



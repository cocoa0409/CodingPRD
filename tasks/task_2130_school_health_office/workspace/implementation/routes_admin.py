"""Administration records: reservation, outcome and the compensating void."""
from flask import Blueprint, request

import calc
import cascades
import serializers as ser
from auth import (ALL_READ_ROLES, authorize, insert, must_exist, nurse_owns,
                  resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import db, floor_minutes, minutes, new_record, sorted_rows, touch
from validators import Field, get_body, supplied, validate

bp = Blueprint("administration", __name__)

MEDICATIONS = {"EPINEPHRINE", "ALBUTEROL", "INSULIN", "METHYLPHENIDATE", "ACETAMINOPHEN"}
CLINICAL_ROLES = ["SchoolNurse", "HealthAide"]


def _credential_allows(nurse, is_controlled):
    if nurse is None:
        return False
    if nurse.get("credential") == "RN":
        return True
    return bool(nurse.get("delegation_authorized")) and not is_controlled


def _choose_lot(school_id, code, units, stock_flag):
    """Ladder positions 48 then 49."""
    lot = calc.select_lot(school_id, code, units, stock_flag)
    if lot is not None:
        return lot
    fallback = calc.select_lot(school_id, code, 0, stock_flag)
    if fallback is None:
        fail("ERR_NO_ELIGIBLE_LOT", "No eligible lot is available for this medication.")
    fail("ERR_INSUFFICIENT_STOCK", "The eligible lot holds fewer units than requested.")


def _reserve(lot, units):
    lot["quantity_on_hand"] -= units
    lot["quantity_reserved"] += units
    touch(lot)


# ---------------------------------------------------------------------------
# Order-backed reservation
# ---------------------------------------------------------------------------

@bp.post("/health-office/administration-records")
def create_record():
    user_id, role = authorize(CLINICAL_ROLES)
    body = get_body(request)
    visit = resolve("health_visits", body.get("visit_id"), "HealthVisit")
    auth = resolve("medication_authorizations", body.get("authorization_id"),
                   "MedicationAuthorization")
    witness = resolve("nurses", body.get("witness_nurse_id"), "Nurse")
    actor = must_exist("nurses", user_id, "Nurse")
    values = validate(body, [
        Field("visit_id", "string"),
        Field("authorization_id", "string"),
        Field("units", "integer", minimum=1, maximum=10),
        Field("expected_authorization_version", "integer"),
        Field("witness_nurse_id", "string", required=False),
    ])
    units = values["units"]

    # 9 - encounter from-state
    if visit["status"] not in ("IN_ASSESSMENT", "DISPOSITIONED"):
        fail("ERR_VISIT_INVALID_STATE",
             "A dose may only be prepared for an encounter in assessment or dispositioned.")
    # 15 - optimistic concurrency on the order version
    if values["expected_authorization_version"] != auth["version"]:
        fail("ERR_STALE_AUTHORIZATION_VERSION", "expected_authorization_version is stale.")
    controlled = bool(auth.get("is_controlled"))
    # 20 - credential and delegation
    if not _credential_allows(actor, controlled):
        fail("ERR_CREDENTIAL_NOT_DELEGATED",
             "This operator may not administer this medication.")
    # 21 - witness presence
    if controlled and witness is None:
        fail("ERR_WITNESS_REQUIRED", "A controlled dose requires a witness.")
    # 22 - segregation of duties
    if controlled and witness is not None and witness["id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The witness must differ from the administering nurse.")
    # 23 / 24 - consent then clinical status
    if auth["consent_status"] != "CONSENT_GRANTED":
        fail("ERR_CONSENT_NOT_GRANTED", "Guardian consent has not been granted.")
    if auth["clinical_status"] != "VERIFIED":
        fail("ERR_AUTHORIZATION_NOT_VERIFIED", "The order is not clinically verified.")
    # 31 - validity window
    clock = db.now()
    if not (auth["valid_from"] <= clock < auth["valid_until"]):
        fail("ERR_AUTHORIZATION_WINDOW_CLOSED", "The order is outside its validity window.")
    # 32 - PRN interval, then 35 - daily cap
    last = calc.last_administered_at(auth)
    if auth["schedule_type"] == "PRN" and last is not None:
        elapsed = floor_minutes(clock - last)
        if elapsed < auth["prn_min_interval_minutes"]:
            fail("ERR_PRN_INTERVAL_NOT_ELAPSED",
                 "The PRN interval has not fully elapsed.")
    if calc.doses_administered_today(auth) >= auth["max_doses_per_day"]:
        fail("ERR_DAILY_DOSE_CAP_REACHED", "The daily dose cap has been reached.")
    # 42 - the order must belong to the encounter's student
    if auth["student_id"] != visit["student_id"]:
        fail("ERR_LOT_MEDICATION_MISMATCH",
             "The order does not belong to the encounter's student.")
    # 48 / 49 - lot selection
    lot = _choose_lot(visit["school_id"], auth["medication_code"], units, False)

    record = new_record({
        "visit_id": visit["id"],
        "authorization_id": auth["id"],
        "lot_id": lot["id"],
        "administering_nurse_id": user_id,
        "witness_nurse_id": witness["id"] if witness else None,
        "medication_code": auth["medication_code"],
        "units": units,
        "dose_amount": auth["dose_amount"],
        "protocol_mode": "AUTHORIZED",
        "reason_code": None,
        "prepared_at": clock,
        "administered_at": None,
        "voided_at": None,
        "status": "PREPARED",
    })
    insert("administration_records", record)
    _reserve(lot, units)
    touch(auth)
    return created(ser.record_json(record))


# ---------------------------------------------------------------------------
# Emergency stock reservation
# ---------------------------------------------------------------------------

@bp.post("/health-office/administration-records/stock-emergency")
def create_stock_record():
    user_id, role = authorize(CLINICAL_ROLES)
    body = get_body(request)
    visit = resolve("health_visits", body.get("visit_id"), "HealthVisit")
    witness = resolve("nurses", body.get("witness_nurse_id"), "Nurse")
    actor = must_exist("nurses", user_id, "Nurse")
    values = validate(body, [
        Field("visit_id", "string"),
        Field("medication_code", "enum", enum=MEDICATIONS),
        Field("units", "integer", minimum=1, maximum=10),
        Field("witness_nurse_id", "string", required=False),
    ])
    code = values["medication_code"]
    units = values["units"]
    if visit["status"] not in ("IN_ASSESSMENT", "DISPOSITIONED"):
        fail("ERR_VISIT_INVALID_STATE",
             "A dose may only be prepared for an encounter in assessment or dispositioned.")
    controlled = code == "METHYLPHENIDATE"
    if not _credential_allows(actor, controlled):
        fail("ERR_CREDENTIAL_NOT_DELEGATED",
             "This operator may not administer this medication.")
    school = db.schools.get(visit["school_id"])
    if school is None or not school.get("emergency_protocol_enabled") \
            or code not in ("EPINEPHRINE", "ALBUTEROL"):
        fail("ERR_STOCK_PROTOCOL_DISABLED",
             "Undesignated stock administration is not available here.")
    lot = _choose_lot(visit["school_id"], code, units, True)
    clock = db.now()
    record = new_record({
        "visit_id": visit["id"],
        "authorization_id": None,
        "lot_id": lot["id"],
        "administering_nurse_id": user_id,
        "witness_nurse_id": witness["id"] if witness else None,
        "medication_code": code,
        "units": units,
        "dose_amount": calc.STOCK_PROTOCOL_DOSE[code],
        "protocol_mode": "STOCK_EMERGENCY",
        "reason_code": None,
        "prepared_at": clock,
        "administered_at": None,
        "voided_at": None,
        "status": "PREPARED",
    })
    insert("administration_records", record)
    _reserve(lot, units)
    return created(ser.record_json(record))


@bp.get("/health-office/administration-records/<record_id>")
def get_record(record_id):
    authorize(ALL_READ_ROLES)
    record = must_exist("administration_records", record_id, "AdministrationRecord")
    return ok(ser.record_json(record))


@bp.get("/health-office/administration-records")
def list_records():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("administration_records")
    for key in ("visit_id", "authorization_id", "lot_id", "administering_nurse_id",
                "witness_nurse_id", "status", "protocol_mode"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.record_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/administration-records/<record_id>/outcome")
def record_outcome(record_id):
    user_id, role = authorize(CLINICAL_ROLES)
    record = db.administration_records.get(record_id)
    nurse_owns(record, user_id, role, "administering_nurse_id")
    record = must_exist("administration_records", record_id, "AdministrationRecord")
    body = get_body(request)
    witness = resolve("nurses", body.get("witness_nurse_id"), "Nurse")
    actor = must_exist("nurses", user_id, "Nurse")
    values = validate(body, [
        Field("outcome", "enum", enum={"ADMINISTERED", "REFUSED", "WASTED"}),
        Field("reason_code", "string", required=False),
        Field("witness_nurse_id", "string", required=False),
    ])
    outcome = values["outcome"]
    if record["status"] != "PREPARED":
        fail("ERR_ADMINISTRATION_INVALID_STATE",
             "Only a PREPARED record may take an outcome.")
    controlled = record["medication_code"] == "METHYLPHENIDATE"
    if not _credential_allows(actor, controlled):
        fail("ERR_CREDENTIAL_NOT_DELEGATED",
             "This operator may not administer this medication.")
    if controlled and witness is None:
        fail("ERR_WITNESS_REQUIRED", "A controlled dose requires a witness.")
    witness_id = witness["id"] if witness else record.get("witness_nurse_id")
    if controlled and witness_id == record["administering_nurse_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The witness must differ from the administering nurse.")

    lot = db.medication_stock_lots.get(record["lot_id"])
    units = record["units"]
    clock = db.now()
    if witness is not None:
        record["witness_nurse_id"] = witness["id"]
    if supplied(values, "reason_code"):
        record["reason_code"] = values["reason_code"]
    record["status"] = outcome
    if outcome == "ADMINISTERED":
        record["administered_at"] = clock
        touch(record)
        if lot is not None:
            cascades.move_units(lot, "quantity_reserved", "quantity_administered", units)
            cascades.refresh_lot_state(lot)
        visit = db.health_visits.get(record["visit_id"])
        if visit is not None:
            cascades.recompute_observed(db.students.get(visit["student_id"]))
    elif outcome == "REFUSED":
        touch(record)
        if lot is not None:
            cascades.move_units(lot, "quantity_reserved", "quantity_on_hand", units)
    else:
        touch(record)
        if lot is not None:
            cascades.move_units(lot, "quantity_reserved", "quantity_wasted", units)
            cascades.refresh_lot_state(lot)
    return ok(ser.record_json(record))


@bp.post("/health-office/administration-records/<record_id>/void")
def void_record_endpoint(record_id):
    user_id, role = authorize(["SchoolNurse"])
    record = db.administration_records.get(record_id)
    nurse_owns(record, user_id, role, "administering_nurse_id")
    record = must_exist("administration_records", record_id, "AdministrationRecord")
    body = get_body(request)
    values = validate(body, [Field("reason_code", "string")])
    if record["status"] not in ("PREPARED", "ADMINISTERED", "WASTED"):
        fail("ERR_ADMINISTRATION_INVALID_STATE", "This record may not be voided.")
    if not db.now() < record["prepared_at"] + minutes(calc.VOID_WINDOW_MINUTES):
        fail("ERR_VOID_WINDOW_CLOSED", "The void window has closed.")
    cascades.void_record(record, values["reason_code"])
    return ok(ser.record_json(record))

"""Medication orders and medication stock lots."""
from flask import Blueprint, request

import calc
import cascades
import serializers as ser
from auth import (ALL_READ_ROLES, ALL_READ_ROLES_WITH_GUARDIAN, authorize,
                  guardian_owns, insert, must_exist, principal, require_role,
                  resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import db, new_record, parse_dt, sorted_rows, touch
from validators import Field, get_body, supplied, validate, value_or

bp = Blueprint("meds", __name__)

MEDICATIONS = {"EPINEPHRINE", "ALBUTEROL", "INSULIN", "METHYLPHENIDATE", "ACETAMINOPHEN"}
ROUTES = {"IM", "INHALED", "ORAL", "SUBQ"}
DOSE_UNITS = {"MG", "MCG", "ML", "PUFF", "UNIT"}
SCHEDULES = {"SCHEDULED", "PRN"}
LOT_READ_ROLES = ["DistrictHealthAdmin", "SchoolNurse", "HealthAide", "SchoolPhysician"]


# ---------------------------------------------------------------------------
# MedicationAuthorization
# ---------------------------------------------------------------------------

@bp.post("/health-office/medication-authorizations")
def create_authorization():
    authorize(["SchoolNurse"])
    body = get_body(request)
    student = resolve("students", body.get("student_id"), "Student")
    plan = None
    if body.get("action_plan_id") is not None:
        plan = resolve("action_plans", body.get("action_plan_id"), "ActionPlan")
        if student is not None and plan["student_id"] != student["id"]:
            fail("ERR_RESOURCE_NOT_FOUND",
                 "The action plan does not belong to this student.")
    values = validate(body, [
        Field("student_id", "string"),
        Field("medication_code", "enum", enum=MEDICATIONS),
        Field("route", "enum", enum=ROUTES),
        Field("dose_amount", "number", exclusive_minimum=0),
        Field("dose_unit", "enum", enum=DOSE_UNITS),
        Field("schedule_type", "enum", enum=SCHEDULES),
        Field("max_doses_per_day", "integer", minimum=1, maximum=12),
        Field("valid_from", "datetime"),
        Field("valid_until", "datetime"),
        Field("action_plan_id", "string", required=False),
        Field("prn_min_interval_minutes", "integer", required=False,
              minimum=1, maximum=1440),
    ])
    schedule_type = values["schedule_type"]
    has_interval = supplied(values, "prn_min_interval_minutes")
    if schedule_type == "PRN" and not has_interval:
        fail("ERR_MISSING_REQUIRED_FIELD",
             "prn_min_interval_minutes is required for a PRN order.")
    if schedule_type == "SCHEDULED" and has_interval:
        fail("ERR_INVALID_FIELD_VALUE",
             "prn_min_interval_minutes must be null for a SCHEDULED order.")
    valid_from = parse_dt(values["valid_from"])
    valid_until = parse_dt(values["valid_until"])
    if valid_until <= valid_from:
        fail("ERR_INVALID_FIELD_VALUE", "valid_until must be later than valid_from.")
    if student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    record = new_record({
        "student_id": student["id"],
        "action_plan_id": plan["id"] if plan else None,
        "medication_code": values["medication_code"],
        "route": values["route"],
        "dose_amount": values["dose_amount"],
        "dose_unit": values["dose_unit"],
        "schedule_type": schedule_type,
        "prn_min_interval_minutes": (values["prn_min_interval_minutes"]
                                     if has_interval else None),
        "max_doses_per_day": values["max_doses_per_day"],
        "valid_from": valid_from,
        "valid_until": valid_until,
        "is_controlled": values["medication_code"] == "METHYLPHENIDATE",
        "consent_status": "CONSENT_PENDING",
        "clinical_status": "UNVERIFIED",
    })
    insert("medication_authorizations", record)
    return created(ser.authorization_json(record))


@bp.get("/health-office/medication-authorizations/<auth_id>")
def get_authorization(auth_id):
    user_id, role = authorize(ALL_READ_ROLES_WITH_GUARDIAN)
    auth = db.medication_authorizations.get(auth_id)
    guardian_owns(auth, user_id, role)
    auth = must_exist("medication_authorizations", auth_id, "MedicationAuthorization")
    return ok(ser.authorization_json(auth))


@bp.get("/health-office/medication-authorizations")
def list_authorizations():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("medication_authorizations")
    for key in ("student_id", "action_plan_id", "medication_code",
                "consent_status", "clinical_status"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.authorization_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/medication-authorizations/<auth_id>/consent")
def authorization_consent(auth_id):
    user_id, role = authorize(["Guardian"])
    auth = db.medication_authorizations.get(auth_id)
    guardian_owns(auth, user_id, role)
    auth = must_exist("medication_authorizations", auth_id, "MedicationAuthorization")
    body = get_body(request)
    values = validate(body, [Field("decision", "enum", enum={"GRANT", "WITHDRAW"})])
    decision = values["decision"]
    current = auth["consent_status"]
    if decision == "GRANT":
        if current not in ("CONSENT_PENDING", "CONSENT_WITHDRAWN"):
            fail("ERR_AUTHORIZATION_INVALID_STATE", "Consent is already granted.")
        if current == "CONSENT_PENDING":
            student = db.students.get(auth["student_id"])
            if student is None or student["enrollment_status"] != "ENROLLED":
                fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
        auth["consent_status"] = "CONSENT_GRANTED"
        touch(auth)
    else:
        if current != "CONSENT_GRANTED":
            fail("ERR_AUTHORIZATION_INVALID_STATE", "Consent is not currently granted.")
        auth["consent_status"] = "CONSENT_WITHDRAWN"
        touch(auth)
        cascades.void_prepared_for_authorization(auth["id"])
    return ok(ser.authorization_json(auth))


@bp.post("/health-office/medication-authorizations/<auth_id>/clinical-review")
def authorization_clinical_review(auth_id):
    user_id, role = principal()
    require_role(role, ["SchoolNurse", "SchoolPhysician"])
    body = get_body(request)
    decision = body.get("decision") if isinstance(body, dict) else None
    # Ladder position 2 - the decision selects which role may act.
    if decision == "VERIFY":
        if role != "SchoolNurse":
            fail("ERR_ROLE_NOT_PERMITTED", "Only a school nurse may verify an order.")
        nurse = db.nurses.get(user_id)
        if nurse is None or nurse.get("credential") != "RN":
            fail("ERR_ROLE_NOT_PERMITTED", "Only an RN may verify an order.")
    elif decision == "SUSPEND":
        if role != "SchoolPhysician":
            fail("ERR_ROLE_NOT_PERMITTED", "Only a physician may suspend an order.")
    auth = must_exist("medication_authorizations", auth_id, "MedicationAuthorization")
    values = validate(body, [
        Field("decision", "enum", enum={"VERIFY", "SUSPEND"}),
        Field("note", "string", required=False),
    ])
    decision = values["decision"]
    current = auth["clinical_status"]
    if decision == "VERIFY":
        if current not in ("UNVERIFIED", "SUSPENDED"):
            fail("ERR_AUTHORIZATION_INVALID_STATE",
                 "The order cannot be verified from %s." % current)
        plan_id = auth.get("action_plan_id")
        if plan_id is not None:
            plan = db.action_plans.get(plan_id)
            if plan is None or plan["status"] != "ACTIVE":
                fail("ERR_PLAN_INVALID_STATE",
                     "The linked action plan is not ACTIVE.")
        auth["clinical_status"] = "VERIFIED"
        touch(auth)
    else:
        if current != "VERIFIED":
            fail("ERR_AUTHORIZATION_INVALID_STATE",
                 "Only a VERIFIED order may be suspended.")
        cascades.suspend_authorization(auth)
    return ok(ser.authorization_json(auth))


# ---------------------------------------------------------------------------
# MedicationStockLot
# ---------------------------------------------------------------------------

@bp.post("/health-office/medication-stock-lots")
def create_lot():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    school = resolve("schools", body.get("school_id"), "School")
    values = validate(body, [
        Field("school_id", "string"),
        Field("medication_code", "enum", enum=MEDICATIONS),
        Field("lot_number", "string"),
        Field("is_stock_protocol", "boolean"),
        Field("initial_quantity", "integer", minimum=1),
        Field("expiration_date", "datetime"),
    ])
    expiration = parse_dt(values["expiration_date"])
    if not expiration > db.now():
        fail("ERR_LOT_EXPIRED", "The lot is already at or past its expiration.")
    quantity = values["initial_quantity"]
    record = new_record({
        "school_id": school["id"],
        "medication_code": values["medication_code"],
        "lot_number": values["lot_number"],
        "is_stock_protocol": values["is_stock_protocol"],
        "expiration_date": expiration,
        "received_total": quantity,
        "quantity_on_hand": quantity,
        "quantity_reserved": 0,
        "quantity_administered": 0,
        "quantity_wasted": 0,
        "status": "AVAILABLE",
    })
    insert("medication_stock_lots", record)
    return created(ser.lot_json(record))


@bp.get("/health-office/medication-stock-lots/<lot_id>")
def get_lot(lot_id):
    authorize(LOT_READ_ROLES)
    lot = must_exist("medication_stock_lots", lot_id, "MedicationStockLot")
    return ok(ser.lot_json(lot))


@bp.get("/health-office/medication-stock-lots")
def list_lots():
    authorize(LOT_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("medication_stock_lots")
    for key in ("school_id", "medication_code", "status"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    stock_flag = request.args.get("is_stock_protocol")
    if stock_flag is not None:
        wanted = str(stock_flag).lower() in ("true", "1")
        result = [r for r in result if bool(r["is_stock_protocol"]) == wanted]
    return listing([ser.lot_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/medication-stock-lots/<lot_id>/inventory-action")
def lot_inventory_action(lot_id):
    authorize(["DistrictHealthAdmin"])
    lot = must_exist("medication_stock_lots", lot_id, "MedicationStockLot")
    body = get_body(request)
    values = validate(body, [
        Field("action", "enum", enum={"RECEIVE", "DISCARD", "QUARANTINE", "RESTORE"}),
        Field("expected_lot_version", "integer"),
        Field("units", "integer", required=False, minimum=1),
        Field("reason_code", "string", required=False),
    ])
    action = values["action"]
    if action in ("RECEIVE", "DISCARD") and not supplied(values, "units"):
        fail("ERR_MISSING_REQUIRED_FIELD", "units is required for a %s action." % action)

    # Ladder position 11 - lot from-state
    status = lot["status"]
    if status == "EXPIRED":
        fail("ERR_LOT_INVALID_STATE", "An EXPIRED lot admits no inventory action.")
    if action == "QUARANTINE" and status not in ("AVAILABLE", "DEPLETED"):
        fail("ERR_LOT_INVALID_STATE", "Only an AVAILABLE or DEPLETED lot may be quarantined.")
    if action == "RESTORE" and status != "QUARANTINED":
        fail("ERR_LOT_INVALID_STATE", "Only a QUARANTINED lot may be restored.")
    if action in ("RECEIVE", "DISCARD") and status not in ("AVAILABLE", "QUARANTINED", "DEPLETED"):
        fail("ERR_LOT_INVALID_STATE", "The lot does not admit this action.")

    # Ladder position 16 - optimistic concurrency on the lot version
    if values["expected_lot_version"] != lot["version"]:
        fail("ERR_STALE_LOT_VERSION", "expected_lot_version is stale.")

    # Ladder position 39 - the lot must still be unexpired
    if not lot["expiration_date"] > db.now():
        fail("ERR_LOT_EXPIRED", "The lot has passed its expiration date.")

    units = value_or(values, "units", 0)
    if action == "DISCARD" and lot["quantity_on_hand"] - units < 0:
        fail("ERR_INSUFFICIENT_STOCK", "The discard would drive quantity_on_hand below zero.")

    if supplied(values, "reason_code"):
        lot["reason_code"] = values["reason_code"]

    if action == "RECEIVE":
        lot["received_total"] += units
        lot["quantity_on_hand"] += units
        touch(lot)
        cascades.refresh_lot_state(lot)
    elif action == "DISCARD":
        lot["quantity_on_hand"] -= units
        lot["quantity_wasted"] += units
        touch(lot)
        cascades.refresh_lot_state(lot)
    elif action == "QUARANTINE":
        cascades.quarantine_cascade(lot)
    else:
        lot["status"] = "AVAILABLE"
        touch(lot)
    return ok(ser.lot_json(lot))

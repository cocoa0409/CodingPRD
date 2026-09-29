"""Driver hiring, motor-vehicle records, insurance and qualification (PRD 3.6)."""
from flask import Blueprint

import auth
import cascade
import clock
import db
import derive
import listing
import response
import serialize
import validate
from errors import fail

bp = Blueprint("drivers", __name__)

READ_ROLES = auth.ALL_ROLES
VEHICLE_CLASSES = ("CAR", "SUV", "SCOOTER")
QUALIFICATION_STATUSES = ("APPLICANT", "PENDING_CHECKS", "QUALIFIED", "SUSPENDED", "DISQUALIFIED")
MVR_RESULTS = ("CLEAR", "MINOR_VIOLATIONS", "FAILED")
INSURANCE_STATUSES = ("VERIFIED", "REJECTED", "SUPERSEDED")
DECISIONS = ("QUALIFY", "SUSPEND", "REINSTATE", "DISQUALIFY")

DECISION_FROM = {
    "QUALIFY": ("PENDING_CHECKS",),
    "SUSPEND": ("QUALIFIED",),
    "REINSTATE": ("SUSPENDED",),
    "DISQUALIFY": ("PENDING_CHECKS", "QUALIFIED", "SUSPENDED"),
}


@bp.post("/store-ops/drivers")
def hire_driver():
    actor = auth.authenticate(["StoreManager"])
    auth.guard(actor, [], [("store_id", "store")])
    body = validate.body()
    raw_store_id = body.get("store_id")
    store = None
    if isinstance(raw_store_id, str) and raw_store_id != "":
        store = auth.body_fk("store", raw_store_id)
    validate.string(body, "store_id")
    full_name = validate.string(body, "full_name")
    license_number = validate.string(body, "license_number")
    vehicle_class = validate.enum(body, "vehicle_class", VEHICLE_CLASSES)
    for existing in db.drivers.values():
        if existing["store_id"] == store["id"] and existing["license_number"] == license_number:
            fail("ERR_LICENSE_NUMBER_TAKEN", "That licence number is already on file at this store.")
    record = {
        "store_id": store["id"],
        "full_name": full_name,
        "license_number": license_number,
        "vehicle_class": vehicle_class,
        "qualification_status": "APPLICANT",
        "qualified_by_user_id": None,
        "disqualified_reason": None,
    }
    db.insert(db.drivers, record)
    return response.created(serialize.driver(record))


@bp.post("/store-ops/drivers/<driver_id>/mvr-checks")
def record_mvr_check(driver_id):
    actor = auth.authenticate(["ComplianceOfficer"])
    (driver,) = auth.guard(actor, [("driver", driver_id)])
    body = validate.body()
    result = validate.enum(body, "result", MVR_RESULTS)
    violation_points = validate.integer(body, "violation_points", minimum=0, maximum=20)
    checked_on = validate.instant(body, "checked_on")
    record = {
        "driver_id": driver["id"],
        "result": result,
        "violation_points": violation_points,
        "checked_on": checked_on,
        "recorded_by_user_id": actor.user_id,
    }
    db.insert(db.mvr_checks, record, versioned=False)
    if result == "FAILED":
        if driver["qualification_status"] in ("APPLICANT", "PENDING_CHECKS", "QUALIFIED", "SUSPENDED"):
            cascade.disqualify_driver(driver, "MVR_FAILED")
    elif driver["qualification_status"] == "APPLICANT":
        driver["qualification_status"] = "PENDING_CHECKS"
    db.touch(driver)
    return response.created(serialize.mvr_check(record))


@bp.post("/store-ops/drivers/<driver_id>/insurance-verifications")
def file_insurance(driver_id):
    actor = auth.authenticate(["ComplianceOfficer"])
    (driver,) = auth.guard(actor, [("driver", driver_id)])
    body = validate.body()
    policy_number = validate.string(body, "policy_number")
    coverage_from = validate.instant(body, "coverage_from")
    coverage_to = validate.instant(body, "coverage_to")
    liability = validate.integer(body, "liability_limit_cents", minimum=0)
    expected_driver_version = validate.integer(body, "expected_driver_version")
    if not coverage_to > coverage_from:
        fail("ERR_INVALID_COVERAGE_WINDOW", "coverage_to must be strictly after coverage_from.")
    if expected_driver_version != driver["version"]:
        fail("ERR_STALE_DRIVER_VERSION", "The driver has moved on; re-read the driver record.")
    previous = [c for c in db.insurance_verifications.values() if c["driver_id"] == driver["id"]]
    for certificate in db.ordered(previous):
        certificate["status"] = "SUPERSEDED"
        db.touch(certificate)
    verified = liability >= 10000000
    record = {
        "driver_id": driver["id"],
        "policy_number": policy_number,
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "liability_limit_cents": liability,
        "status": "VERIFIED" if verified else "REJECTED",
        "rejected_reason": None
        if verified
        else "Combined single-limit liability is below 10000000 cents.",
    }
    db.insert(db.insurance_verifications, record)
    db.touch(driver)
    return response.created(serialize.insurance_verification(record))


@bp.post("/store-ops/drivers/<driver_id>/qualification-decisions")
def qualification_decision(driver_id):
    actor = auth.authenticate(["ComplianceOfficer"])
    (driver,) = auth.guard(actor, [("driver", driver_id)])
    body = validate.body()
    decision = validate.enum(body, "decision", DECISIONS)
    reason = validate.string(body, "reason", required=False)
    if decision == "DISQUALIFY" and reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'reason' is required on a DISQUALIFY decision.")
    if driver["qualification_status"] not in DECISION_FROM[decision]:
        fail(
            "ERR_INVALID_DRIVER_STATE",
            "Decision %s is not declared from %s." % (decision, driver["qualification_status"]),
        )
    if decision in ("QUALIFY", "REINSTATE"):
        if not derive.insurance_covers(driver["id"], clock.now()):
            fail("ERR_INSURANCE_NOT_ACTIVE", "No verified certificate covers the current instant.")
        if derive.driver_mvr_points(driver["id"]) > 5:
            fail("ERR_MVR_POINTS_EXCEEDED", "The driver's latest violation-point total exceeds 5.")
        newest = derive.newest_mvr_check(driver["id"])
        if newest is not None and newest["recorded_by_user_id"] == actor.user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The officer who pulled the record may not sign the decision.",
            )
    if decision == "QUALIFY" or decision == "REINSTATE":
        driver["qualification_status"] = "QUALIFIED"
        driver["qualified_by_user_id"] = actor.user_id
    elif decision == "SUSPEND":
        driver["qualification_status"] = "SUSPENDED"
    else:
        cascade.disqualify_driver(driver, reason)
    db.touch(driver)
    # PRD 4: signing a qualification decision "create[s] a record as [its]
    # principal effect" and answers 201 with "that new resource in the data field".
    record = {"driver_id": driver["id"], "decision": decision, "reason": reason}
    db.insert(db.qualification_decisions, record)
    return response.created(serialize.qualification_decision(record))


@bp.get("/store-ops/drivers/<driver_id>")
def read_driver(driver_id):
    actor = auth.authenticate(READ_ROLES)
    (driver,) = auth.guard(actor, [("driver", driver_id)])
    return response.ok(serialize.driver(driver))


@bp.get("/store-ops/drivers")
def list_drivers():
    actor = auth.authenticate(READ_ROLES)
    store_id = validate.filter_string("store_id")
    qualification_status = validate.filter_enum("qualification_status", QUALIFICATION_STATUSES)
    vehicle_class = validate.filter_enum("vehicle_class", VEHICLE_CLASSES)
    records = list(db.drivers.values())
    if actor.is_manager:
        records = [d for d in records if d["store_id"] == actor.user_id]
    elif actor.is_driver:
        records = [d for d in records if d["id"] == actor.user_id]
    if store_id is not None:
        records = [d for d in records if d["store_id"] == store_id]
    if qualification_status is not None:
        records = [d for d in records if d["qualification_status"] == qualification_status]
    if vehicle_class is not None:
        records = [d for d in records if d["vehicle_class"] == vehicle_class]
    return listing.respond(records, serialize.driver)


@bp.get("/store-ops/mvr-checks/<mvr_check_id>")
def read_mvr_check(mvr_check_id):
    actor = auth.authenticate(["StoreManager", "ComplianceOfficer"])
    (record,) = auth.guard(actor, [("mvr_check", mvr_check_id)])
    return response.ok(serialize.mvr_check(record))


@bp.get("/store-ops/mvr-checks")
def list_mvr_checks():
    auth.authenticate(["StoreManager", "ComplianceOfficer"])
    driver_id = validate.filter_string("driver_id")
    result = validate.filter_enum("result", MVR_RESULTS)
    records = list(db.mvr_checks.values())
    if driver_id is not None:
        records = [r for r in records if r["driver_id"] == driver_id]
    if result is not None:
        records = [r for r in records if r["result"] == result]
    # The one collection returned newest first.
    return listing.respond(records, serialize.mvr_check, descending=True)


@bp.get("/store-ops/insurance-verifications/<insurance_verification_id>")
def read_insurance(insurance_verification_id):
    actor = auth.authenticate(["StoreManager", "ComplianceOfficer"])
    (record,) = auth.guard(actor, [("insurance_verification", insurance_verification_id)])
    return response.ok(serialize.insurance_verification(record))


@bp.get("/store-ops/insurance-verifications")
def list_insurance():
    auth.authenticate(["StoreManager", "ComplianceOfficer"])
    driver_id = validate.filter_string("driver_id")
    status = validate.filter_enum("status", INSURANCE_STATUSES)
    records = list(db.insurance_verifications.values())
    if driver_id is not None:
        records = [r for r in records if r["driver_id"] == driver_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return listing.respond(records, serialize.insurance_verification)

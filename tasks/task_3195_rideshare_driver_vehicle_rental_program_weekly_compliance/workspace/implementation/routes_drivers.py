"""Driver and enrolment endpoints."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_DRIVING_RECORD_INELIGIBLE, E_INVALID_REQUEST, E_INVALID_STATE,
                    E_PLATFORM_ACTIVITY_INSUFFICIENT, E_REFERENCED_ENTITY_NOT_FOUND,
                    E_UNAUTHORIZED, raise_error)
from middleware import (PLATFORM_ID_RE, check_schema, is_int, is_str)
from middleware import body as get_body
from response import ok, ok_list
from services import (OCCUPANCY_HOLDING, all_of, by_created, get_driver,
                      get_enrollment, paginate, PROGRAM_ACTIVITY_FLOOR)

bp = Blueprint("drivers", __name__)

LICENSE_CLASSES = ("STANDARD", "FOR_HIRE", "COMMERCIAL")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
DRIVER_STATUSES = ("PENDING", "ELIGIBLE", "INELIGIBLE", "SUSPENDED")
ENROLLMENT_STATUSES = ("PENDING_VERIFICATION", "ACTIVE", "REJECTED", "SUSPENDED", "WITHDRAWN")


def _text(value, field):
    if not is_str(value) or not value.strip():
        raise_error(E_INVALID_REQUEST, "%s must be a non-empty string." % field)
    return value


def _bounded_int(value, field, low, high):
    if not is_int(value):
        raise_error(E_INVALID_REQUEST, "%s must be an integer." % field)
    if value < low or value > high:
        raise_error(E_INVALID_REQUEST, "%s must be between %d and %d." % (field, low, high))
    return value


def _enum(value, field, allowed):
    if value not in allowed:
        raise_error(E_INVALID_REQUEST, "%s must be one of %s." % (field, ", ".join(allowed)))
    return value


@bp.post("/program/drivers")
def create_driver():
    payload = get_body()
    check_schema(payload, "POST", "/program/drivers")
    full_name = _text(payload["full_name"], "full_name")
    email = _text(payload["email"], "email")
    platform_driver_id = _text(payload["platform_driver_id"], "platform_driver_id")
    if not PLATFORM_ID_RE.match(platform_driver_id):
        raise_error(E_INVALID_REQUEST,
                    "platform_driver_id must be PLT- followed by eight alphanumerics.")
    activity = _bounded_int(payload["platform_activity_score"], "platform_activity_score", 0, 100)
    points = _bounded_int(payload["driving_record_points"], "driving_record_points", 0, 12)
    license_class = _enum(payload["license_class"], "license_class", LICENSE_CLASSES)
    tier = _enum(payload["program_driver_tier"], "program_driver_tier", TIERS)

    for existing in db.DRIVERS.values():
        if existing["email"].lower() == email.lower():
            raise_error(E_INVALID_REQUEST, "email is already registered.")
        if existing["platform_driver_id"] == platform_driver_id:
            raise_error(E_INVALID_REQUEST, "platform_driver_id is already registered.")

    row = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "platform_driver_id": platform_driver_id,
        "platform_activity_score": activity,
        "driving_record_points": points,
        "license_class": license_class,
        "program_driver_tier": tier,
        "eligibility_status": "PENDING",
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.DRIVERS[row["id"]] = row
    return ok(svc.driver_out(row), 201)


@bp.get("/program/drivers")
def list_drivers():
    rows = by_created(db.DRIVERS.values())
    status = request.args.get("eligibility_status")
    tier = request.args.get("program_driver_tier")
    if status:
        rows = [r for r in rows if r["eligibility_status"] == status]
    if tier:
        rows = [r for r in rows if r["program_driver_tier"] == tier]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.driver_out(r) for r in page], limit, offset, total)


@bp.get("/program/drivers/<driver_id>")
def get_one_driver(driver_id):
    return ok(svc.driver_out(get_driver(driver_id)))


@bp.post("/program/drivers/<driver_id>/activity")
def set_activity(driver_id):
    driver = get_driver(driver_id)
    payload = get_body()
    check_schema(payload, "POST", "/program/drivers/{id}/activity")
    score = _bounded_int(payload["platform_activity_score"], "platform_activity_score", 0, 100)
    driver["platform_activity_score"] = score
    db.touch(driver)
    _refresh_enrollments(driver)
    return ok(svc.driver_out(driver))


@bp.post("/program/drivers/<driver_id>/driving-record")
def set_record(driver_id):
    driver = get_driver(driver_id)
    payload = get_body()
    check_schema(payload, "POST", "/program/drivers/{id}/driving-record")
    points = _bounded_int(payload["driving_record_points"], "driving_record_points", 0, 12)
    driver["driving_record_points"] = points
    db.touch(driver)
    _refresh_enrollments(driver)
    return ok(svc.driver_out(driver))


def _refresh_enrollments(driver):
    for enrollment in all_of(db.ENROLLMENTS, lambda e: e["driver_id"] == driver["id"]):
        if enrollment["enrollment_status"] == "WITHDRAWN":
            continue
        svc.evaluate_enrollment(enrollment)
        db.touch(enrollment)
    svc.refresh_driver_posture(driver)
    db.touch(driver)


@bp.get("/program/drivers/<driver_id>/enrollments")
def driver_enrollments(driver_id):
    driver = get_driver(driver_id)
    rows = by_created(all_of(db.ENROLLMENTS, lambda e: e["driver_id"] == driver["id"]))
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.enrollment_out(r) for r in page], limit, offset, total)


@bp.get("/program/drivers/<driver_id>/summary")
def driver_summary(driver_id):
    driver = get_driver(driver_id)
    enrollments = by_created(all_of(db.ENROLLMENTS, lambda e: e["driver_id"] == driver["id"]))
    active = next((e for e in enrollments if e["enrollment_status"] == "ACTIVE"), None)
    vehicle = next((v for v in db.VEHICLES.values()
                    if v["vehicle_status"] == "ASSIGNED"
                    and v["assigned_driver_id"] == driver["id"]), None)
    outstanding = 0
    open_week_number = 0
    agreements = by_created(all_of(db.AGREEMENTS, lambda a: a["driver_id"] == driver["id"]))
    # the balance is read off every week that is not yet settled, whether or
    # not its period has been metered into a receivable
    for agreement in agreements:
        for week in svc.weeks_of(agreement["id"]):
            if week["week_status"] not in ("PAID", "WAIVED", "RECOVERED"):
                outstanding += week["amount_due_cents"]
    live = [a for a in agreements if a["agreement_status"] in OCCUPANCY_HOLDING]
    if live:
        open_week_number = live[-1]["current_week_number"]
    return ok({
        "driver_id": driver["id"],
        "eligibility_status": driver["eligibility_status"],
        "active_enrollment_id": active["id"] if active else None,
        "assigned_vehicle_id": vehicle["id"] if vehicle else None,
        "outstanding_balance_cents": outstanding,
        "open_week_number": open_week_number,
    })


# --- Enrolments ---------------------------------------------------------------

@bp.post("/program/enrollments")
def create_enrollment():
    payload = get_body()
    check_schema(payload, "POST", "/program/enrollments")
    driver_id = payload["driver_id"]
    if driver_id not in db.DRIVERS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "driver_id does not name a driver.")
    driver = db.DRIVERS[driver_id]
    tier = _enum(payload["program_tier"], "program_tier", TIERS)

    if driver["driving_record_points"] > 6:
        raise_error(E_DRIVING_RECORD_INELIGIBLE,
                    "The driver's driving record points exceed the programme ceiling.")
    if driver["platform_activity_score"] < PROGRAM_ACTIVITY_FLOOR:
        raise_error(E_PLATFORM_ACTIVITY_INSUFFICIENT,
                    "The driver's platform activity score is below the programme floor.")

    row = {
        "id": db.new_id(),
        "driver_id": driver_id,
        "program_tier": tier,
        "activity_snapshot": driver["platform_activity_score"],
        "record_snapshot": driver["driving_record_points"],
        "eligibility_score": 0,
        "eligibility_decision": "DENIED",
        "enrollment_status": "PENDING_VERIFICATION",
        "verified_at": None,
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.ENROLLMENTS[row["id"]] = row
    svc.evaluate_enrollment(row)
    return ok(svc.enrollment_out(row), 201)


@bp.get("/program/enrollments")
def list_enrollments():
    rows = by_created(db.ENROLLMENTS.values())
    driver_id = request.args.get("driver_id")
    status = request.args.get("enrollment_status")
    if driver_id:
        rows = [r for r in rows if r["driver_id"] == driver_id]
    if status:
        rows = [r for r in rows if r["enrollment_status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.enrollment_out(r) for r in page], limit, offset, total)


@bp.get("/program/enrollments/<enrollment_id>")
def get_one_enrollment(enrollment_id):
    return ok(svc.enrollment_out(get_enrollment(enrollment_id)))


@bp.post("/program/enrollments/<enrollment_id>/verify")
def verify_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    if enrollment["enrollment_status"] != "PENDING_VERIFICATION":
        raise_error(E_INVALID_STATE, "The enrolment is not awaiting verification.")
    driver = db.DRIVERS[enrollment["driver_id"]]
    if enrollment["eligibility_decision"] == "APPROVED":
        enrollment["enrollment_status"] = "ACTIVE"
        enrollment["verified_at"] = db.now()
        db.touch(enrollment)
        driver["eligibility_status"] = "ELIGIBLE"
        driver["program_driver_tier"] = enrollment["program_tier"]
        db.touch(driver)
    elif enrollment["eligibility_decision"] == "DENIED":
        enrollment["enrollment_status"] = "REJECTED"
        db.touch(enrollment)
        driver["eligibility_status"] = "INELIGIBLE"
        db.touch(driver)
    else:
        # a deferred application is still welcome: it admits the driver, whose
        # activity reading simply sits below the level the programme prefers
        enrollment["enrollment_status"] = "ACTIVE"
        enrollment["verified_at"] = db.now()
        db.touch(enrollment)
        driver["eligibility_status"] = "ELIGIBLE"
        driver["program_driver_tier"] = enrollment["program_tier"]
        db.touch(driver)
    return ok(svc.enrollment_out(enrollment))


@bp.post("/program/enrollments/<enrollment_id>/re-evaluate")
def re_evaluate_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    if enrollment["enrollment_status"] != "REJECTED":
        raise_error(E_INVALID_STATE, "Only a rejected enrolment may be re-evaluated.")
    driver = db.DRIVERS[enrollment["driver_id"]]
    enrollment["enrollment_status"] = "PENDING_VERIFICATION"
    driver["eligibility_status"] = "PENDING"
    db.touch(driver)
    svc.evaluate_enrollment(enrollment)
    db.touch(enrollment)
    return ok(svc.enrollment_out(enrollment))


@bp.post("/program/enrollments/<enrollment_id>/reinstate")
def reinstate_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    driver = db.DRIVERS[enrollment["driver_id"]]
    if enrollment["enrollment_status"] != "SUSPENDED":
        raise_error(E_INVALID_STATE, "The enrolment is not suspended.")
    for agreement in all_of(db.AGREEMENTS, lambda a: a["driver_id"] == driver["id"]):
        if agreement["compliance_posture"] == "FROZEN":
            raise_error(E_INVALID_STATE, "An agreement of this driver is still FROZEN.")
    enrollment["enrollment_status"] = "ACTIVE"
    db.touch(enrollment)
    if driver["eligibility_status"] == "SUSPENDED":
        driver["eligibility_status"] = "ELIGIBLE"
        db.touch(driver)
    return ok(svc.enrollment_out(enrollment))


@bp.post("/program/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    role = request.headers.get("X-User-Role")
    actor = request.headers.get("X-User-ID")
    if role == "Driver" and str(actor) != str(enrollment["driver_id"]):
        raise_error(E_UNAUTHORIZED, "The acting driver does not own this enrolment.")
    if enrollment["enrollment_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(E_INVALID_STATE, "Only an ACTIVE or SUSPENDED enrolment may be withdrawn.")
    for agreement in all_of(db.AGREEMENTS, lambda a: a["enrollment_id"] == enrollment["id"]):
        if agreement["agreement_status"] in OCCUPANCY_HOLDING:
            raise_error(E_INVALID_STATE,
                        "An occupancy-holding agreement of this enrolment remains open.")
    enrollment["enrollment_status"] = "WITHDRAWN"
    db.touch(enrollment)
    driver = db.DRIVERS[enrollment["driver_id"]]
    driver["eligibility_status"] = "INELIGIBLE"
    db.touch(driver)
    return ok(svc.enrollment_out(enrollment))
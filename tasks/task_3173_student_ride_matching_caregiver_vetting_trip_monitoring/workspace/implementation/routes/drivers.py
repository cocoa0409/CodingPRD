"""Driver endpoints: onboarding, the qualification pipeline, revocation and the
driver-side reverse reads.

Driver qualification is a strictly forward-moving succession of three gates
(PRD section 3.3): PENDING --open check--> BACKGROUND_CHECK --record
inspection--> INSPECTION --attest--> ACTIVE.
"""

import calculations as calc
import db
import models
import services
import validators as v
from clock import clock_date, now_utc, parse_date
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CAREGIVER_EXPERIENCE_SHORT,
    ERR_CLEARANCE_EXPIRED,
    ERR_CLEARANCE_INCOMPLETE,
    ERR_DUPLICATE_CLEARANCE,
    ERR_DRIVER_ON_TRIP,
    ERR_INSPECTION_SEAT_COUNT,
    ERR_INVALID_STATE,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("drivers", __name__)

DRIVER_INPUT = (
    "full_name", "phone", "employer_org", "caregiver_experience_months",
    "language_codes", "vehicle_class", "seat_capacity", "child_seat_type",
)
BACKGROUND_CHECK_INPUT = ("check_type", "reference_code", "expires_on")
INSPECTION_INPUT = ("vehicle_class", "seat_count", "child_seat_type", "inspector_note", "expires_on")

REVOCABLE_CHECK_TYPES = ("FINGERPRINT_FBI", "FINGERPRINT_STATE", "SEX_OFFENDER_REGISTRY")


def load_driver(driver_id):
    driver = db.get("drivers", driver_id)
    if driver is None:
        raise not_found("The addressed driver does not exist.")
    return driver


def _state_gate(current, required, msg, terminal=()):
    """Priority 9: wrong source state, or a terminal-lockdown probe."""
    if isinstance(required, str):
        required = (required,)
    if current in required:
        return
    if current in terminal:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The resource has already reached a terminal state for this dimension.",
        )
    raise ApiError(ERR_INVALID_STATE, msg)


def _current(record, key):
    """Recompute the derived fields the response must reflect."""
    return record[key]


def _months_between(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


@bp.post("/student-rides/drivers")
@requires("DistrictAdmin", "PlatformAdmin")
def create_driver():
    data = v.body()
    v.reject_unknown(data, DRIVER_INPUT)
    driver = db.new_record({
        "full_name": v.as_string(data, "full_name"),
        "phone": v.as_string(data, "phone"),
        "employer_org": v.as_string(data, "employer_org"),
        "caregiver_experience_months": v.as_int(data, "caregiver_experience_months", required_field=True),
        "language_codes": v.as_array(data, "language_codes", default=[]) or [],
        "vehicle_class": v.enum_value("vehicle_class", v.required(data, "vehicle_class")),
        "seat_capacity": v.as_int(data, "seat_capacity", required_field=True),
        "child_seat_type": v.enum_value("child_seat_type", data.get("child_seat_type", "NONE")),
        "approved_seat_count": 0,
        "compliance_expires_at": None,
        "incident_strike_count": 0,
        "status": "PENDING",
    })
    db.save("drivers", driver)
    return object_response(models.driver_out(driver), 201)


@bp.get("/student-rides/drivers")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_drivers():
    page, limit, offset, total = paginate(db.all_of("drivers"), request.args)
    return array_response(models.serialise_all("drivers", page), limit, offset, total)


@bp.get("/student-rides/drivers/<driver_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def get_driver(driver_id):
    driver = load_driver(driver_id)
    calc.recompute_driver(driver)
    return object_response(models.driver_out(driver))


@bp.post("/student-rides/drivers/<driver_id>/background-checks")
@requires("DistrictAdmin", "PlatformAdmin")
def create_background_check(driver_id):
    driver = load_driver(driver_id)
    data = v.body()
    v.reject_unknown(data, BACKGROUND_CHECK_INPUT)

    # PRD §3.3: the opening step "requires the driver to be in `PENDING`" and
    # PRD §3.3.1 makes `BACKGROUND_CHECK` a rebuildable state — a failed check
    # "is not erased by a later clearance, and the driver's covering paperwork
    # must be rebuilt from a fresh check" — so a further check may be opened
    # while the roster sits in either state. PRD §3.3 defines the duplication
    # rule per check type: opening a `FINGERPRINT_FBI` when one already exists is
    # refused with `ERR_DUPLICATE_CLEARANCE` (HTTP 409), while a check of another
    # type may still be added.
    _state_gate(
        driver["status"], ("PENDING", "BACKGROUND_CHECK"),
        "A background check may only be opened for a driver in PENDING.",
    )
    requested_check_type = v.enum_value("check_type", v.required(data, "check_type"))
    if requested_check_type == "FINGERPRINT_FBI" and any(
        c["check_type"] == "FINGERPRINT_FBI"
        for c in db.all_of("background_checks")
        if c["driver_id"] == driver_id
    ):
        raise ApiError(
            ERR_DUPLICATE_CLEARANCE,
            "The driver already holds a FINGERPRINT_FBI background check.",
        )

    check = db.new_record({
        "driver_id": driver_id,
        "check_type": v.enum_value("check_type", v.required(data, "check_type")),
        "reference_code": v.as_string(data, "reference_code"),
        "result": "PENDING",
        "expires_on": v.as_iso_date_string(data, "expires_on"),
        "cleared_after_months": None,
    })
    db.save("background_checks", check)

    driver["status"] = "BACKGROUND_CHECK"
    db.bump_version(driver)
    return object_response(models.background_check_out(check), 201)


@bp.get("/student-rides/drivers/<driver_id>/background-checks")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_background_checks(driver_id):
    load_driver(driver_id)
    rows = [c for c in db.all_of("background_checks") if c["driver_id"] == driver_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("background_checks", page), limit, offset, total)


@bp.post("/student-rides/drivers/<driver_id>/inspections")
@requires("DistrictAdmin", "PlatformAdmin")
def create_inspection(driver_id):
    driver = load_driver(driver_id)
    data = v.body()
    v.reject_unknown(data, INSPECTION_INPUT)

    _state_gate(
        driver["status"], "BACKGROUND_CHECK",
        "A vehicle inspection may only be recorded for a driver in BACKGROUND_CHECK.",
        terminal=("INACTIVE",),
    )
    if driver["caregiver_experience_months"] < calc.CAREGIVER_EXPERIENCE_MIN_MONTHS:
        raise ApiError(
            ERR_CAREGIVER_EXPERIENCE_SHORT,
            "The driver's declared caregiving experience is below the twelve-month minimum.",
        )
    cleared = [
        c for c in db.all_of("background_checks")
        if c["driver_id"] == driver_id and c["result"] == "CLEARED"
    ]
    if not cleared:
        raise ApiError(
            ERR_CLEARANCE_INCOMPLETE,
            "The driver has no CLEARED background check on file.",
        )

    inspection = db.new_record({
        "driver_id": driver_id,
        "vehicle_class": v.enum_value("vehicle_class", v.required(data, "vehicle_class")),
        "seat_count": v.as_int(data, "seat_count", required_field=True),
        "child_seat_type": v.enum_value("child_seat_type", data.get("child_seat_type", "NONE")),
        "inspector_note": v.as_string(data, "inspector_note", required_field=False),
        "result": "PENDING",
        "expires_on": v.as_iso_date_string(data, "expires_on"),
        "seat_credit": 0,
    })
    db.save("vehicle_inspections", inspection)

    driver["status"] = "INSPECTION"
    db.bump_version(driver)
    return object_response(models.vehicle_inspection_out(inspection), 201)


@bp.get("/student-rides/drivers/<driver_id>/inspections")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_inspections(driver_id):
    load_driver(driver_id)
    rows = [i for i in db.all_of("vehicle_inspections") if i["driver_id"] == driver_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("vehicle_inspections", page), limit, offset, total)


@bp.get("/student-rides/drivers/<driver_id>/trips")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def list_driver_trips(driver_id):
    load_driver(driver_id)
    rows = [
        t for t in db.all_of("trips")
        if t.get("driver_id") == driver_id or t.get("candidate_driver_id") == driver_id
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("trips", page), limit, offset, total)


@bp.get("/student-rides/drivers/<driver_id>/safety-incidents")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_driver_incidents(driver_id):
    load_driver(driver_id)
    rows = [i for i in db.all_of("safety_incidents") if i["driver_id"] == driver_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("safety_incidents", page), limit, offset, total)


@bp.post("/student-rides/drivers/<driver_id>/reactivate")
@requires("DistrictAdmin", "PlatformAdmin")
def reactivate_driver(driver_id):
    driver = load_driver(driver_id)
    _state_gate(
        driver["status"], "SUSPENDED",
        "Only a SUSPENDED driver may be reactivated.",
        terminal=("INACTIVE",),
    )
    expiry = driver.get("compliance_expires_at")
    if not expiry or parse_date(expiry) <= clock_date():
        raise ApiError(
            ERR_CLEARANCE_EXPIRED,
            "The driver's compliance coverage has lapsed.",
        )
    driver["status"] = "ACTIVE"
    db.bump_version(driver)
    return object_response(models.driver_out(driver))


@bp.post("/student-rides/drivers/<driver_id>/deactivate")
@requires("DistrictAdmin", "PlatformAdmin")
def deactivate_driver(driver_id):
    driver = load_driver(driver_id)
    _state_gate(
        driver["status"], ("ACTIVE", "SUSPENDED"),
        "Only an ACTIVE or SUSPENDED driver may be deactivated.",
        terminal=("INACTIVE",),
    )
    on_trip = any(
        t.get("driver_id") == driver_id and t["trip_state"] in calc.IN_PROGRESS_TRIP_STATES
        for t in db.all_of("trips")
    )
    if on_trip:
        raise ApiError(
            ERR_DRIVER_ON_TRIP,
            "The driver has a trip in progress and cannot be deactivated.",
        )
    driver["status"] = "INACTIVE"
    driver["approved_seat_count"] = 0
    db.bump_version(driver)
    return object_response(models.driver_out(driver))


# --- BackgroundCheck transitions --------------------------------------------

def load_background_check(check_id):
    check = db.get("background_checks", check_id)
    if check is None:
        raise not_found("The addressed background check does not exist.")
    return check


@bp.post("/student-rides/background-checks/<check_id>/clear")
@requires("DistrictAdmin", "PlatformAdmin")
def clear_background_check(check_id):
    check = load_background_check(check_id)
    driver = load_driver(check["driver_id"])
    _state_gate(
        check["result"], "PENDING",
        "Only a PENDING background check may be cleared.",
        terminal=("CLEARED", "FAILED"),
    )
    if parse_date(check["expires_on"]) <= clock_date():
        raise ApiError(ERR_CLEARANCE_EXPIRED, "The clearance's expires_on has already lapsed.")

    now = now_utc()
    check["result"] = "CLEARED"
    check["cleared_after_months"] = _months_between(parse_date(check["created_at"]), now.date())
    db.bump_version(check)

    calc.recompute_driver(driver)
    # A failure is not erased by a later clearance.
    if any(c["driver_id"] == driver["id"] and c["result"] == "FAILED"
           for c in db.all_of("background_checks")):
        driver["status"] = "BACKGROUND_CHECK"
    db.bump_version(driver)
    return object_response(models.background_check_out(check))


@bp.post("/student-rides/background-checks/<check_id>/fail")
@requires("DistrictAdmin", "PlatformAdmin")
def fail_background_check(check_id):
    check = load_background_check(check_id)
    driver = load_driver(check["driver_id"])

    if check["result"] == "FAILED":
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The background check has already reached a terminal state.",
        )
    if check["result"] == "PENDING":
        check["result"] = "FAILED"
        db.bump_version(check)
        for other in db.all_of("background_checks"):
            if other["driver_id"] == driver["id"] and other["id"] != check["id"] and other["result"] == "PENDING":
                other["result"] = "FAILED"
                db.bump_version(other)
        driver["status"] = "PENDING"
        driver["approved_seat_count"] = 0
        driver["compliance_expires_at"] = None
        db.bump_version(driver)
        for trip in db.all_of("trips"):
            if trip.get("driver_id") != driver["id"]:
                continue
            if trip["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
                continue
            trip["trip_state"] = "CANCELLED"
            trip["driver_id"] = None
            trip["candidate_driver_id"] = None
            trip["safety_state"] = "LOCKED"
            db.bump_version(trip)
            services.refresh_trip_relations(trip)
        return object_response(models.background_check_out(check))

    # CLEARED -> FAILED is the revocation path.
    if check["check_type"] not in REVOCABLE_CHECK_TYPES:
        raise ApiError(
            ERR_INVALID_STATE,
            "A cleared COUNTY_COURT check cannot be revoked through this operation.",
        )
    check["result"] = "FAILED"
    db.bump_version(check)
    # PRD §3.3.1: "Revoking a cleared fingerprint clearance moves the driver to
    # `SUSPENDED`, recomputes the approved seat count, and cancels every trip for
    # that driver still in `SCHEDULED` or `DRIVER_EN_ROUTE`, clearing the
    # assigned driver and locking the trip's safety posture." The recomputation
    # leaves the seat count at its covered value here, because `SUSPENDED` is
    # itself one of the lifecycle statuses the approved-seat rule counts as
    # qualifying.
    driver["status"] = "SUSPENDED"
    calc.recompute_driver(driver)
    db.bump_version(driver)
    for trip in db.all_of("trips"):
        if trip.get("driver_id") != driver["id"]:
            continue
        if trip["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
            continue
        trip["trip_state"] = "CANCELLED"
        trip["driver_id"] = None
        trip["candidate_driver_id"] = None
        trip["safety_state"] = "LOCKED"
        db.bump_version(trip)
        services.refresh_trip_relations(trip)
    return object_response(models.background_check_out(check))


# --- VehicleInspection transitions ------------------------------------------

def load_inspection(inspection_id):
    inspection = db.get("vehicle_inspections", inspection_id)
    if inspection is None:
        raise not_found("The addressed vehicle inspection does not exist.")
    return inspection


@bp.post("/student-rides/vehicle-inspections/<inspection_id>/attest")
@requires("DistrictAdmin", "PlatformAdmin")
def attest_inspection(inspection_id):
    inspection = load_inspection(inspection_id)
    driver = load_driver(inspection["driver_id"])

    _state_gate(
        inspection["result"], "PENDING",
        "Only a PENDING inspection may be attested as passed.",
        terminal=("PASSED", "FAILED"),
    )
    if parse_date(inspection["expires_on"]) <= clock_date():
        raise ApiError(ERR_CLEARANCE_EXPIRED, "The inspection's expires_on has already lapsed.")
    if int(inspection["seat_count"]) < 1:
        raise ApiError(
            ERR_INSPECTION_SEAT_COUNT,
            "An inspection counting no usable seats cannot support any student.",
        )
    _state_gate(
        driver["status"], "INSPECTION",
        "Attestation is only legal while the driver sits in INSPECTION.",
        terminal=("INACTIVE",),
    )

    inspection["result"] = "PASSED"
    inspection["seat_credit"] = inspection["seat_count"]
    db.bump_version(inspection)

    calc.recompute_driver(driver)
    driver["status"] = "ACTIVE"
    db.bump_version(driver)
    return object_response(models.vehicle_inspection_out(inspection))


@bp.post("/student-rides/vehicle-inspections/<inspection_id>/reject")
@requires("DistrictAdmin", "PlatformAdmin")
def reject_inspection(inspection_id):
    inspection = load_inspection(inspection_id)
    driver = load_driver(inspection["driver_id"])

    _state_gate(
        inspection["result"], ("PENDING", "PASSED"),
        "Only a PENDING or PASSED inspection may be rejected.",
        terminal=("FAILED",),
    )

    revoked_attestation = inspection["result"] == "PASSED"
    inspection["result"] = "FAILED"
    inspection["seat_credit"] = 0
    db.bump_version(inspection)

    if revoked_attestation:
        driver["status"] = "SUSPENDED"
        calc.recompute_driver(driver)
        db.bump_version(driver)
        for trip in db.all_of("trips"):
            if trip.get("driver_id") != driver["id"]:
                continue
            if trip["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
                continue
            trip["trip_state"] = "CANCELLED"
            trip["driver_id"] = None
            trip["candidate_driver_id"] = None
            trip["safety_state"] = "LOCKED"
            db.bump_version(trip)
            services.refresh_trip_relations(trip)
    else:
        calc.recompute_driver(driver)
        db.bump_version(driver)
    return object_response(models.vehicle_inspection_out(inspection))
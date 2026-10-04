"""Rental agreement endpoints."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_AGREEMENT_FROZEN, E_DRIVER_VEHICLE_CONFLICT, E_ENROLLMENT_NOT_ACTIVE,
                    E_INVALID_REQUEST, E_INVALID_STATE, E_RECOVERY_ALREADY_CLOSED,
                    E_REFERENCED_ENTITY_NOT_FOUND, E_VEHICLE_INTERVAL_OVERLAP, raise_error)
from middleware import check_schema, is_bool, is_int, is_str
from middleware import body as get_body
from response import ok, ok_list
from services import (OCCUPANCY_HOLDING, all_of, by_created, check_agreement_version,
                      driver_holds_vehicle, ensure_activity_permitted, ensure_driver_eligible, ensure_driver_licence,
                      ensure_enrollment_active,
                      ensure_no_week_overlap, ensure_vehicle_available, get_agreement,
                      get_enrollment, get_vehicle, interval_collides, paginate,
                      recompute_equity_credit, recompute_posture, refresh_open_week_charge)

bp = Blueprint("agreements", __name__)

POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


def _cents(value, field):
    if not is_int(value) or value < 0:
        raise_error(E_INVALID_REQUEST, "%s must be a non-negative integer." % field)
    return value


@bp.post("/program/agreements")
def create_agreement():
    payload = get_body()
    check_schema(payload, "POST", "/program/agreements")
    enrollment_id = payload["enrollment_id"]
    driver_id = payload["driver_id"]
    vehicle_id = payload["vehicle_id"]

    if enrollment_id not in db.ENROLLMENTS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "enrollment_id does not name an enrolment.")
    if driver_id not in db.DRIVERS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "driver_id does not name a driver.")
    if vehicle_id not in db.VEHICLES:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "vehicle_id does not name a vehicle.")

    enrollment = db.ENROLLMENTS[enrollment_id]
    driver = db.DRIVERS[driver_id]
    vehicle = db.VEHICLES[vehicle_id]

    rate = _cents(payload["weekly_rate_cents"], "weekly_rate_cents")
    premium = _cents(payload["insurance_premium_cents"], "insurance_premium_cents")
    allowance = _cents(payload["maintenance_allowance_miles"], "maintenance_allowance_miles")
    unlimited = payload.get("unlimited_mileage", False)
    if not is_bool(unlimited):
        raise_error(E_INVALID_REQUEST, "unlimited_mileage must be a boolean.")
    cap = payload.get("mileage_cap_miles")
    if unlimited:
        if cap is not None and not (is_int(cap) and cap >= 0):
            raise_error(E_INVALID_REQUEST, "mileage_cap_miles must be a non-negative integer.")
    else:
        if not is_int(cap) or cap < 0:
            raise_error(E_INVALID_REQUEST,
                        "mileage_cap_miles is required when the agreement is metered.")
    start = db.parse_iso(payload["period_start"])
    end = db.parse_iso(payload["period_end"])
    if start is None or end is None:
        raise_error(E_INVALID_REQUEST, "period_start and period_end must be ISO 8601 instants.")
    if end <= start:
        raise_error(E_INVALID_REQUEST, "period_end must fall after period_start.")

    ensure_driver_licence(driver)
    if driver_holds_vehicle(driver_id):
        raise_error(E_DRIVER_VEHICLE_CONFLICT, "The driver already holds a program vehicle.")
    ensure_vehicle_available(vehicle)
    ensure_activity_permitted(vehicle)
    if interval_collides(vehicle_id, start, end):
        raise_error(E_VEHICLE_INTERVAL_OVERLAP,
                    "The requested interval collides with an existing occupancy interval.")

    row = {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "weekly_rate_cents": rate,
        "insurance_premium_cents": premium,
        "unlimited_mileage": unlimited,
        "mileage_cap_miles": None if unlimited else cap,
        "maintenance_allowance_miles": allowance,
        "compliance_posture": "OPEN",
        "agreement_status": "DRAFT",
        "current_week_number": 0,
        "total_billed_cents": 0,
        "total_waived_cents": 0,
        "period_start": start,
        "period_end": end,
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.AGREEMENTS[row["id"]] = row
    return ok(svc.agreement_out(row), 201)


@bp.get("/program/agreements")
def list_agreements():
    rows = by_created(db.AGREEMENTS.values())
    for key in ("enrollment_id", "driver_id", "vehicle_id", "agreement_status",
                "compliance_posture"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.agreement_out(r) for r in page], limit, offset, total)


@bp.get("/program/agreements/<agreement_id>")
def get_one_agreement(agreement_id):
    return ok(svc.agreement_out(get_agreement(agreement_id)))


@bp.get("/program/agreements/<agreement_id>/summary")
def agreement_summary(agreement_id):
    agreement = get_agreement(agreement_id)
    renewal_credit = 0
    settled_weeks = {w["id"] for w in svc.weeks_of(agreement["id"])
                     if w["week_status"] in ("PAID", "RECOVERED", "WAIVED")}
    for payment in db.PAYMENTS.values():
        if payment["agreement_id"] != agreement["id"]:
            continue
        if payment["payment_outcome"] != "SUCCEEDED":
            continue
        if payment["week_id"] not in settled_weeks:
            continue
        renewal_credit += payment["coverage_cents"]
    options = all_of(db.PURCHASE_OPTIONS, lambda o: o["agreement_id"] == agreement["id"])
    # the reads report the live reading off the settled weeks; the option rows
    # carry whatever was last written onto them
    equity = svc.equity_credit_for(agreement)
    escrow = max((o["escrow_balance_cents"] for o in options), default=0)
    return ok({
        "agreement_id": agreement["id"],
        "agreement_status": agreement["agreement_status"],
        "compliance_posture": agreement["compliance_posture"],
        "current_week_number": agreement["current_week_number"],
        "outstanding_delinquent_weeks": svc.outstanding_delinquent_weeks(agreement["id"]),
        "renewal_credit_cents": renewal_credit,
        "total_billed_cents": agreement["total_billed_cents"],
        "total_waived_cents": agreement["total_waived_cents"],
        "equity_credit_cents": equity,
        "escrow_balance_cents": escrow,
    })


@bp.post("/program/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    if agreement["agreement_status"] != "DRAFT":
        raise_error(E_INVALID_STATE, "Only a DRAFT agreement may be activated.")
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
        raise_error(E_ENROLLMENT_NOT_ACTIVE, "The authorising enrolment is not ACTIVE.")
    driver = db.DRIVERS[agreement["driver_id"]]
    ensure_driver_eligible(driver)
    ensure_driver_licence(driver)
    vehicle = get_vehicle(agreement["vehicle_id"])
    if driver_holds_vehicle(agreement["driver_id"]):
        raise_error(E_DRIVER_VEHICLE_CONFLICT, "The driver already holds a program vehicle.")
    ensure_vehicle_available(vehicle)
    ensure_activity_permitted(vehicle)

    vehicle["vehicle_status"] = "ASSIGNED"
    vehicle["assigned_driver_id"] = agreement["driver_id"]
    vehicle["baseline_odometer_miles"] = vehicle["odometer_miles"]
    db.touch(vehicle)

    agreement["agreement_status"] = "ACTIVE"
    agreement["compliance_posture"] = "OPEN"
    agreement["current_week_number"] = 0
    db.touch(agreement)
    return ok(svc.agreement_out(agreement))


@bp.post("/program/agreements/<agreement_id>/swap")
def swap_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    payload = get_body()
    check_schema(payload, "POST", "/program/agreements/{id}/swap")
    new_vehicle_id = payload["new_vehicle_id"]
    if new_vehicle_id not in db.VEHICLES:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "new_vehicle_id does not name a vehicle.")
    if agreement["agreement_status"] not in OCCUPANCY_HOLDING:
        raise_error(E_INVALID_STATE, "Only a live agreement may be swapped onto another unit.")
    new_vehicle = db.VEHICLES[new_vehicle_id]
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    ensure_vehicle_available(new_vehicle)
    ensure_activity_permitted(new_vehicle)
    start = db.parse_iso(agreement["period_start"])
    end = db.parse_iso(agreement["period_end"])
    # guard 18 (week ordinal) is evaluated before guard 20 (occupancy overlap)
    ensure_no_week_overlap(agreement)
    if interval_collides(new_vehicle_id, start, end, ignore_agreement_id=agreement["id"]):
        raise_error(E_VEHICLE_INTERVAL_OVERLAP,
                    "The replacement unit already has a colliding occupancy interval.")

    old_vehicle = db.VEHICLES.get(agreement["vehicle_id"])
    if old_vehicle is not None and old_vehicle["id"] != new_vehicle_id:
        old_vehicle["vehicle_status"] = "AVAILABLE"
        old_vehicle["assigned_driver_id"] = None
        db.touch(old_vehicle)

    new_vehicle["vehicle_status"] = "ASSIGNED"
    new_vehicle["assigned_driver_id"] = agreement["driver_id"]
    new_vehicle["baseline_odometer_miles"] = new_vehicle["odometer_miles"]
    db.touch(new_vehicle)

    agreement["vehicle_id"] = new_vehicle_id
    db.touch(agreement)
    return ok(svc.agreement_out(agreement))


@bp.post("/program/agreements/<agreement_id>/complete")
def complete_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")
    if agreement["agreement_status"] != "ACTIVE":
        raise_error(E_INVALID_STATE, "Only an ACTIVE agreement may be completed.")
    for week in svc.weeks_of(agreement["id"]):
        if week["week_status"] in svc.DELINQUENT_BLOCKING:
            raise_error(E_INVALID_STATE,
                        "A week of the agreement has money outstanding and uncollected.")
    for option in all_of(db.PURCHASE_OPTIONS, lambda o: o["agreement_id"] == agreement["id"]):
        if option["option_status"] == "ELECTED":
            raise_error(E_INVALID_STATE, "A purchase option on the agreement is ELECTED.")

    vehicle = db.VEHICLES.get(agreement["vehicle_id"])
    if vehicle is not None:
        vehicle["vehicle_status"] = "AVAILABLE"
        vehicle["assigned_driver_id"] = None
        vehicle["returned_to_available_at"] = db.now()
        db.touch(vehicle)
    agreement["agreement_status"] = "COMPLETED"
    db.touch(agreement)
    return ok(svc.agreement_out(agreement))


@bp.post("/program/agreements/<agreement_id>/escalate-recovery")
def escalate_recovery(agreement_id):
    agreement = get_agreement(agreement_id)
    if agreement["agreement_status"] != "DELINQUENT":
        raise_error(E_INVALID_STATE, "Only a DELINQUENT agreement may be escalated.")
    if agreement["compliance_posture"] != "FROZEN":
        raise_error(E_INVALID_STATE, "The agreement's posture is not FROZEN.")
    if svc.outstanding_delinquent_weeks(agreement["id"]) < 2:
        raise_error(E_INVALID_STATE, "Fewer than two delinquent weeks are outstanding.")
    agreement["agreement_status"] = "RECOVERY_PENDING"
    db.touch(agreement)
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    if enrollment is not None:
        blocking = any(a["agreement_status"] in OCCUPANCY_HOLDING
                       for a in all_of(db.AGREEMENTS,
                                       lambda a: a["enrollment_id"] == enrollment["id"]))
        if not blocking and enrollment["enrollment_status"] != "WITHDRAWN":
            enrollment["enrollment_status"] = "WITHDRAWN"
            db.touch(enrollment)
    return ok(svc.agreement_out(agreement))


@bp.post("/program/agreements/<agreement_id>/recover")
def recover_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    # the recovered-week set is inspected before the lifecycle state, so a
    # replay of an already-executed recovery is reported as a closed set
    delinquent = [w for w in svc.weeks_of(agreement["id"]) if w["week_status"] == "DELINQUENT"]
    if not delinquent and agreement["agreement_status"] != "RECOVERY_PENDING":
        raise_error(E_RECOVERY_ALREADY_CLOSED,
                    "The agreement's recovered-week set is already closed.")
    if agreement["agreement_status"] != "RECOVERY_PENDING":
        raise_error(E_INVALID_STATE, "Only a RECOVERY_PENDING agreement may be recovered.")
    vehicle = get_vehicle(agreement["vehicle_id"])
    if vehicle["vehicle_status"] != "RECOVERY":
        raise_error(E_INVALID_STATE, "The unit is not in the recovery pool.")
    if not delinquent:
        raise_error(E_RECOVERY_ALREADY_CLOSED,
                    "The agreement's recovered-week set is already closed.")

    vehicle["vehicle_status"] = "AVAILABLE"
    vehicle["assigned_driver_id"] = None
    vehicle["returned_to_available_at"] = db.now()
    db.touch(vehicle)
    for week in delinquent:
        week["week_status"] = "RECOVERED"
        db.touch(week)
    agreement["agreement_status"] = "RECOVERED"
    db.touch(agreement)
    # the recovered-week set is closed, so the posture reading falls back and the
    # freeze it produced is unwound with it
    svc.recompute_posture(agreement)
    return ok(svc.agreement_out(agreement))
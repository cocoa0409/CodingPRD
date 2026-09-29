"""Plate lots and the steel ledger (PRD 3.3); shell courses (PRD 3.4)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import ALL_ROLES, ERECTION_SUPERINTENDENT, PROJECT_ENGINEER, endpoint
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import PLATE_LOTS, SHELL_COURSES, TANKS, new_row, touch
from util import D, now_logical, q

bp = Blueprint("plate", __name__)

LOT_STATUSES = ("ORDERED", "ROLLED", "SHIPPED", "RECEIVED", "QUARANTINED",
                "RELEASED")
LOT_TRANSITIONS = {
    "ORDERED": ("ROLLED",),
    "ROLLED": ("SHIPPED",),
    "SHIPPED": ("RECEIVED",),
    "RECEIVED": ("QUARANTINED", "RELEASED"),
    "QUARANTINED": ("RELEASED",),
    "RELEASED": (),
}


@bp.post("/plate-lots")
@endpoint((ERECTION_SUPERINTENDENT,))
def create_lot():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    mill_name = v.s_str(body, "mill_name", required=True)
    heat_number = v.s_str(body, "heat_number", required=True)
    thickness_in = v.s_num(body, "thickness_in", required=True, gt=0)
    plate_count = v.s_int(body, "plate_count", required=True, ge=1)
    plate_weight_lb = v.s_num(body, "plate_weight_lb", required=True, gt=0)
    unit_cost = v.s_num(body, "unit_cost_usd_per_lb", required=True, gt=0)
    mtr_number = v.s_str(body, "mtr_number", required=False)

    tank = common.get_tank(tank_id)

    lot = new_row({
        "tank_id": tank["id"],
        "mill_name": mill_name,
        "heat_number": heat_number,
        "thickness_in": thickness_in,
        "plate_count": plate_count,
        "plate_weight_lb": plate_weight_lb,
        "unit_cost_usd_per_lb": unit_cost,
        "mtr_number": mtr_number,
        "received_weight_lb": 0.0,
        "allocated_weight_lb": 0.0,
        "remaining_weight_lb": 0.0,
        "status": "ORDERED",
        "quarantine_reason": None,
    })
    PLATE_LOTS[lot["id"]] = lot
    return object_response(lot, 201)


@bp.get("/plate-lots")
@endpoint(ALL_ROLES)
def list_lots():
    filters = query_filters("tank_id", "status", "heat_number")
    rows, limit, offset, total = paged(PLATE_LOTS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/plate-lots/<plate_lot_id>")
@endpoint(ALL_ROLES)
def read_lot(plate_lot_id):
    return object_response(common.get_plate_lot(plate_lot_id))


@bp.post("/plate-lots/<plate_lot_id>/status-transitions")
@endpoint((ERECTION_SUPERINTENDENT,))
def transition_lot(plate_lot_id):
    lot = common.get_plate_lot(plate_lot_id)
    target = v.s_enum(g.body, "target_status", LOT_STATUSES, required=True)
    mtr_number = v.s_str(g.body, "mtr_number", required=False)
    quarantine_reason = v.s_str(g.body, "quarantine_reason", required=False)
    remarks = v.s_str(g.body, "remarks", required=False)

    current = lot["status"]
    if target not in LOT_TRANSITIONS.get(current, ()):
        raise ApiError(errors.ERR_PLATE_LOT_STATE_INVALID, 409,
                       "A plate lot in %s may not move to %s." % (current, target))
    if target == "RECEIVED" and mtr_number is None:
        raise ApiError(errors.ERR_PLATE_LOT_STATE_INVALID, 409,
                       "Reaching RECEIVED requires mtr_number in the body.")
    if target == "RELEASED" and current == "QUARANTINED" and mtr_number is None:
        raise ApiError(errors.ERR_PLATE_LOT_STATE_INVALID, 409,
                       "Releasing a quarantined lot requires the corrected "
                       "mtr_number in the body.")
    if target == "RELEASED" and current == "RECEIVED" and lot["mtr_number"] is None:
        raise ApiError(errors.ERR_PLATE_LOT_STATE_INVALID, 409,
                       "The lot has no material test report number.")
    if target == "QUARANTINED" and D(lot["allocated_weight_lb"]) != 0:
        raise ApiError(errors.ERR_PLATE_LOT_STATE_INVALID, 409,
                       "A lot holding allocations may not be quarantined.")

    tank = TANKS.get(lot["tank_id"])
    if target == "RECEIVED":
        lot["mtr_number"] = mtr_number
        weight = q(D(lot["plate_count"]) * D(lot["plate_weight_lb"]), 2)
        lot["received_weight_lb"] = weight
        lot["remaining_weight_lb"] = weight
    if target == "RELEASED" and current == "QUARANTINED":
        lot["mtr_number"] = mtr_number
    if target == "QUARANTINED":
        lot["quarantine_reason"] = (quarantine_reason if quarantine_reason
                                    is not None else remarks)
    lot["status"] = target
    touch(lot)
    derive.rederive_steel_ledger(tank)
    return object_response(lot)


@bp.post("/plate-lots/<plate_lot_id>/allocations")
@endpoint((ERECTION_SUPERINTENDENT,))
def allocate_lot(plate_lot_id):
    lot = common.get_plate_lot(plate_lot_id)
    course_id = v.s_str(g.body, "shell_course_id", required=True)
    weight = v.s_num(g.body, "allocated_weight_lb", required=True, ge=0)
    course = common.get_shell_course(course_id)
    tank = TANKS.get(lot["tank_id"])

    if lot["status"] not in ("RECEIVED", "RELEASED"):
        raise ApiError(errors.ERR_ALLOCATION_STATE_INVALID, 409,
                       "Only a RECEIVED or RELEASED lot may be allocated.")
    if course["allocation_status"] != "UNALLOCATED":
        raise ApiError(errors.ERR_ALLOCATION_STATE_INVALID, 409,
                       "The shell course already holds an allocation.")
    common.require_not_frozen(tank)
    if course["tank_id"] != lot["tank_id"]:
        raise common.cross_tank("The shell course belongs to another tank.")
    if D(weight) > D(lot["remaining_weight_lb"]):
        raise ApiError(errors.ERR_PLATE_WEIGHT_EXCEEDED, 409,
                       "The requested weight exceeds the lot's remaining weight.")

    course["allocated_plate_lot_id"] = lot["id"]
    course["allocated_weight_lb"] = q(weight, 2)
    course["allocation_status"] = "ALLOCATED"
    touch(course)
    derive.rederive_steel_ledger(tank)
    return object_response(course)


@bp.post("/shell-courses")
@endpoint((PROJECT_ENGINEER,))
def create_course():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    course_number = v.s_int(body, "course_number", required=True, ge=1)
    course_width_ft = v.s_num(body, "course_width_ft", required=True, gt=0)
    plate_thickness_in = v.s_num(body, "plate_thickness_in", required=True, gt=0)
    material_spec = v.s_str(body, "material_spec", required=True)
    stress_design = v.s_num(body, "allowable_stress_design_psi", required=True,
                            gt=0)
    stress_test = v.s_num(body, "allowable_stress_test_psi", required=True, gt=0)

    tank = common.get_tank(tank_id)

    for other in derive.courses_of_tank(tank["id"]):
        if int(other["course_number"]) == course_number:
            raise common.duplicate("course_number must be unique within a tank.")

    course = new_row({
        "tank_id": tank["id"],
        "course_number": course_number,
        "course_width_ft": course_width_ft,
        "plate_thickness_in": plate_thickness_in,
        "material_spec": material_spec,
        "allowable_stress_design_psi": stress_design,
        "allowable_stress_test_psi": stress_test,
        "course_bottom_elevation_ft": 0.0,
        "design_liquid_height_ft": 0.0,
        "required_thickness_design_in": 0.0,
        "required_thickness_test_in": 0.0,
        "required_thickness_in": 0.0,
        "governing_case": "MIN_NOMINAL",
        "thickness_verdict": "ADEQUATE",
        "allocated_plate_lot_id": None,
        "allocated_weight_lb": 0.0,
        "allocation_status": "UNALLOCATED",
        "status": "SPECIFIED",
        "fitup_at_utc": None,
    })
    SHELL_COURSES[course["id"]] = course
    derive.compute_course_thickness(course, tank)
    course["version"] = 1
    # PRD 3.4: adding a lower course re-evaluates the stack above it.
    derive.recompute_tank_courses(tank)
    return object_response(course, 201)


@bp.get("/shell-courses")
@endpoint(ALL_ROLES)
def list_courses():
    filters = query_filters("tank_id", "allocated_plate_lot_id", "status",
                            "allocation_status", "thickness_verdict")
    rows, limit, offset, total = paged(SHELL_COURSES.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/shell-courses/<shell_course_id>")
@endpoint(ALL_ROLES)
def read_course(shell_course_id):
    return object_response(common.get_shell_course(shell_course_id))


@bp.post("/shell-courses/<shell_course_id>/allocation-release")
@endpoint((ERECTION_SUPERINTENDENT,))
def release_allocation(shell_course_id):
    course = common.get_shell_course(shell_course_id)
    v.s_str(g.body, "reason", required=True)
    tank = TANKS.get(course["tank_id"])

    if (course["allocation_status"] != "ALLOCATED"
            or course["allocated_plate_lot_id"] is None
            or course["status"] != "SPECIFIED"):
        raise ApiError(errors.ERR_ALLOCATION_STATE_INVALID, 409,
                       "Only an unfitted course holding an allocation may be "
                       "released.")

    course["allocated_plate_lot_id"] = None
    course["allocated_weight_lb"] = 0.0
    course["allocation_status"] = "UNALLOCATED"
    touch(course)
    derive.rederive_steel_ledger(tank)
    return object_response(course)


@bp.post("/shell-courses/<shell_course_id>/fitup")
@endpoint((ERECTION_SUPERINTENDENT,))
def fitup_course(shell_course_id):
    course = common.get_shell_course(shell_course_id)
    tank = TANKS.get(course["tank_id"])

    if course["status"] != "SPECIFIED":
        raise ApiError(errors.ERR_COURSE_STATE_INVALID, 409,
                       "The course has already been fitted up.")
    if tank["construction_phase"] not in ("FOUNDATION_ACCEPTED",
                                          "ERECTION_IN_PROGRESS"):
        raise ApiError(errors.ERR_COURSE_STATE_INVALID, 409,
                       "The tank's construction phase does not permit fit-up.")
    common.require_not_frozen(tank)
    package = derive.package_of_tank(tank["id"])
    if package is None or package["status"] != "ACCEPTED":
        raise ApiError(errors.ERR_FOUNDATION_NOT_ACCEPTED, 409,
                       "The tank's foundation package is not ACCEPTED.")
    if course["thickness_verdict"] != "ADEQUATE":
        raise ApiError(errors.ERR_COURSE_THICKNESS_DEFICIENT, 409,
                       "The ordered plate is thinner than the governing "
                       "requirement.")

    course["status"] = "FITTED"
    course["fitup_at_utc"] = now_logical()
    touch(course)
    if tank["construction_phase"] == "FOUNDATION_ACCEPTED":
        tank["construction_phase"] = "ERECTION_IN_PROGRESS"
        touch(tank)
    return object_response(course)

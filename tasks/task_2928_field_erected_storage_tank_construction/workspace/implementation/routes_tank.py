"""Logical clock (PRD 2.4) and tanks (PRD 3.1)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import ALL_ROLES, PROJECT_ENGINEER
from auth import endpoint
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import TANKS, new_row, touch
from util import now_logical, set_logical

bp = Blueprint("tank", __name__)

DESIGN_STANDARDS = ("API_650_BASIC", "API_650_ANNEX_A", "API_620")
ROOF_TYPES = ("CONE_SUPPORTED", "CONE_SELF_SUPPORTING", "DOME_SELF_SUPPORTING",
              "EXTERNAL_FLOATING", "INTERNAL_FLOATING")
JOINT_EFFICIENCIES = (0.70, 0.85, 1.00)
CONSTRUCTION_PHASES = ("DESIGN_REGISTERED", "FOUNDATION_ACCEPTED",
                       "ERECTION_IN_PROGRESS", "SHELL_COMPLETE",
                       "HYDROTEST_PASSED", "COATED", "COMMISSIONED")


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_clock():
    moment = v.s_dt(g.body, "to_iso8601", required=True)
    set_logical(moment)
    return object_response({"current_utc": now_logical()})


@bp.post("/tanks")
@endpoint((PROJECT_ENGINEER,))
def create_tank():
    body = g.body
    tank_tag = v.s_str(body, "tank_tag", required=True, min_len=1, max_len=32)
    design_standard = v.s_enum(body, "design_standard", DESIGN_STANDARDS,
                               required=False, default="API_650_BASIC")
    diameter_ft = v.s_num(body, "diameter_ft", required=True, gt=0)
    shell_height_ft = v.s_num(body, "shell_height_ft", required=True, gt=0)
    design_liquid_level_ft = v.s_num(body, "design_liquid_level_ft",
                                     required=True, gt=0)
    if design_liquid_level_ft > shell_height_ft:
        v.bad("design_liquid_level_ft may not exceed shell_height_ft.")
    specific_gravity = v.s_num(body, "product_specific_gravity", required=True,
                               ge=0.5, le=2.0)
    joint_efficiency = v.s_num_enum(body, "joint_efficiency",
                                    JOINT_EFFICIENCIES, required=True)
    corrosion_allowance_in = v.s_num(body, "corrosion_allowance_in",
                                     required=False, default=0.0625, ge=0)
    roof_type = v.s_enum(body, "roof_type", ROOF_TYPES, required=False,
                         default="CONE_SUPPORTED")
    bottom_thickness_in = v.s_num(body, "bottom_thickness_in", required=True,
                                  gt=0)
    bottom_minimum_thickness_in = v.s_num(body, "bottom_minimum_thickness_in",
                                          required=True, gt=0)
    if bottom_minimum_thickness_in >= bottom_thickness_in:
        v.bad("bottom_minimum_thickness_in must be strictly less than "
              "bottom_thickness_in.")
    corrosion_rate = v.s_num(body, "assumed_corrosion_rate_ipy", required=True,
                             gt=0)

    for row in TANKS.values():
        if row["tank_tag"] == tank_tag:
            raise common.duplicate("tank_tag must be unique across every tank.")

    tank = new_row({
        "tank_tag": tank_tag,
        "design_standard": design_standard,
        "diameter_ft": diameter_ft,
        "shell_height_ft": shell_height_ft,
        "design_liquid_level_ft": design_liquid_level_ft,
        "product_specific_gravity": specific_gravity,
        "joint_efficiency": joint_efficiency,
        "corrosion_allowance_in": corrosion_allowance_in,
        "roof_type": roof_type,
        "bottom_thickness_in": bottom_thickness_in,
        "bottom_minimum_thickness_in": bottom_minimum_thickness_in,
        "assumed_corrosion_rate_ipy": corrosion_rate,
        "min_nominal_thickness_in": derive.min_nominal_thickness(diameter_ft),
        "construction_phase": "DESIGN_REGISTERED",
        "quality_posture": "OPEN",
        "open_nonconformance_count": 0,
        "weld_reject_rate": 0.0,
        "required_examination_pct": 10.0,
        "steel_received_lb": 0.0,
        "steel_allocated_lb": 0.0,
        "active_hydrotest_plan_id": None,
    })
    TANKS[tank["id"]] = tank
    return object_response(tank, 201)


@bp.get("/tanks")
@endpoint(ALL_ROLES)
def list_tanks():
    filters = query_filters("tank_tag", "construction_phase", "quality_posture")
    rows, limit, offset, total = paged(TANKS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/tanks/<tank_id>")
@endpoint(ALL_ROLES)
def read_tank(tank_id):
    return object_response(common.get_tank(tank_id))


@bp.get("/tanks/<tank_id>/summary")
@endpoint(ALL_ROLES)
def read_tank_summary(tank_id):
    tank = common.get_tank(tank_id)
    return object_response(derive.tank_summary(tank))


@bp.post("/tanks/<tank_id>/phase-transitions")
@endpoint((PROJECT_ENGINEER,))
def phase_transition(tank_id):
    tank = common.get_tank(tank_id)
    target = v.s_enum(g.body, "target_phase", CONSTRUCTION_PHASES,
                      required=True)
    v.s_str(g.body, "remarks", required=False)

    # PRD 2.7: exactly one transition is requestable by an operator.
    if target != "SHELL_COMPLETE" or tank["construction_phase"] != "ERECTION_IN_PROGRESS":
        raise ApiError(errors.ERR_PHASE_TRANSITION_INVALID, 409,
                       "That construction_phase transition is not requestable.")
    courses = derive.courses_of_tank(tank["id"])
    if not courses or any(c["status"] != "RT_ACCEPTED" for c in courses):
        raise ApiError(errors.ERR_PHASE_TRANSITION_INVALID, 409,
                       "Every shell course of the tank must be RT_ACCEPTED.")
    common.require_not_frozen(tank)

    tank["construction_phase"] = "SHELL_COMPLETE"
    touch(tank)
    return object_response(tank)

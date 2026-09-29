"""Foundation packages and settlement surveys (PRD 3.2)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import ALL_ROLES, CIVIL_CONTRACTOR, PROJECT_ENGINEER, acting_user
from auth import endpoint
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import (FOUNDATION_PACKAGES, SETTLEMENT_SURVEYS, TANKS, new_row,
                   touch)
from util import now_logical

bp = Blueprint("foundation", __name__)

FOUNDATION_TYPES = ("RINGWALL_CONCRETE", "CRUSHED_STONE_RINGWALL",
                    "EARTHEN_PAD", "SLAB")
EVALUATION_METHODS = ("COSINE_BEST_FIT", "ADJACENT_PAIR")
DECISIONS = ("ACCEPT", "REJECT")


@bp.post("/foundation-packages")
@endpoint((CIVIL_CONTRACTOR,))
def create_package():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    foundation_type = v.s_enum(body, "foundation_type", FOUNDATION_TYPES,
                               required=True)
    ringwall = v.s_num(body, "ringwall_top_elevation_ft", required=False,
                       default=0.0)
    method = v.s_enum(body, "settlement_evaluation_method", EVALUATION_METHODS,
                      required=True)
    uniform = v.s_num(body, "permitted_uniform_settlement_in", required=True,
                      gt=0)
    ratio = v.s_num(body, "permitted_differential_ratio", required=True, gt=0,
                    le=0.05)
    points = v.s_int(body, "monitoring_point_count", required=True, ge=8)
    if points % 2 != 0:
        v.bad("monitoring_point_count must be an even number.")

    tank = common.get_tank(tank_id)

    if derive.package_of_tank(tank["id"]) is not None:
        raise ApiError(errors.ERR_SINGLETON_EXISTS, 409,
                       "This tank already has a foundation package.")

    package = new_row({
        "tank_id": tank["id"],
        "foundation_type": foundation_type,
        "ringwall_top_elevation_ft": ringwall,
        "settlement_evaluation_method": method,
        "permitted_uniform_settlement_in": uniform,
        "permitted_differential_ratio": ratio,
        "monitoring_point_count": points,
        "point_spacing_in": 0.0,
        "allowable_differential_in": 0.0,
        "baseline_survey_id": None,
        "status": "PLANNED",
        "decided_by_user_id": None,
        "decided_at_utc": None,
        "decision_remarks": None,
    })
    derive.settlement_envelope(package, tank)
    FOUNDATION_PACKAGES[package["id"]] = package
    return object_response(package, 201)


@bp.get("/foundation-packages")
@endpoint(ALL_ROLES)
def list_packages():
    filters = query_filters("tank_id", "status", "foundation_type")
    rows, limit, offset, total = paged(FOUNDATION_PACKAGES.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/foundation-packages/<foundation_package_id>")
@endpoint(ALL_ROLES)
def read_package(foundation_package_id):
    return object_response(common.get_foundation_package(foundation_package_id))


@bp.post("/foundation-packages/<foundation_package_id>/acceptance")
@endpoint((PROJECT_ENGINEER,))
def decide_package(foundation_package_id):
    package = common.get_foundation_package(foundation_package_id)
    decision = v.s_enum(g.body, "decision", DECISIONS, required=True)
    remarks = v.s_str(g.body, "decision_remarks", required=False)
    tank = TANKS.get(package["tank_id"])

    if package["status"] != "BASELINE_SET" or package["baseline_survey_id"] is None:
        raise ApiError(errors.ERR_FOUNDATION_STATE_INVALID, 409,
                       "The package must be BASELINE_SET with a baseline survey.")
    common.require_not_frozen(tank)

    package["decided_by_user_id"] = acting_user()
    package["decided_at_utc"] = now_logical()
    package["decision_remarks"] = remarks
    if decision == "ACCEPT":
        package["status"] = "ACCEPTED"
        touch(package)
        if tank["construction_phase"] == "DESIGN_REGISTERED":
            tank["construction_phase"] = "FOUNDATION_ACCEPTED"
            touch(tank)
    else:
        package["status"] = "REJECTED"
        package["baseline_survey_id"] = None
        touch(package)
    return object_response(package)


@bp.post("/settlement-surveys")
@endpoint((CIVIL_CONTRACTOR,))
def create_survey():
    body = g.body
    package_id = v.s_str(body, "foundation_package_id", required=True)
    plan_id = v.s_str(body, "hydrotest_plan_id", required=False)
    fill_percent = v.s_num(body, "fill_percent", required=True, ge=0, le=100)
    measured_at = v.s_dt(body, "measured_at_utc", required=False)
    readings = v.s_point_readings(body, "point_readings")

    package = common.get_foundation_package(package_id)
    plan = common.get_hydrotest_plan(plan_id) if plan_id is not None else None
    tank = TANKS.get(package["tank_id"])

    is_baseline = package["baseline_survey_id"] is None
    if is_baseline and fill_percent != 0:
        # PRD 3.2: a monitoring survey submitted before a baseline exists.
        raise ApiError(errors.ERR_FOUNDATION_STATE_INVALID, 409,
                       "This package has no baseline survey yet.")

    if plan is not None and plan["tank_id"] != package["tank_id"]:
        raise common.cross_tank("The hydrotest plan belongs to another tank.")

    count = int(package["monitoring_point_count"])
    indexes = sorted(int(r["point_index"]) for r in readings)
    if len(readings) != count or indexes != list(range(1, count + 1)):
        raise ApiError(errors.ERR_INSUFFICIENT_SURVEY_POINTS, 409,
                       "point_readings must carry every monitoring point "
                       "exactly once.")

    survey = new_row({
        "foundation_package_id": package["id"],
        "hydrotest_plan_id": plan["id"] if plan is not None else None,
        "survey_role": "BASELINE" if is_baseline else "MONITORING",
        "fill_percent": fill_percent,
        "measured_at_utc": measured_at if measured_at is not None else now_logical(),
        "point_readings": readings,
        "uniform_settlement_in": 0.0,
        "max_out_of_plane_in": 0.0,
        "max_adjacent_differential_in": 0.0,
        "governing_metric_in": 0.0,
        "verdict": "BASELINE",
        "nonconformance_state": "NOT_APPLICABLE",
        "superseded_by_survey_id": None,
    })

    if is_baseline:
        SETTLEMENT_SURVEYS[survey["id"]] = survey
        package["baseline_survey_id"] = survey["id"]
        package["status"] = "BASELINE_SET"
        touch(package)
    else:
        baseline = SETTLEMENT_SURVEYS.get(package["baseline_survey_id"])
        derive.evaluate_survey(survey, package, baseline)
        if survey["verdict"] == "OUT_OF_TOLERANCE":
            survey["nonconformance_state"] = "OPEN"
        SETTLEMENT_SURVEYS[survey["id"]] = survey
        derive.close_superseded_surveys(survey, package)

    derive.recompute_posture(tank)
    return object_response(survey, 201)


@bp.get("/settlement-surveys")
@endpoint(ALL_ROLES)
def list_surveys():
    filters = query_filters("foundation_package_id", "hydrotest_plan_id",
                            "survey_role", "verdict", "nonconformance_state")
    rows, limit, offset, total = paged(SETTLEMENT_SURVEYS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/settlement-surveys/<settlement_survey_id>")
@endpoint(ALL_ROLES)
def read_survey(settlement_survey_id):
    return object_response(common.get_settlement_survey(settlement_survey_id))

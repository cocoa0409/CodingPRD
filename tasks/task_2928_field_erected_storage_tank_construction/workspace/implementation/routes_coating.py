"""Coating, lining and the rework cascade (PRD 3.8)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import ALL_ROLES, PROJECT_ENGINEER, QC_INSPECTOR, endpoint
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import COATING_APPLICATIONS, TANKS, new_row, touch
from util import D

bp = Blueprint("coating", __name__)

SCOPES = ("INTERNAL_LINING", "EXTERNAL_COATING")
SPECIFIED_PREP_STANDARDS = ("SSPC_SP5", "SSPC_SP6", "SSPC_SP10")
ACHIEVED_PREP_STANDARDS = ("SSPC_SP3", "SSPC_SP6", "SSPC_SP10", "SSPC_SP5")
DFT_METHODS = ("SPOT_AVERAGE_80_120", "INDIVIDUAL_GAUGE_MIN")


@bp.post("/coating-applications")
@endpoint((PROJECT_ENGINEER,))
def create_application():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    scope = v.s_enum(body, "scope", SCOPES, required=True)
    surface_area = v.s_num(body, "surface_area_sqft", required=True, gt=0)
    prep_standard = v.s_enum(body, "specified_prep_standard",
                             SPECIFIED_PREP_STANDARDS, required=True)
    min_dft = v.s_num(body, "specified_min_dft_mils", required=True, gt=0)
    method = v.s_enum(body, "dft_acceptance_method", DFT_METHODS,
                      required=True)
    coating_system = v.s_str(body, "coating_system", required=True)
    tank = common.get_tank(tank_id)

    application = new_row({
        "tank_id": tank["id"],
        "scope": scope,
        "surface_area_sqft": surface_area,
        "specified_prep_standard": prep_standard,
        "specified_min_dft_mils": min_dft,
        "dft_acceptance_method": method,
        "coating_system": coating_system,
        "achieved_prep_standard": None,
        "profile_mils": None,
        "dew_point_spread_f": None,
        "spot_count": 0,
        "computed_spot_average_min_mils": 0.0,
        "computed_spot_average_max_mils": 0.0,
        "computed_overall_average_mils": 0.0,
        "computed_min_gauge_reading_mils": 0.0,
        "dft_verdict": "NOT_EVALUATED",
        "holidays_found": None,
        "holiday_test_voltage_v": None,
        "rework_cycle_count": 0,
        "status": "SPEC_ISSUED",
    })
    COATING_APPLICATIONS[application["id"]] = application
    return object_response(application, 201)


@bp.get("/coating-applications")
@endpoint(ALL_ROLES)
def list_applications():
    filters = query_filters("tank_id", "scope", "status", "dft_verdict")
    rows, limit, offset, total = paged(COATING_APPLICATIONS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/coating-applications/<coating_application_id>")
@endpoint(ALL_ROLES)
def read_application(coating_application_id):
    return object_response(
        common.get_coating_application(coating_application_id))


@bp.post("/coating-applications/<coating_application_id>/surface-prep")
@endpoint((QC_INSPECTOR,))
def surface_prep(coating_application_id):
    application = common.get_coating_application(coating_application_id)
    achieved = v.s_enum(g.body, "achieved_prep_standard",
                        ACHIEVED_PREP_STANDARDS, required=True)
    profile = v.s_num(g.body, "profile_mils", required=True, ge=0)
    spread = v.s_num(g.body, "dew_point_spread_f", required=True)
    tank = TANKS.get(application["tank_id"])

    if application["status"] not in ("SPEC_ISSUED", "REWORK_REQUIRED"):
        raise ApiError(errors.ERR_COATING_STEP_INVALID, 409,
                       "Surface preparation is not the expected next step.")
    common.require_not_frozen(tank)

    if (derive.prep_rank(achieved)
            < derive.prep_rank(application["specified_prep_standard"])):
        raise ApiError(errors.ERR_SURFACE_PREP_DEFICIENT, 409,
                       "The achieved preparation grade is less clean than the "
                       "specified grade.")
    if D(spread) < D(derive.MIN_DEW_POINT_SPREAD_F):
        raise ApiError(errors.ERR_DEW_POINT_SPREAD_INSUFFICIENT, 409,
                       "The dew-point spread must be at least 5.0 degrees "
                       "Fahrenheit.")

    was_rework = application["status"] == "REWORK_REQUIRED"
    application["achieved_prep_standard"] = achieved
    application["profile_mils"] = profile
    application["dew_point_spread_f"] = spread
    application["status"] = "PREP_ACCEPTED"
    if was_rework:
        application["rework_cycle_count"] = (
            application["rework_cycle_count"] + 1)
        derive.reset_dft_measurements(application)
    touch(application)
    if was_rework and tank is not None:
        derive.recompute_posture(tank)
    return object_response(application)


@bp.post("/coating-applications/<coating_application_id>/dft-readings")
@endpoint((QC_INSPECTOR,))
def dft_readings(coating_application_id):
    application = common.get_coating_application(coating_application_id)
    spot_readings = v.s_spot_readings(g.body, "spot_readings")
    tank = TANKS.get(application["tank_id"])

    if application["status"] != "PREP_ACCEPTED":
        raise ApiError(errors.ERR_COATING_STEP_INVALID, 409,
                       "Dry film thickness readings are not the expected next "
                       "step.")
    common.require_not_frozen(tank)

    derive.evaluate_dft(application, spot_readings)
    application["status"] = "DFT_RECORDED"
    touch(application)
    return object_response(application)


@bp.post("/coating-applications/<coating_application_id>/holiday-test")
@endpoint((QC_INSPECTOR,))
def holiday_test(coating_application_id):
    application = common.get_coating_application(coating_application_id)
    holidays_found = v.s_int(g.body, "holidays_found", required=True, ge=0)
    voltage = v.s_num(g.body, "test_voltage_v", required=True, ge=0)
    tank = TANKS.get(application["tank_id"])

    if application["status"] != "DFT_RECORDED":
        raise ApiError(errors.ERR_COATING_STEP_INVALID, 409,
                       "The holiday test is not the expected next step.")
    common.require_not_frozen(tank)

    if application["scope"] == "INTERNAL_LINING":
        floor = (derive.HOLIDAY_VOLTAGE_FACTOR
                 * D(application["specified_min_dft_mils"]))
        if D(voltage) < floor:
            raise ApiError(errors.ERR_HOLIDAY_TEST_VOLTAGE_LOW, 409,
                           "The holiday test voltage is below the probative "
                           "floor.")
    if holidays_found == 0 and application["dft_verdict"] != "PASS":
        raise ApiError(errors.ERR_DFT_NOT_PASSED, 409,
                       "A failing dry film thickness verdict must be "
                       "reworked.")

    application["holidays_found"] = holidays_found
    application["holiday_test_voltage_v"] = voltage
    if holidays_found == 0:
        application["status"] = "ACCEPTED"
        touch(application)
        if tank is not None:
            derive.maybe_advance_coated(tank)
    else:
        application["status"] = "REWORK_REQUIRED"
        touch(application)
        if tank is not None:
            derive.coating_rework_cascade(tank)
    return object_response(application)

"""Resource resolution (PRD 2.4 not-found mapping) and the posture gates."""

import errors
from errors import ApiError
from store import (
    APPURTENANCES, COATING_APPLICATIONS, COMMISSIONING_PACKAGES,
    FOUNDATION_PACKAGES, HYDROTEST_PLANS, NDE_REPORTS, PLATE_LOTS,
    SETTLEMENT_SURVEYS, SHELL_COURSES, TANKS, WATER_SOURCES,
    WATER_WITHDRAWALS, WELD_SEAMS, WELDERS,
)

_NOT_FOUND = (
    (TANKS, errors.ERR_TANK_NOT_FOUND),
    (FOUNDATION_PACKAGES, errors.ERR_FOUNDATION_PACKAGE_NOT_FOUND),
    (SETTLEMENT_SURVEYS, errors.ERR_SETTLEMENT_SURVEY_NOT_FOUND),
    (PLATE_LOTS, errors.ERR_PLATE_LOT_NOT_FOUND),
    (SHELL_COURSES, errors.ERR_SHELL_COURSE_NOT_FOUND),
    (WELDERS, errors.ERR_WELDER_NOT_FOUND),
    (WELD_SEAMS, errors.ERR_WELD_SEAM_NOT_FOUND),
    (NDE_REPORTS, errors.ERR_NDE_REPORT_NOT_FOUND),
    (WATER_SOURCES, errors.ERR_WATER_SOURCE_NOT_FOUND),
    (HYDROTEST_PLANS, errors.ERR_HYDROTEST_PLAN_NOT_FOUND),
    (WATER_WITHDRAWALS, errors.ERR_WATER_WITHDRAWAL_NOT_FOUND),
    (COATING_APPLICATIONS, errors.ERR_COATING_APPLICATION_NOT_FOUND),
    (APPURTENANCES, errors.ERR_APPURTENANCE_NOT_FOUND),
    (COMMISSIONING_PACKAGES, errors.ERR_COMMISSIONING_PACKAGE_NOT_FOUND),
)


def _resolve(collection, error_id, resource_id):
    row = collection.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError(error_id, 404, "The referenced resource does not exist.")
    return row


def get_tank(resource_id):
    return _resolve(TANKS, errors.ERR_TANK_NOT_FOUND, resource_id)


def get_foundation_package(resource_id):
    return _resolve(FOUNDATION_PACKAGES,
                    errors.ERR_FOUNDATION_PACKAGE_NOT_FOUND, resource_id)


def get_settlement_survey(resource_id):
    return _resolve(SETTLEMENT_SURVEYS,
                    errors.ERR_SETTLEMENT_SURVEY_NOT_FOUND, resource_id)


def get_plate_lot(resource_id):
    return _resolve(PLATE_LOTS, errors.ERR_PLATE_LOT_NOT_FOUND, resource_id)


def get_shell_course(resource_id):
    return _resolve(SHELL_COURSES, errors.ERR_SHELL_COURSE_NOT_FOUND,
                    resource_id)


def get_welder(resource_id):
    return _resolve(WELDERS, errors.ERR_WELDER_NOT_FOUND, resource_id)


def get_weld_seam(resource_id):
    return _resolve(WELD_SEAMS, errors.ERR_WELD_SEAM_NOT_FOUND, resource_id)


def get_nde_report(resource_id):
    return _resolve(NDE_REPORTS, errors.ERR_NDE_REPORT_NOT_FOUND, resource_id)


def get_water_source(resource_id):
    return _resolve(WATER_SOURCES, errors.ERR_WATER_SOURCE_NOT_FOUND,
                    resource_id)


def get_hydrotest_plan(resource_id):
    return _resolve(HYDROTEST_PLANS, errors.ERR_HYDROTEST_PLAN_NOT_FOUND,
                    resource_id)


def get_water_withdrawal(resource_id):
    return _resolve(WATER_WITHDRAWALS, errors.ERR_WATER_WITHDRAWAL_NOT_FOUND,
                    resource_id)


def get_coating_application(resource_id):
    return _resolve(COATING_APPLICATIONS,
                    errors.ERR_COATING_APPLICATION_NOT_FOUND, resource_id)


def get_appurtenance(resource_id):
    return _resolve(APPURTENANCES, errors.ERR_APPURTENANCE_NOT_FOUND,
                    resource_id)


def get_commissioning_package(resource_id):
    return _resolve(COMMISSIONING_PACKAGES,
                    errors.ERR_COMMISSIONING_PACKAGE_NOT_FOUND, resource_id)


# ------------------------------------------------------ PRD 2.8 posture gates
def require_not_frozen(tank):
    """A FROZEN tank accepts no production work at all."""
    if tank["quality_posture"] == "FROZEN":
        raise ApiError(errors.ERR_TANK_POSTURE_FROZEN, 409,
                       "The tank's quality posture is FROZEN.")


def require_posture_open(tank):
    """The stricter gate: frozen is reported before restricted."""
    if tank["quality_posture"] == "FROZEN":
        raise ApiError(errors.ERR_TANK_POSTURE_FROZEN, 409,
                       "The tank's quality posture is FROZEN.")
    if tank["quality_posture"] != "OPEN":
        raise ApiError(errors.ERR_TANK_POSTURE_RESTRICTED, 409,
                       "This operation requires a completely clean tank.")


def duplicate(message="A resource with that identifier already exists."):
    return ApiError(errors.ERR_DUPLICATE_IDENTIFIER, 409, message)


def cross_tank(message="Every entity in one request must belong to the same tank."):
    return ApiError(errors.ERR_CROSS_TANK_REFERENCE, 409, message)

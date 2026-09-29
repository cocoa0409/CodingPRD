"""Shared state precondition helpers (PRD 2.11 step 8)."""
from errors import ApiError


def require_gmp_executed(project):
    if project["gmp_status"] != "EXECUTED":
        raise ApiError(
            "ERR_GMP_NOT_EXECUTED",
            "project gmp_status is %s, not EXECUTED" % project["gmp_status"],
        )


def require_gmp_not_executed(project):
    if project["gmp_status"] in ("EXECUTED", "CLOSED"):
        raise ApiError(
            "ERR_GMP_ALREADY_EXECUTED",
            "project gmp_status is already %s" % project["gmp_status"],
        )


def require_not_settled(project):
    if project["closeout_status"] == "SETTLEMENT_EXECUTED":
        raise ApiError(
            "ERR_CLOSEOUT_ALREADY_SETTLED",
            "project closeout_status has already reached SETTLEMENT_EXECUTED",
        )


def require_not_frozen(project):
    if project["contingency_posture"] == "FROZEN":
        raise ApiError(
            "ERR_CONTINGENCY_FROZEN",
            "project contingency_posture is FROZEN",
        )


def require_posture_recovered(project):
    if project["contingency_posture"] != "OPEN":
        raise ApiError(
            "ERR_POSTURE_NOT_RECOVERED",
            "project contingency_posture is %s, not OPEN"
            % project["contingency_posture"],
        )


def state_error(error_id, message):
    return ApiError(error_id, message)

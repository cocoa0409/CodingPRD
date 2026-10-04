"""CareTeam endpoints per PRD §3.4."""
from flask import Blueprint

from db import db
from errors import (err_not_found, err_state, err_input,
                    ERR_ENROLLMENT_NOT_FOUND, ERR_CARE_TEAM_NOT_FOUND,
                    ERR_CLINICIAN_NOT_FOUND, ERR_CARE_TEAM_NOT_DRAFT,
                    ERR_CARE_TEAM_NOT_ACTIVE, ERR_CARE_TEAM_NOT_SUSPENDED,
                    ERR_PRIMARY_NP_INVALID, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list
from services import serializers
from services.resources import touch

bp = Blueprint("care_teams", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "EngagementSpecialist", "PerformanceAnalyst"]
WRITE_ROLE = ["CareCoordinator"]

SLOT_DISCIPLINE = {
    "primary_np_id": "NP",
    "social_worker_id": "SW",
    "behavioral_clinician_id": "BH",
}


def _get_care_team(enrollment_id):
    for t in db.care_teams.values():
        if t.get("enrollment_id") == enrollment_id:
            return t
    return None


def _get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise err_not_found(ERR_ENROLLMENT_NOT_FOUND, "MemberEnrollment")
    return e


def _get_team_or_404(enrollment_id):
    t = _get_care_team(enrollment_id)
    if t is None:
        raise err_not_found(ERR_CARE_TEAM_NOT_FOUND, "CareTeam")
    return t


def _recompute_composition(t):
    t["composition_complete"] = bool(
        t.get("primary_np_id")
        and t.get("social_worker_id")
        and t.get("behavioral_clinician_id"))


@bp.route("/enrollments/<enrollmentId>/care-team", methods=["GET"])
def get_care_team(enrollmentId):
    require_roles(READ_ROLES)
    _get_enrollment_or_404(enrollmentId)
    t = _get_care_team(enrollmentId)
    items = [serializers.care_team(t)] if t is not None else []
    return success_list(items, limit=10, offset=0, total_count=len(items))


@bp.route("/enrollments/<enrollmentId>/care-team", methods=["PUT"])
def update_care_team(enrollmentId):
    require_roles(WRITE_ROLE)
    _get_enrollment_or_404(enrollmentId)
    t = _get_team_or_404(enrollmentId)

    from flask import request
    body = request.get_json(silent=True) or {}

    for slot, discipline in SLOT_DISCIPLINE.items():
        if slot not in body:
            continue
        value = body.get(slot)
        if value is None:
            t[slot] = None
            continue
        if not isinstance(value, str):
            raise err_input(ERR_INVALID_REQUEST,
                            "%s must be a clinician id string" % slot)
        clin = db.clinicians.get(value)
        if clin is None:
            raise err_not_found(ERR_CLINICIAN_NOT_FOUND, "Clinician")
        if clin.get("status") != "ACTIVE" or clin.get("discipline") != discipline:
            raise err_input(ERR_INVALID_REQUEST,
                            "Clinician for %s must be ACTIVE with discipline %s"
                            % (slot, discipline))
        t[slot] = value

    _recompute_composition(t)
    touch(t)
    return success_object(serializers.care_team(t))


@bp.route("/enrollments/<enrollmentId>/care-team/activate", methods=["POST"])
def activate_care_team(enrollmentId):
    require_roles(WRITE_ROLE)
    _get_enrollment_or_404(enrollmentId)
    t = _get_team_or_404(enrollmentId)
    if t.get("status") != "DRAFT":
        raise err_state(ERR_CARE_TEAM_NOT_DRAFT,
                        "Care team must be DRAFT to activate")
    np_id = t.get("primary_np_id")
    clin = db.clinicians.get(np_id) if np_id else None
    if (clin is None or clin.get("status") != "ACTIVE"
            or clin.get("discipline") != "NP"):
        raise err_state(ERR_PRIMARY_NP_INVALID,
                        "primary_np_id must reference an ACTIVE NP clinician")
    t["status"] = "ACTIVE"
    touch(t)
    return success_object(serializers.care_team(t))


@bp.route("/enrollments/<enrollmentId>/care-team/suspend", methods=["POST"])
def suspend_care_team(enrollmentId):
    require_roles(WRITE_ROLE)
    _get_enrollment_or_404(enrollmentId)
    t = _get_team_or_404(enrollmentId)
    if t.get("status") != "ACTIVE":
        raise err_state(ERR_CARE_TEAM_NOT_ACTIVE,
                        "Care team must be ACTIVE to suspend")
    t["status"] = "SUSPENDED"
    touch(t)
    return success_object(serializers.care_team(t))


@bp.route("/enrollments/<enrollmentId>/care-team/reinstate", methods=["POST"])
def reinstate_care_team(enrollmentId):
    require_roles(WRITE_ROLE)
    _get_enrollment_or_404(enrollmentId)
    t = _get_team_or_404(enrollmentId)
    if t.get("status") != "SUSPENDED":
        raise err_state(ERR_CARE_TEAM_NOT_SUSPENDED,
                        "Care team must be SUSPENDED to reinstate")
    t["status"] = "ACTIVE"
    touch(t)
    return success_object(serializers.care_team(t))

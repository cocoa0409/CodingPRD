"""Protocol milestone endpoints: deferral and execution (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint

from db import DB, clock, parse_iso, touch
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, promote_next_milestone, protocol_for_enrollment,
    protocol_is_frozen, referral_for_enrollment, serialize_milestone,
    sweep_missed_milestones,
)

bp = Blueprint("milestones", __name__)

NEAR_STATES = {"TX", "OK", "AR", "MS", "AL", "LA", "TN", "MO", "KY"}
FAR_STATES = {"CA", "NY", "IL", "WA", "MA", "NJ", "CT", "OR", "MD"}
ADJACENT_GROUPS = [NEAR_STATES, FAR_STATES]
VISIT_WINDOW_DAYS = 14


def _is_adjacent(clinic_state, household_state):
    clinic_state = (clinic_state or "").upper()
    household_state = (household_state or "").upper()
    if clinic_state == household_state:
        return True
    for group in ADJACENT_GROUPS:
        if clinic_state in group and household_state in group:
            return True
    return False


@bp.get("/programs/milestones")
def list_milestones():
    require_role("Any")
    rows = ordered(DB["milestones"].values())
    rows = filtered(rows,
                    enrollment_id=arg("enrollment_id"),
                    affiliate_clinic_id=arg("affiliate_clinic_id"),
                    deferred_from_milestone_id=arg("deferred_from_milestone_id"),
                    status=arg("status"))
    return list_response(rows, serialize_milestone)


@bp.get("/programs/protocol-milestones")
def list_protocol_milestones():
    require_role("Any")
    rows = ordered(DB["milestones"].values())
    rows = filtered(rows,
                    enrollment_id=arg("enrollment_id"),
                    affiliate_clinic_id=arg("affiliate_clinic_id"),
                    deferred_from_milestone_id=arg("deferred_from_milestone_id"),
                    status=arg("status"))
    return list_response(rows, serialize_milestone)


@bp.get("/programs/milestones/<milestone_id>")
def get_milestone(milestone_id):
    require_role("Any")
    milestone = get_or_404("milestones", milestone_id)
    return success_object(serialize_milestone(milestone), 200)


@bp.post("/programs/protocol-milestones/<milestone_id>/defer-visit")
def defer_visit(milestone_id):
    require_role("AffiliateClinicCoordinator")
    milestone = get_or_404("milestones", milestone_id)
    enrollment = get_or_404("enrollments", milestone["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    clinic_id = required(data, "affiliate_clinic_id", "str")
    clinic = get_or_404("clinics", clinic_id)

    if milestone["status"] != "DUE":
        raise ApiError("ERR_MILESTONE_NOT_DUE")
    sweep_missed_milestones(enrollment)
    if milestone["status"] != "DUE":
        raise ApiError("ERR_MILESTONE_NOT_DUE")
    if protocol is None or not (protocol["status"] == "OPEN"
                               and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_PROTOCOL_HELD")

    agreement = None
    for candidate in DB["affiliations"].values():
        if candidate["clinic_id"] != clinic["id"]:
            continue
        if protocol is None or candidate["protocol_id"] != protocol["id"]:
            continue
        if candidate["status"] != "ACTIVE":
            continue
        agreement = candidate
        break
    if agreement is None:
        raise ApiError("ERR_NO_ACTIVE_AFFILIATION_AGREEMENT")

    household_state = (referral or {}).get("household_state_code")
    if not clinic["is_active"] or not _is_adjacent(clinic["state_code"], household_state):
        raise ApiError("ERR_AFFILIATE_NOT_ADJACENT")
    if milestone["requires_main_campus"]:
        raise ApiError("ERR_MILESTONE_REQUIRES_MAIN_CAMPUS")
    if parse_iso(milestone["target_at"]) - clock() > timedelta(days=VISIT_WINDOW_DAYS):
        raise ApiError("ERR_VISIT_WINDOW_TOO_DISTANT")

    milestones = [m for m in DB["milestones"].values()
                  if m["enrollment_id"] == enrollment["id"]]
    previous = [m for m in milestones
                if m["milestone_sequence"] < milestone["milestone_sequence"]]
    predecessor = None
    if previous:
        predecessor = max(previous, key=lambda m: m["milestone_sequence"])
    milestone["deferred_from_milestone_id"] = predecessor["id"] if predecessor else None
    milestone["affiliate_clinic_id"] = clinic["id"]
    milestone["status"] = "DUE"
    touch(milestone)
    return success_object(serialize_milestone(milestone), 200)


@bp.post("/programs/protocol-milestones/<milestone_id>/execute")
def execute_milestone(milestone_id):
    require_role("AffiliateClinicCoordinator")
    milestone = get_or_404("milestones", milestone_id)
    enrollment = get_or_404("enrollments", milestone["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    from db import now_iso
    body_json()

    if milestone["status"] != "DUE":
        raise ApiError("ERR_MILESTONE_NOT_DUE")
    if protocol is None or not (protocol["status"] == "OPEN"
                                and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_PROTOCOL_NOT_OPEN")

    milestone["status"] = "EXECUTED"
    milestone["executed_at"] = now_iso()
    touch(milestone)
    promote_next_milestone(enrollment)
    return success_object(serialize_milestone(milestone), 200)
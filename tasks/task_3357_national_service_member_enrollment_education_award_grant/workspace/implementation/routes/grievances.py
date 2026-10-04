from flask import Blueprint

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("grievances", __name__)


def _grievance_member_id(grievance):
    enrollment = db.store.enrollments.get(grievance["enrollment_id"])
    return enrollment["member_id"] if enrollment is not None else None


@bp.route("/enrollments/<enrollmentId>/grievances", methods=["POST"])
def file_grievance(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["Member"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        auth.check_member_ownership(uid, role, enrollment["member_id"])
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    body = util.body_json()
    description = body.get("description")
    if not util.is_str(description) or not description.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    grievance = db.new_entity(
        {
            "id": util.new_id(),
            "enrollment_id": enrollmentId,
            "description": description,
            "outcome": None,
            "status": "FILED",
        }
    )
    db.store.grievances[grievance["id"]] = grievance
    return util.ok(serialize(grievance), 201)


@bp.route("/grievances/<grievanceId>/escalate", methods=["POST"])
def escalate_grievance(grievanceId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["Member"])
    grievance = db.store.grievances.get(grievanceId)
    if grievance is not None:
        auth.check_member_ownership(uid, role, _grievance_member_id(grievance))
    if grievance is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", 404, "Grievance not found")
    if grievance["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Grievance is not FILED")
    grievance["status"] = "ESCALATED"
    domain.touch(grievance)
    return util.ok(serialize(grievance), 200)


@bp.route("/grievances/<grievanceId>/resolve", methods=["POST"])
def resolve_grievance(grievanceId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    grievance = db.store.grievances.get(grievanceId)
    if grievance is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", 404, "Grievance not found")
    body = util.body_json()
    outcome = body.get("outcome")
    if outcome not in C.GRIEVANCE_OUTCOMES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "outcome must be UPHELD or DISMISSED"
        )
    if grievance["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Grievance is not ESCALATED")
    grievance["status"] = "RESOLVED"
    grievance["outcome"] = outcome
    domain.touch(grievance)
    return util.ok(serialize(grievance), 200)

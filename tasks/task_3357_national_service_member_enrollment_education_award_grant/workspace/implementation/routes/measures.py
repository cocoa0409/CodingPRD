from flask import Blueprint

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("measures", __name__)


@bp.route("/awards/<awardId>/performance-measures", methods=["POST"])
def create_measure(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    award = db.store.awards.get(awardId)
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if award is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Award not found")
    body = util.body_json()
    measure_code = body.get("measure_code")
    target_value = body.get("target_value")
    unit = body.get("unit")
    if measure_code not in C.MEASURE_CODES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "measure_code is invalid")
    if not util.is_int(target_value) or target_value <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "target_value must be an integer greater than zero"
        )
    if not util.is_str(unit) or not unit.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit is required")
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_SUSPENDED", 409, "Award is not ACTIVE")
    measure = db.new_entity(
        {
            "id": util.new_id(),
            "award_id": awardId,
            "measure_code": measure_code,
            "target_value": target_value,
            "unit": unit,
            "latest_period_start": None,
            "latest_period_end": None,
            "latest_actual_value": None,
            "review_comment": None,
            "status": "OPEN",
        }
    )
    db.store.measures[measure["id"]] = measure
    return util.ok(serialize(measure), 201)


@bp.route("/performance-measures/<measureId>/reports", methods=["POST"])
def submit_report(measureId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    measure = db.store.measures.get(measureId)
    if measure is not None:
        award = db.store.awards.get(measure["award_id"])
        if award is not None:
            auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if measure is None:
        raise ApiError("ERR_MEASURE_NOT_FOUND", 404, "Performance measure not found")
    body = util.body_json()
    period_start_raw = body.get("period_start")
    period_end_raw = body.get("period_end")
    period_start = util.parse_date(period_start_raw)
    period_end = util.parse_date(period_end_raw)
    actual_value = body.get("actual_value")
    if period_start is None or period_end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_start/period_end must be ISO dates"
        )
    if not util.is_int(actual_value) or actual_value < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "actual_value must be an integer >= 0"
        )
    if period_end < period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_end must not precede period_start"
        )
    if measure["status"] not in ("OPEN", "RETURNED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Measure is not OPEN or RETURNED"
        )
    measure["status"] = "SUBMITTED"
    measure["latest_period_start"] = period_start_raw
    measure["latest_period_end"] = period_end_raw
    measure["latest_actual_value"] = actual_value
    domain.touch(measure)
    return util.ok(serialize(measure), 200)


@bp.route("/performance-measures/<measureId>/review", methods=["POST"])
def review_measure(measureId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    measure = db.store.measures.get(measureId)
    if measure is None:
        raise ApiError("ERR_MEASURE_NOT_FOUND", 404, "Performance measure not found")
    body = util.body_json()
    decision = body.get("decision")
    comment = body.get("comment")
    if decision not in C.REVIEW_DECISIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be ACCEPT or RETURN")
    if comment is not None and not util.is_str(comment):
        raise ApiError("ERR_INVALID_REQUEST", 400, "comment must be a string")
    if decision == "RETURN" and (not util.is_str(comment) or not comment.strip()):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "comment is required when the decision is RETURN",
        )
    if measure["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Measure is not SUBMITTED")
    if decision == "ACCEPT":
        measure["status"] = "ACCEPTED"
        measure["review_comment"] = comment
    else:
        measure["status"] = "RETURNED"
        measure["review_comment"] = comment
    domain.touch(measure)
    return util.ok(serialize(measure), 200)

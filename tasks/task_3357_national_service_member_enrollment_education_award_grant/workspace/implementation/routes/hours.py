from flask import Blueprint

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("hours", __name__)


def _check_entry_ownership(uid, role, entry):
    enrollment = db.store.enrollments.get(entry["enrollment_id"])
    if enrollment is None:
        return
    award = db.store.awards.get(enrollment["award_id"])
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])


@bp.route("/enrollments/<enrollmentId>/hour-entries", methods=["POST"])
def create_hour_entry(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        award = db.store.awards.get(enrollment["award_id"])
        if award is not None:
            auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    body = util.body_json()
    service_date_raw = body.get("service_date")
    service_date = util.parse_date(service_date_raw)
    minutes = body.get("minutes")
    activity_code = body.get("activity_code")
    if service_date is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "service_date must be an ISO date (YYYY-MM-DD)"
        )
    if (
        not util.is_int(minutes)
        or minutes < C.MINUTES_MIN
        or minutes > C.MINUTES_MAX
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "minutes must be an integer in 1..48000"
        )
    if activity_code not in C.ACTIVITY_CODES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "activity_code is invalid")
    if enrollment["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE"
        )
    start = util.parse_date(enrollment["service_start_date"])
    end = util.parse_date(enrollment["service_end_date"])
    if not (start <= service_date < end):
        raise ApiError(
            "ERR_SERVICE_DATE_OUT_OF_RANGE",
            422,
            "service_date is outside the enrollment's service period",
        )
    entry = db.new_entity(
        {
            "id": util.new_id(),
            "enrollment_id": enrollmentId,
            "service_date": service_date_raw,
            "minutes": minutes,
            "activity_code": activity_code,
            "reject_reason": None,
            "status": "PENDING",
        }
    )
    db.store.hour_entries[entry["id"]] = entry
    return util.ok(serialize(entry), 201)


@bp.route("/hour-entries/<entryId>/certify", methods=["POST"])
def certify_hour_entry(entryId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    entry = db.store.hour_entries.get(entryId)
    if entry is not None:
        _check_entry_ownership(uid, role, entry)
    auth.check_not_debarred(uid, role)
    if entry is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND", 404, "Hour entry not found")
    if entry["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Hour entry is not PENDING")
    enrollment = db.store.enrollments.get(entry["enrollment_id"])
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    if entry["activity_code"] in C.PROHIBITED_ACTIVITIES:
        raise ApiError(
            "ERR_PROHIBITED_ACTIVITY",
            422,
            "Prohibited activities can never be certified",
        )
    if entry["activity_code"] == "FUNDRAISING":
        fundraising_after = enrollment["fundraising_certified_minutes"] + entry["minutes"]
        certified_after = enrollment["certified_minutes"] + entry["minutes"]
        if fundraising_after * 10 > certified_after:
            raise ApiError(
                "ERR_FUNDRAISING_CAP_EXCEEDED",
                422,
                "Fundraising minutes would exceed 10% of total certified minutes",
            )
    entry["status"] = "CERTIFIED"
    domain.touch(entry)
    enrollment["certified_minutes"] += entry["minutes"]
    if entry["activity_code"] == "FUNDRAISING":
        enrollment["fundraising_certified_minutes"] += entry["minutes"]
    domain.touch(enrollment)
    return util.ok(serialize(entry), 200)


@bp.route("/hour-entries/<entryId>/reject", methods=["POST"])
def reject_hour_entry(entryId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    entry = db.store.hour_entries.get(entryId)
    if entry is not None:
        _check_entry_ownership(uid, role, entry)
    auth.check_not_debarred(uid, role)
    if entry is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND", 404, "Hour entry not found")
    body = util.body_json()
    reason = body.get("reason")
    if not util.is_str(reason):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason is required")
    if entry["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Hour entry is not PENDING")
    entry["status"] = "REJECTED"
    entry["reject_reason"] = reason
    domain.touch(entry)
    return util.ok(serialize(entry), 200)

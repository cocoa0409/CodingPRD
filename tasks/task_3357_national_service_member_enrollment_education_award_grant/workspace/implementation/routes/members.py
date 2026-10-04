from flask import Blueprint

import auth
import clock
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("members", __name__)

MEMBER_READ_ROLES = ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff", "Member"]


@bp.route("/members/register", methods=["POST"])
def register_member():
    _uid, role = auth.authenticate()
    auth.authorize(role, ["Anonymous"])
    body = util.body_json()
    full_name = body.get("full_name")
    date_of_birth = body.get("date_of_birth")
    citizenship_status = body.get("citizenship_status")
    if not util.is_str(full_name) or not full_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "full_name is required")
    if util.parse_date(date_of_birth) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "date_of_birth must be an ISO date (YYYY-MM-DD)"
        )
    if citizenship_status not in C.CITIZENSHIP_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "citizenship_status is invalid")
    member = db.new_entity(
        {
            "id": util.new_id(),
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "citizenship_status": citizenship_status,
            "status": "ACTIVE",
            "for_cause_release_count": 0,
        }
    )
    db.store.members[member["id"]] = member
    return util.ok(serialize(member), 201)


@bp.route("/members/<memberId>", methods=["GET"])
def get_member(memberId):
    uid, role = auth.authenticate()
    auth.authorize(role, MEMBER_READ_ROLES)
    # Member self-read ownership is path-based.
    auth.check_member_ownership(uid, role, memberId)
    member = db.store.members.get(memberId)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    return util.ok(serialize(member), 200)


@bp.route("/members/<memberId>/criminal-history-checks", methods=["POST"])
def create_check(memberId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    auth.check_not_debarred(uid, role)
    member = db.store.members.get(memberId)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    existing = [c for c in db.store.checks.values() if c["member_id"] == memberId]
    for check in existing:
        if check["adjudication"] == "PENDING":
            raise ApiError(
                "ERR_CHECK_IN_PROGRESS",
                409,
                "A criminal history check is still PENDING for this member",
            )
    check_seq = max((c["check_seq"] for c in existing), default=0) + 1
    check = db.new_entity(
        {
            "id": util.new_id(),
            "member_id": memberId,
            "check_seq": check_seq,
            "nsopr_status": "PENDING",
            "state_status": "PENDING",
            "fbi_status": "PENDING",
            "adjudication": "PENDING",
            "adjudicated_at": None,
        }
    )
    db.store.checks[check["id"]] = check
    return util.ok(serialize(check), 201)


@bp.route("/members/<memberId>/criminal-history-checks", methods=["GET"])
def list_checks(memberId):
    uid, role = auth.authenticate()
    auth.authorize(role, MEMBER_READ_ROLES)
    auth.check_member_ownership(uid, role, memberId)
    member = db.store.members.get(memberId)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    items = [c for c in db.store.checks.values() if c["member_id"] == memberId]
    return util.list_response(items, serialize)


@bp.route("/criminal-history-checks/<checkId>/component-results", methods=["POST"])
def record_component_result(checkId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    check = db.store.checks.get(checkId)
    if check is None:
        raise ApiError("ERR_CHECK_NOT_FOUND", 404, "Criminal history check not found")
    body = util.body_json()
    component = body.get("component")
    result = body.get("result")
    if component not in C.CHECK_COMPONENTS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "component must be NSOPR, STATE_REPOSITORY, or FBI_FINGERPRINT",
        )
    if result not in C.CHECK_RESULTS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "result must be CLEAR or FLAGGED")
    if check["adjudication"] != "PENDING":
        raise ApiError(
            "ERR_CHECK_ALREADY_ADJUDICATED",
            409,
            "The check's adjudication has already left PENDING",
        )
    field = C.COMPONENT_FIELD[component]
    if check[field] != "PENDING":
        raise ApiError(
            "ERR_COMPONENT_ALREADY_RECORDED",
            409,
            "That component already has a recorded result",
        )
    check[field] = result
    components = [check["nsopr_status"], check["state_status"], check["fbi_status"]]
    if all(value != "PENDING" for value in components):
        check["adjudication"] = (
            "CLEARED" if all(value == "CLEAR" for value in components) else "FLAGGED"
        )
        check["adjudicated_at"] = clock.now_iso()
        domain.touch(check)
        domain.adjudication_cascade(check)
    else:
        domain.touch(check)
    return util.ok(serialize(check), 200)

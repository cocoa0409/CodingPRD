"""Churn notice lifecycle routes."""

from flask import Blueprint

from db import DB, touch
from errors import ERR_INVALID_STATE, ApiError
from middleware import auth, require_owner
from response import ok_object
from routes.common import fetch, guard_member_view, list_response
from services import calc, serialize
from timeutil import parse_ts

BP = Blueprint("notices", __name__)


@BP.route("/benefits/churn-notices", methods=["GET"])
def list_notices():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    items = list(DB.notices.values())
    filters = {"member_id": "member_id", "notice_type": "notice_type", "status": "status"}
    return list_response(items, serialize.notice, filters)


@BP.route("/benefits/churn-notices/<notice_id>", methods=["GET"])
def get_notice(notice_id):
    user_id, role = auth(("Member", "PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    notice = fetch("notices", notice_id)
    guard_member_view(user_id, role, notice["member_id"])
    return ok_object(serialize.notice(notice))


@BP.route("/benefits/churn-notices/<notice_id>/send", methods=["POST"])
def send_notice(notice_id):
    auth(("PlatformAdmin",))
    notice = fetch("notices", notice_id)
    if notice["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE)
    issued = parse_ts(notice.get("issued_at"))
    if issued is not None and DB.clock() < issued:
        raise ApiError(ERR_INVALID_STATE)
    notice["status"] = "SENT"
    touch(notice, DB.clock())
    return ok_object(serialize.notice(notice))


@BP.route("/benefits/churn-notices/<notice_id>/acknowledge", methods=["POST"])
def acknowledge_notice(notice_id):
    user_id, role = auth(("Member",))
    del role
    notice = fetch("notices", notice_id)
    require_owner(user_id, notice["member_id"])
    if notice["status"] != "SENT":
        raise ApiError(ERR_INVALID_STATE)
    notice["status"] = "ACKNOWLEDGED"
    touch(notice, DB.clock())
    return ok_object(serialize.notice(notice))

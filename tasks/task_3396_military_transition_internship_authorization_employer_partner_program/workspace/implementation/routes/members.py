from datetime import timedelta

from flask import Blueprint, request

import constants
import db
import services
from errors import fail
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_int,
    req_enum,
    req_list_str,
    req_date,
    opt_str,
    opt_date,
    opt_list_str,
)
from response import success, paginate
from util import serialize

bp = Blueprint("members", __name__)

ALL_ROLES = list(constants.ROLES)


def _get_member(mid):
    member = db.store.members.get(mid)
    if member is None:
        fail("ERR_MEMBER_NOT_FOUND", "ServiceMember %s does not exist" % mid)
    return member


@bp.route("/service-members", methods=["POST"])
@locked
def create_member():
    uid, role = auth_context()
    data = body()
    full_name = req_str(data, "full_name")
    service_branch = req_enum(data, "service_branch", constants.SERVICE_BRANCHES)
    pay_grade = req_str(data, "pay_grade")
    separation_date = req_date(data, "separation_date")
    skills = req_list_str(data, "skills")
    home_installation_id = req_str(data, "home_installation_id")
    require_role(role, ["TransitionCounselor"])
    installation = db.store.installations.get(home_installation_id)
    if installation is None:
        fail("ERR_INSTALLATION_NOT_FOUND", "Installation %s does not exist" % home_installation_id)
    ent = db.base_entity()
    ent.update(
        {
            "full_name": full_name,
            "service_branch": service_branch,
            "pay_grade": pay_grade,
            "separation_date": separation_date,
            "skills": skills,
            "home_installation_id": home_installation_id,
            "service_status": "ACTIVE_DUTY",
            "tap_stage": "TAP_NOT_STARTED",
            "active_match_count": 0,
        }
    )
    db.store.members[ent["id"]] = ent
    return success(services.serialize_member(ent), status=201)


@bp.route("/service-members", methods=["GET"])
@locked
def list_members():
    auth_context()
    items = sorted(db.store.members.values(), key=lambda e: e["_seq"])
    f_inst = request.args.get("home_installation_id")
    f_status = request.args.get("service_status")
    if f_inst is not None:
        items = [m for m in items if m["home_installation_id"] == f_inst]
    if f_status is not None:
        items = [m for m in items if m["service_status"] == f_status]
    page, pagination = paginate(items)
    return success([services.serialize_member(m) for m in page], pagination=pagination)


@bp.route("/service-members/<mid>", methods=["GET"])
@locked
def get_member(mid):
    auth_context()
    return success(services.serialize_member(_get_member(mid)))


@bp.route("/service-members/<mid>", methods=["PATCH"])
@locked
def patch_member(mid):
    uid, role = auth_context()
    data = body()
    expected_version = req_int(data, "expected_service_member_version")
    new_sep = opt_date(data, "separation_date")
    new_skills = None
    if "skills" in data and data["skills"] is not None:
        new_skills = req_list_str(data, "skills")
    new_pay_grade = opt_str(data, "pay_grade")
    require_role(role, ["TransitionCounselor"])
    member = _get_member(mid)
    if expected_version != member["version"]:
        fail("ERR_STALE_VERSION", "expected_service_member_version does not match current version")
    if new_sep is not None:
        deadline = new_sep - timedelta(days=constants.SEPARATION_BUFFER_DAYS)
        for m in db.store.matches.values():
            if (
                m["service_member_id"] == member["id"]
                and m["match_status"] in constants.NON_TERMINAL_MATCH_STATUSES
                and m["end_date"] > deadline
            ):
                fail(
                    "ERR_SEPARATION_DATE_CONFLICT",
                    "separation_date change would strand a non-terminal match",
                )
    if new_sep is not None:
        member["separation_date"] = new_sep
    if new_skills is not None:
        member["skills"] = new_skills
    if new_pay_grade is not None:
        member["pay_grade"] = new_pay_grade
    services.touch(member)
    return success(services.serialize_member(member))


@bp.route("/service-members/<mid>/tap-advance", methods=["POST"])
@locked
def tap_advance(mid):
    uid, role = auth_context()
    data = body()
    target = req_enum(data, "target_stage", constants.TAP_ORDER)
    require_role(role, ["TransitionCounselor"])
    member = _get_member(mid)
    if member["service_status"] != "ACTIVE_DUTY":
        fail("ERR_MEMBER_NOT_ON_ACTIVE_DUTY", "Member is not ACTIVE_DUTY")
    order = constants.TAP_ORDER
    if order.index(target) != order.index(member["tap_stage"]) + 1:
        fail("ERR_TAP_SEQUENCE_VIOLATION", "target_stage is not exactly the next TAP stage")
    member["tap_stage"] = target
    services.touch(member)
    return success(services.serialize_member(member))

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
    req_enum,
    opt_str,
)
from response import success, paginate
from util import serialize

bp = Blueprint("applications", __name__)


def _get_application(aid):
    app = db.store.applications.get(aid)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "InternshipApplication %s does not exist" % aid)
    return app


@bp.route("/internship-applications", methods=["POST"])
@locked
def create_application():
    uid, role = auth_context()
    data = body()
    smid = req_str(data, "service_member_id")
    require_role(role, ["ServiceMember"])
    member = db.store.members.get(smid)
    if member is None:
        fail("ERR_MEMBER_NOT_FOUND", "ServiceMember %s does not exist" % smid)
    if uid != smid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal service_member_id")
    if member["service_status"] != "ACTIVE_DUTY":
        fail("ERR_MEMBER_NOT_ON_ACTIVE_DUTY", "Member is not ACTIVE_DUTY")
    for app in db.store.applications.values():
        if (
            app["service_member_id"] == smid
            and app["status"] in constants.LIVE_APPLICATION_STATUSES
        ):
            fail("ERR_ACTIVE_APPLICATION_EXISTS", "Member already holds a live application")
    installation = db.store.installations.get(member["home_installation_id"])
    if installation is None:
        fail("ERR_INSTALLATION_NOT_FOUND", "Member home installation does not exist")
    if member["pay_grade"] in installation["excluded_pay_grades"]:
        fail("ERR_PAY_GRADE_EXCLUDED", "Member pay grade is excluded at this installation")
    days = (member["separation_date"] - db.now().date()).days
    if days < constants.ELIGIBILITY_WINDOW_MIN_DAYS or days > constants.ELIGIBILITY_WINDOW_MAX_DAYS:
        fail("ERR_OUTSIDE_ELIGIBILITY_WINDOW", "days_until_separation outside [30, 180]")
    ent = db.base_entity()
    ent.update(
        {
            "service_member_id": smid,
            "installation_id": member["home_installation_id"],
            "status": "SUBMITTED",
            "submitted_at": db.now(),
            "days_until_separation_at_submission": days,
            "decided_by_user_id": None,
            "decision_reason": None,
            "decided_at": None,
            "appeal_count": 0,
            "appeal_deadline": None,
        }
    )
    db.store.applications[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/internship-applications", methods=["GET"])
@locked
def list_applications():
    auth_context()
    items = sorted(db.store.applications.values(), key=lambda e: e["_seq"])
    f_member = request.args.get("service_member_id")
    f_inst = request.args.get("installation_id")
    f_status = request.args.get("status")
    if f_member is not None:
        items = [a for a in items if a["service_member_id"] == f_member]
    if f_inst is not None:
        items = [a for a in items if a["installation_id"] == f_inst]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    page, pagination = paginate(items)
    return success([serialize(a) for a in page], pagination=pagination)


@bp.route("/internship-applications/<aid>", methods=["GET"])
@locked
def get_application(aid):
    auth_context()
    return success(serialize(_get_application(aid)))


@bp.route("/internship-applications/<aid>/commander-decision", methods=["POST"])
@locked
def commander_decision(aid):
    uid, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "DENY"})
    reason = opt_str(data, "reason")
    if decision == "DENY" and reason is None:
        fail("ERR_VALIDATION", "reason is required when decision is DENY")
    require_role(role, ["UnitCommander"])
    app = _get_application(aid)
    if app["status"] != "SUBMITTED":
        fail("ERR_APPLICATION_NOT_SUBMITTED", "Application is not SUBMITTED")
    installation = db.store.installations.get(app["installation_id"])
    member = db.store.members.get(app["service_member_id"])
    if (
        installation is not None
        and installation["requires_tap_complete"]
        and (member is None or member["tap_stage"] != "CAPSTONE_DONE")
    ):
        fail("ERR_TAP_INCOMPLETE", "Installation requires TAP CAPSTONE_DONE before decision")
    app["decided_by_user_id"] = uid
    app["decided_at"] = db.now()
    app["decision_reason"] = reason
    if decision == "APPROVE":
        app["status"] = "APPROVED"
    else:
        app["status"] = "DENIED"
        app["appeal_deadline"] = db.now() + timedelta(days=installation["appeal_window_days"])
    services.touch(app)
    return success(serialize(app))


@bp.route("/internship-applications/<aid>/appeal", methods=["POST"])
@locked
def appeal(aid):
    uid, role = auth_context()
    data = body()
    opt_str(data, "appeal_reason")  # optional; validated for type, not stored
    require_role(role, ["ServiceMember"])
    app = _get_application(aid)
    if uid != app["service_member_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the application's service_member_id")
    if app["status"] != "DENIED":
        fail("ERR_APPLICATION_NOT_DENIED", "Application is not DENIED")
    if app["appeal_deadline"] is None or db.now() > app["appeal_deadline"]:
        fail("ERR_APPEAL_WINDOW_EXPIRED", "Appeal window has expired")
    if app["appeal_count"] >= constants.MAX_APPEALS_PER_APPLICATION:
        fail("ERR_MAX_APPEALS_REACHED", "Appeal budget exhausted")
    app["status"] = "UNDER_APPEAL"
    app["appeal_count"] += 1
    services.touch(app)
    return success(serialize(app))


@bp.route("/internship-applications/<aid>/adjudicate-appeal", methods=["POST"])
@locked
def adjudicate_appeal(aid):
    uid, role = auth_context()
    data = body()
    outcome = req_enum(data, "outcome", {"OVERTURNED", "UPHELD"})
    reason = opt_str(data, "reason")
    require_role(role, ["InstallationAuthority"])
    app = _get_application(aid)
    if app["status"] != "UNDER_APPEAL":
        fail("ERR_NO_PENDING_APPEAL", "Application has no pending appeal")
    if uid == app["decided_by_user_id"]:
        fail(
            "ERR_APPEAL_ADJUDICATOR_CONFLICT",
            "Adjudicator must differ from the deciding commander",
        )
    app["decided_by_user_id"] = uid
    app["decided_at"] = db.now()
    app["decision_reason"] = reason
    if outcome == "OVERTURNED":
        app["status"] = "APPROVED"
    else:
        app["status"] = "DENIED"
        installation = db.store.installations.get(app["installation_id"])
        window = installation["appeal_window_days"] if installation is not None else 1
        app["appeal_deadline"] = db.now() + timedelta(days=window)
    services.touch(app)
    return success(serialize(app))

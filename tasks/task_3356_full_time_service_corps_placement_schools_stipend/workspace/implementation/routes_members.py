from flask import Blueprint, request

from db import store, touch, parse_date
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_enum, opt_date, is_int,
                        paginate, forbid_role, not_owner)
from response import ok
from serialize import (member_json, assignment_json, student_json,
                       hour_entry_json, payment_json)
import services as svc

bp = Blueprint("members", __name__)

MEMBER_READ_ROLES = ["SiteDirector", "ProgramManager", "StipendAdministrator",
                     "CorpsMember"]
SERVICE_STATES = {"ENROLLED", "ACTIVE", "SUSPENDED", "COMPLETED", "EXITED_EARLY"}
STIPEND_STATES = {"NOT_STARTED", "ACTIVE", "SUSPENDED", "ENDED"}
AWARD_STATES = {"NOT_EARNED", "EARNED_FULL", "EARNED_PARTIAL", "FORFEITED",
                "DISBURSED"}
EXIT_TYPES = {"COMPLETED_TERM", "COMPELLING_CIRCUMSTANCE", "FOR_CAUSE",
              "NON_COMPELLING"}


def get_member_or_404(member_id):
    m = store.members.get(member_id)
    if m is None:
        not_found("CorpsMember not found")
    return m


def _check_self(role, uid, member_id):
    if role == "CorpsMember" and uid != member_id:
        not_owner("CorpsMember may only access their own record")


@bp.route("/corps/members/<member_id>", methods=["GET"])
def get_member(member_id):
    uid, role = auth(MEMBER_READ_ROLES)
    _check_self(role, uid, member_id)
    return ok(member_json(get_member_or_404(member_id)), 200)


@bp.route("/corps/members/<member_id>/state", methods=["POST"])
def member_state(member_id):
    uid, role = auth(["ProgramManager", "StipendAdministrator"])
    data = body()
    dimension = data.get("dimension", "SERVICE")
    if dimension not in ("SERVICE", "STIPEND", "AWARD"):
        bad_request("dimension must be SERVICE, STIPEND or AWARD")
    to_status = need(data, "to_status")
    if dimension == "SERVICE":
        if role != "ProgramManager":
            forbid_role("Only a ProgramManager drives the SERVICE dimension")
        if to_status not in SERVICE_STATES:
            bad_request("to_status is not a valid SERVICE status")
    elif dimension == "STIPEND":
        if role != "StipendAdministrator":
            forbid_role("Only a StipendAdministrator drives the STIPEND dimension")
        if to_status not in STIPEND_STATES:
            bad_request("to_status is not a valid STIPEND status")
    else:
        if role != "StipendAdministrator":
            forbid_role("Only a StipendAdministrator drives the AWARD dimension")
        if to_status not in AWARD_STATES:
            bad_request("to_status is not a valid AWARD status")
    m = get_member_or_404(member_id)

    if dimension == "SERVICE":
        cur = m["service_status"]
        if to_status == "ACTIVE" and cur == "ENROLLED":
            site = svc.site_of_member(m)
            if site is None or site["status"] != "ACTIVE":
                invalid_state("Site is not ACTIVE")
            m["service_status"] = "ACTIVE"
            if m["stipend_status"] == "NOT_STARTED":
                m["stipend_status"] = "ACTIVE"
        elif to_status == "SUSPENDED" and cur == "ACTIVE":
            m["service_status"] = "SUSPENDED"
            if m["stipend_status"] == "ACTIVE":
                m["stipend_status"] = "SUSPENDED"
        elif to_status == "ACTIVE" and cur == "SUSPENDED":
            m["service_status"] = "ACTIVE"
            if m["stipend_status"] == "SUSPENDED":
                m["stipend_status"] = "ACTIVE"
        else:
            invalid_state("service_status %s cannot transition to %s"
                          % (cur, to_status))
    elif dimension == "STIPEND":
        cur = m["stipend_status"]
        if to_status == "SUSPENDED" and cur == "ACTIVE":
            m["stipend_status"] = "SUSPENDED"
        elif to_status == "ACTIVE" and cur == "SUSPENDED":
            if m["service_status"] != "ACTIVE":
                raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                               "Member service_status is not ACTIVE")
            m["stipend_status"] = "ACTIVE"
        else:
            invalid_state("stipend_status %s cannot transition to %s"
                          % (cur, to_status))
    else:  # AWARD
        if to_status == "DISBURSED":
            if m["award_status"] not in ("EARNED_FULL", "EARNED_PARTIAL"):
                raise ApiError("ERR_AWARD_NOT_EARNED", 409,
                               "Award is not in an earned state")
            m["award_status"] = "DISBURSED"
        else:
            invalid_state("award_status %s cannot transition to %s"
                          % (m["award_status"], to_status))
    touch(m)
    return ok(member_json(m), 200)


@bp.route("/corps/members/<member_id>/exit", methods=["POST"])
def member_exit(member_id):
    auth(["ProgramManager"])
    data = body()
    expected = need(data, "expected_member_version")
    if not is_int(expected):
        bad_request("expected_member_version must be an integer")
    exit_type = need_enum(data, "exit_type", EXIT_TYPES)
    exit_date = opt_date(data, "exit_date")
    m = get_member_or_404(member_id)
    if expected != m["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_member_version does not match current version")
    cur = m["service_status"]
    if exit_type == "COMPLETED_TERM":
        if cur != "ACTIVE":
            invalid_state("COMPLETED_TERM exit is only valid from ACTIVE")
        if svc.verified_hours(m) < svc.FULL_TERM_HOURS:
            raise ApiError("ERR_COMPLETION_HOURS_NOT_MET", 422,
                           "verified_hours_total is below 120")
    else:
        if cur not in ("ACTIVE", "SUSPENDED", "ENROLLED"):
            invalid_state("Member in %s cannot exit" % cur)
    from db import clock_date_str
    svc.member_exit(m, exit_type, exit_date or clock_date_str())
    return ok(member_json(m), 200)


# ---- member-scoped list endpoints ------------------------------------------

@bp.route("/corps/members/<member_id>/assignments", methods=["GET"])
def list_member_assignments(member_id):
    uid, role = auth(["SiteDirector", "ProgramManager", "CorpsMember"])
    _check_self(role, uid, member_id)
    m = get_member_or_404(member_id)
    items = svc.assignments_of_member(m["id"])
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([assignment_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/members/<member_id>/students", methods=["GET"])
def list_member_students(member_id):
    uid, role = auth(["SiteDirector", "ProgramManager", "CorpsMember"])
    _check_self(role, uid, member_id)
    m = get_member_or_404(member_id)
    items = [s for s in store.students.values()
             if m["id"] in s.get("_caseload_members", [])]
    flt = request.args.get("caseload_status")
    if flt is not None:
        items = [x for x in items if x["caseload_status"] == flt]
    page, pg = paginate(items)
    return ok([student_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/members/<member_id>/hour-entries", methods=["GET"])
def list_member_hour_entries(member_id):
    uid, role = auth(MEMBER_READ_ROLES)
    _check_self(role, uid, member_id)
    m = get_member_or_404(member_id)
    items = svc.entries_of_member(m["id"])
    if request.args.get("status") is not None:
        items = [x for x in items if x["status"] == request.args.get("status")]
    if request.args.get("category") is not None:
        items = [x for x in items if x["category"] == request.args.get("category")]
    if request.args.get("service_date") is not None:
        items = [x for x in items
                 if x["service_date"] == request.args.get("service_date")]
    page, pg = paginate(items)
    return ok([hour_entry_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/members/<member_id>/stipend-payments", methods=["GET"])
def list_member_payments(member_id):
    uid, role = auth(MEMBER_READ_ROLES)
    _check_self(role, uid, member_id)
    m = get_member_or_404(member_id)
    items = svc.payments_of_member(m["id"])
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([payment_json(x) for x in page], 200, is_array=True, pagination=pg)

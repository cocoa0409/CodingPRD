from flask import Blueprint, request

from db import store, new_entity, touch, parse_date, clock_date, clock_date_str
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_int, need_enum,
                        is_int, paginate, forbid_role, not_owner)
from response import ok
from serialize import school_json, team_json, student_json, report_json
import services as svc

bp = Blueprint("schools", __name__)

SCOPES = {"ATTENDANCE_SUPPORT", "LITERACY_TUTORING", "MATH_TUTORING",
          "WHOLE_SCHOOL_EVENTS"}
AGREEMENT_STATES = {"DRAFT", "SIGNED", "ACTIVE", "AMENDMENT_REVIEW", "SUSPENDED",
                    "COMPLETED", "TERMINATED"}
DATA_SHARING_STATES = {"DRAFT", "SIGNED", "EXPIRED"}


def get_school_or_404(school_id):
    s = store.schools.get(school_id)
    if s is None:
        not_found("School not found")
    return s


def _validate_scope(v):
    if (not isinstance(v, list) or not v
            or any(x not in SCOPES for x in v)):
        bad_request("service_scope must be a non-empty subset of "
                    "ATTENDANCE_SUPPORT, LITERACY_TUTORING, MATH_TUTORING, "
                    "WHOLE_SCHOOL_EVENTS")
    return v


@bp.route("/corps/schools", methods=["POST"])
def create_school():
    auth(["SiteDirector"])
    data = body()
    site_id = need_str(data, "site_id")
    name = need_str(data, "name")
    district_name = need_str(data, "district_name")
    team_size = need_int(data, "team_size")
    if team_size < 3:
        bad_request("team_size must be >= 3")
    scope = _validate_scope(need(data, "service_scope"))
    cost_share = need_int(data, "annual_cost_share_cents")
    if cost_share < 0:
        bad_request("annual_cost_share_cents must be >= 0")
    site = store.sites.get(site_id)
    if site is None:
        not_found("Site not found")
    s = new_entity({
        "site_id": site_id,
        "name": name,
        "district_name": district_name,
        "team_size": team_size,
        "service_scope": scope,
        "annual_cost_share_cents": cost_share,
        "agreement_status": "DRAFT",
        "data_sharing_status": "DRAFT",
    })
    store.schools[s["id"]] = s
    return ok(school_json(s), 201)


@bp.route("/corps/schools/<school_id>", methods=["GET"])
def get_school(school_id):
    auth(["SiteDirector", "ProgramManager", "SchoolLiaison"])
    return ok(school_json(get_school_or_404(school_id)), 200)


@bp.route("/corps/schools/<school_id>/amend", methods=["POST"])
def amend_school(school_id):
    auth(["SiteDirector"])
    data = body()
    expected = need(data, "expected_school_version")
    if not is_int(expected):
        bad_request("expected_school_version must be an integer")
    new_team_size = data.get("team_size")
    if new_team_size is not None and (not is_int(new_team_size) or new_team_size < 3):
        bad_request("team_size must be an integer >= 3")
    new_cost = data.get("annual_cost_share_cents")
    if new_cost is not None and (not is_int(new_cost) or new_cost < 0):
        bad_request("annual_cost_share_cents must be a non-negative integer")
    new_scope = data.get("service_scope")
    if new_scope is not None:
        _validate_scope(new_scope)
    s = get_school_or_404(school_id)
    if expected != s["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_school_version does not match current version")
    if s["agreement_status"] != "ACTIVE":
        invalid_state("Only an ACTIVE agreement can be amended")
    if new_team_size is not None:
        s["team_size"] = new_team_size
    if new_cost is not None:
        s["annual_cost_share_cents"] = new_cost
    if new_scope is not None:
        s["service_scope"] = new_scope
    s["agreement_status"] = "AMENDMENT_REVIEW"
    touch(s)
    return ok(school_json(s), 200)


def _data_sharing_not_signed():
    raise ApiError("ERR_DATA_SHARING_NOT_SIGNED", 409,
                   "data_sharing_status is not SIGNED")


def _agreement_transition(s, to_status, uid, role):
    cur = s["agreement_status"]
    site = store.sites.get(s["site_id"])
    if to_status == "SIGNED" and cur == "DRAFT":
        if role != "SchoolLiaison":
            forbid_role("Only the SchoolLiaison signs the agreement")
        s["agreement_status"] = "SIGNED"
    elif to_status == "ACTIVE" and cur == "SIGNED":
        if role != "SiteDirector":
            forbid_role("Only a SiteDirector activates the agreement")
        if s["data_sharing_status"] != "SIGNED":
            _data_sharing_not_signed()
        if site is None or site["status"] != "ACTIVE":
            invalid_state("Site is not ACTIVE")
        s["agreement_status"] = "ACTIVE"
    elif to_status == "ACTIVE" and cur == "AMENDMENT_REVIEW":
        if role != "SchoolLiaison":
            forbid_role("Only the SchoolLiaison confirms an amendment")
        if s["data_sharing_status"] != "SIGNED":
            _data_sharing_not_signed()
        s["agreement_status"] = "ACTIVE"
    elif to_status == "SUSPENDED" and cur == "ACTIVE":
        if role != "SiteDirector":
            forbid_role("Only a SiteDirector suspends the agreement")
        s["agreement_status"] = "SUSPENDED"
    elif to_status == "ACTIVE" and cur == "SUSPENDED":
        if role != "SiteDirector":
            forbid_role("Only a SiteDirector resumes the agreement")
        if s["data_sharing_status"] != "SIGNED":
            _data_sharing_not_signed()
        s["agreement_status"] = "ACTIVE"
    elif to_status == "COMPLETED" and cur == "ACTIVE":
        if role != "SiteDirector":
            forbid_role("Only a SiteDirector completes the agreement")
        if clock_date() < parse_date(site["service_year_end"]):
            invalid_state("Service year has not ended")
        s["agreement_status"] = "COMPLETED"
        svc.complete_school_agreement(s, clock_date_str())
    elif to_status == "TERMINATED" and cur in ("ACTIVE", "SUSPENDED"):
        if role != "SiteDirector":
            forbid_role("Only a SiteDirector terminates the agreement")
        s["agreement_status"] = "TERMINATED"
        svc.terminate_school(s, clock_date_str())
    else:
        invalid_state("Agreement status %s cannot transition to %s"
                      % (cur, to_status))


def _data_sharing_transition(s, to_status, uid, role):
    cur = s["data_sharing_status"]
    if to_status == "SIGNED" and cur in ("DRAFT", "EXPIRED"):
        if role != "SchoolLiaison":
            forbid_role("Only the SchoolLiaison signs data sharing")
        # EXPIRED -> SIGNED deliberately does not resume a SUSPENDED agreement.
        s["data_sharing_status"] = "SIGNED"
    elif to_status == "EXPIRED" and cur == "SIGNED":
        if role not in ("SchoolLiaison", "SiteDirector"):
            forbid_role()
        s["data_sharing_status"] = "EXPIRED"
        if s["agreement_status"] in ("ACTIVE", "AMENDMENT_REVIEW"):
            s["agreement_status"] = "SUSPENDED"
    else:
        invalid_state("Data-sharing status %s cannot transition to %s"
                      % (cur, to_status))


@bp.route("/corps/schools/<school_id>/state", methods=["POST"])
def school_state(school_id):
    uid, role = auth(["SiteDirector", "SchoolLiaison"])
    if role == "SchoolLiaison" and uid != school_id:
        not_owner("SchoolLiaison may only act on their own school")
    data = body()
    dimension = data.get("dimension", "AGREEMENT")
    if dimension not in ("AGREEMENT", "DATA_SHARING"):
        bad_request("dimension must be AGREEMENT or DATA_SHARING")
    to_status = need(data, "to_status")
    valid = AGREEMENT_STATES if dimension == "AGREEMENT" else DATA_SHARING_STATES
    if to_status not in valid:
        bad_request("to_status is not a valid %s status" % dimension)
    s = get_school_or_404(school_id)
    if dimension == "AGREEMENT":
        _agreement_transition(s, to_status, uid, role)
    else:
        _data_sharing_transition(s, to_status, uid, role)
    touch(s)
    return ok(school_json(s), 200)


# ---- school-scoped list endpoints ------------------------------------------

@bp.route("/corps/schools/<school_id>/teams", methods=["GET"])
def list_school_teams(school_id):
    auth(["SiteDirector", "ProgramManager", "SchoolLiaison"])
    s = get_school_or_404(school_id)
    items = svc.teams_of_school(s["id"])
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([team_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/schools/<school_id>/students", methods=["GET"])
def list_school_students(school_id):
    auth(["SiteDirector", "ProgramManager", "SchoolLiaison"])
    s = get_school_or_404(school_id)
    items = svc.students_of_school(s["id"])
    if request.args.get("focus_list_type") is not None:
        items = [x for x in items
                 if x["focus_list_type"] == request.args.get("focus_list_type")]
    if request.args.get("caseload_status") is not None:
        items = [x for x in items
                 if x["caseload_status"] == request.args.get("caseload_status")]
    page, pg = paginate(items)
    return ok([student_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/schools/<school_id>/evaluation-reports", methods=["GET"])
def list_school_reports(school_id):
    auth(["SiteDirector", "ProgramManager", "SchoolLiaison"])
    s = get_school_or_404(school_id)
    items = [r for r in store.reports.values() if r["school_id"] == s["id"]]
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([report_json(x) for x in page], 200, is_array=True, pagination=pg)

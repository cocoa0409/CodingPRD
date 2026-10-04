from flask import Blueprint, request

from db import store, new_entity, touch, parse_date, clock_date, clock_date_str
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_date, opt_date,
                        is_int, paginate)
from response import ok
from serialize import team_json, assignment_json
import services as svc

bp = Blueprint("teams", __name__)

TEAM_STATES = {"FORMING", "DEPLOYED", "UNDERSTAFFED", "COMPLETED", "DISSOLVED"}
ASSIGNMENT_ROLES = {"CORPS_MEMBER", "TEAM_LEADER"}


def get_team_or_404(team_id):
    t = store.teams.get(team_id)
    if t is None:
        not_found("Team not found")
    return t


@bp.route("/corps/teams", methods=["POST"])
def create_team():
    auth(["SiteDirector"])
    data = body()
    school_id = need_str(data, "school_id")
    name = need_str(data, "name")
    backfill_deadline = need_date(data, "backfill_deadline")
    backfill_limit = data.get("backfill_limit", 2)
    if not is_int(backfill_limit) or backfill_limit < 0:
        bad_request("backfill_limit must be a non-negative integer")
    school = store.schools.get(school_id)
    if school is None:
        not_found("School not found")
    site = store.sites.get(school["site_id"])
    if site is None or site["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "Site is not ACTIVE")
    if school["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "School agreement is not ACTIVE")
    t = new_entity({
        "school_id": school_id,
        "name": name,
        "team_size_snapshot": school["team_size"],
        "backfill_limit": backfill_limit,
        "backfill_deadline": backfill_deadline,
        "status": "FORMING",
    })
    store.teams[t["id"]] = t
    return ok(team_json(t), 201)


@bp.route("/corps/teams/<team_id>", methods=["GET"])
def get_team(team_id):
    auth(["SiteDirector", "ProgramManager"])
    return ok(team_json(get_team_or_404(team_id)), 200)


@bp.route("/corps/teams/<team_id>/state", methods=["POST"])
def team_state(team_id):
    auth(["SiteDirector"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in TEAM_STATES:
        bad_request("to_status must be a valid Team status")
    t = get_team_or_404(team_id)
    cur = t["status"]
    if to_status == "DEPLOYED" and cur == "FORMING":
        school = store.schools.get(t["school_id"])
        if school is None or school["agreement_status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                           "School agreement is not ACTIVE")
        if svc.team_active_count(t) < svc.team_min_members(t):
            raise ApiError("ERR_TEAM_STAFFING_BELOW_MINIMUM", 422,
                           "active_assignment_count is below min_active_members")
        t["status"] = "DEPLOYED"
        touch(t)
    elif to_status == "COMPLETED" and cur in ("DEPLOYED", "UNDERSTAFFED"):
        school = store.schools.get(t["school_id"])
        site = store.sites.get(school["site_id"]) if school else None
        if site is None or clock_date() < parse_date(site["service_year_end"]):
            invalid_state("Service year has not ended")
        svc.complete_team(t, clock_date_str())
    elif to_status == "DISSOLVED" and cur in ("FORMING", "DEPLOYED", "UNDERSTAFFED"):
        svc.dissolve_team(t, clock_date_str())
    else:
        invalid_state("Team status %s cannot transition to %s" % (cur, to_status))
    return ok(team_json(t), 200)


def _capacity_exceeded(team, new_start):
    """Per-date coverage including the new open-ended assignment must stay
    <= team_size_snapshot. Dates compare lexicographically (YYYY-MM-DD)."""
    snap = team["team_size_snapshot"]
    intervals = [(a["start_date"], a["end_date"])
                 for a in svc.assignments_of_team(team["id"])]
    points = [new_start] + [s for s, _e in intervals if s > new_start]
    for p in points:
        count = 1  # the new assignment, open-ended from new_start
        for s, e in intervals:
            if s <= p and (e is None or p < e):
                count += 1
        if count > snap:
            return True
    return False


@bp.route("/corps/teams/<team_id>/assignments", methods=["POST"])
def create_assignment(team_id):
    auth(["ProgramManager"])
    data = body()
    corps_member_id = need_str(data, "corps_member_id")
    start_date = need_date(data, "start_date")
    expected = need(data, "expected_team_version")
    if not is_int(expected):
        bad_request("expected_team_version must be an integer")
    role = data.get("role", "CORPS_MEMBER")
    if role not in ASSIGNMENT_ROLES:
        bad_request("role must be CORPS_MEMBER or TEAM_LEADER")
    t = get_team_or_404(team_id)
    m = store.members.get(corps_member_id)
    if m is None:
        not_found("CorpsMember not found")
    if expected != t["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_team_version does not match current version")
    if t["status"] not in ("FORMING", "DEPLOYED", "UNDERSTAFFED"):
        invalid_state("Team status %s does not accept assignments" % t["status"])
    is_backfill = t["status"] in ("DEPLOYED", "UNDERSTAFFED")
    if is_backfill and clock_date() > parse_date(t["backfill_deadline"]):
        raise ApiError("ERR_BACKFILL_WINDOW_CLOSED", 422,
                       "Backfill deadline has passed")
    if m["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member service_status is not ACTIVE")
    # Half-open intervals: any existing non-ENDED (open-ended) assignment of
    # this member overlaps any new open-ended assignment.
    for a in svc.assignments_of_member(m["id"]):
        if a["status"] != "ENDED":
            if a["end_date"] is None or a["end_date"] > start_date:
                raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                               "Member has an overlapping assignment")
    if _capacity_exceeded(t, start_date):
        raise ApiError("ERR_TEAM_CAPACITY_EXCEEDED", 422,
                       "Team coverage would exceed team_size_snapshot")
    if is_backfill and svc.team_backfill_count(t) >= t["backfill_limit"]:
        raise ApiError("ERR_BACKFILL_LIMIT_REACHED", 422,
                       "Team backfill budget is exhausted")
    a = new_entity({
        "team_id": t["id"],
        "corps_member_id": m["id"],
        "role": role,
        "start_date": start_date,
        "end_date": None,
        "is_backfill": is_backfill,
        "status": "ACTIVE",
    })
    store.assignments[a["id"]] = a
    if t["status"] == "UNDERSTAFFED" and svc.team_active_count(t) >= svc.team_min_members(t):
        t["status"] = "DEPLOYED"
    touch(t)
    return ok(assignment_json(a), 201)


@bp.route("/corps/team-assignments/<assignment_id>/end", methods=["POST"])
def end_assignment(assignment_id):
    auth(["ProgramManager"])
    data = body()
    end_date = opt_date(data, "end_date")
    a = store.assignments.get(assignment_id)
    if a is None:
        not_found("TeamAssignment not found")
    if a["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE assignment can be ended")
    effective_end = end_date or clock_date_str()
    if effective_end < a["start_date"]:
        bad_request("end_date must be on or after start_date")
    svc.end_assignment_manual(a, effective_end)
    return ok(assignment_json(a), 200)


@bp.route("/corps/teams/<team_id>/assignments", methods=["GET"])
def list_team_assignments(team_id):
    auth(["SiteDirector", "ProgramManager"])
    t = get_team_or_404(team_id)
    items = svc.assignments_of_team(t["id"])
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([assignment_json(x) for x in page], 200, is_array=True, pagination=pg)

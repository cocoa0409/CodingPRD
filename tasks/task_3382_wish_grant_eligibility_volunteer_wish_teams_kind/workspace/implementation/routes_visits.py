"""WishVisit scheduling, per-team listing, and conclude (COMPLETED / NO_SHOW)."""

from flask import Blueprint, request, g

from auth import require_roles
from db import STORE, now, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_visit
from util import (
    body_json, req_str, req_enum, req_datetime, parse_date,
    age_months, pagination, paginate, bad,
)

bp = Blueprint("visits", __name__)

_METHODS = {"PLAY_BASED", "DRAWING", "INTERVIEW"}
_WISH_TYPES = {"TRAVEL", "MEET_PERSON", "RECEIVE_ITEM", "BE_SOMETHING"}

PLAY_ONLY_BELOW_MONTHS = 72
INTERVIEW_FROM_MONTHS = 156


@bp.post("/wish-grant/wish-visits")
@require_roles("Volunteer")
def create_visit():
    body = body_json()
    team_id = req_str(body, "wish_team_id")
    start = req_datetime(body, "scheduled_start")
    end = req_datetime(body, "scheduled_end")
    method = req_enum(body, "visit_method", _METHODS)
    if end <= start:
        bad("scheduled_end must be strictly after scheduled_start")

    team = STORE["teams"].get(team_id)
    if team is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WishTeam not found")
    if team["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_TEAM_STATE", 409,
            "Team is not ACTIVE",
        )
    # Half-open overlap against the team's other SCHEDULED visits;
    # adjacency (s == e2 or e == s2) is allowed.
    for v in STORE["visits"].values():
        if v["wish_team_id"] != team["id"] or v["status"] != "SCHEDULED":
            continue
        if start < v["scheduled_end"] and v["scheduled_start"] < end:
            raise ApiError(
                "ERR_TEAM_SCHEDULE_OVERLAP", 409,
                "Visit window overlaps another scheduled visit of the team",
            )
    if g.user_id not in (team["lead_volunteer_id"], team["second_volunteer_id"]):
        raise ApiError(
            "ERR_NOT_TEAM_MEMBER", 403,
            "Acting volunteer is not on this team",
        )

    wish = STORE["wishes"][team["wish_id"]]
    child = STORE["children"][wish["child_id"]]
    dob = parse_date(child["date_of_birth"], "date_of_birth")
    m = age_months(dob, start.date())
    if m < PLAY_ONLY_BELOW_MONTHS:
        allowed = {"PLAY_BASED"}
    elif m < INTERVIEW_FROM_MONTHS:
        allowed = {"PLAY_BASED", "DRAWING"}
    else:
        allowed = {"INTERVIEW"}
    if method not in allowed:
        raise ApiError(
            "ERR_AGE_INAPPROPRIATE_METHOD", 422,
            "visit_method %s not allowed at age %d months" % (method, m),
        )

    v = new_entity(
        wish_team_id=team["id"],
        scheduled_start=start,
        scheduled_end=end,
        visit_method=method,
        status="SCHEDULED",
        captured_true_wish=None,
        captured_wish_type=None,
    )
    STORE["visits"][v["id"]] = v
    return created(ser_visit(v))


@bp.get("/wish-grant/wish-teams/<tid>/visits")
@require_roles("WishCoordinator", "Volunteer", "ChapterDirector")
def list_team_visits(tid):
    team = STORE["teams"].get(tid)
    if team is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WishTeam not found")
    limit, offset = pagination()
    items = sorted(STORE["visits"].values(), key=lambda e: e["created_at"])
    items = [v for v in items if v["wish_team_id"] == tid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_visit(v) for v in page], total, limit, offset, has_more)


@bp.post("/wish-grant/wish-visits/<vid>/conclude")
@require_roles("Volunteer")
def conclude_visit(vid):
    v = STORE["visits"].get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WishVisit not found")
    body = body_json()
    outcome = req_enum(body, "outcome", {"COMPLETED", "NO_SHOW"})
    captured_true_wish = None
    captured_wish_type = None
    if outcome == "COMPLETED":
        captured_true_wish = req_str(body, "captured_true_wish")
        captured_wish_type = req_enum(body, "captured_wish_type", _WISH_TYPES)

    team = STORE["teams"][v["wish_team_id"]]
    if team["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_TEAM_STATE", 409,
            "Team is not ACTIVE",
        )
    if v["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_VISIT_STATE", 409,
            "Visit is not SCHEDULED",
        )
    if g.user_id not in (team["lead_volunteer_id"], team["second_volunteer_id"]):
        raise ApiError(
            "ERR_NOT_TEAM_MEMBER", 403,
            "Acting volunteer is not on this team",
        )

    if outcome == "NO_SHOW":
        v["status"] = "NO_SHOW"
        touch(v)
        return ok(ser_visit(v))

    # COMPLETED: drive the determination cascade.
    v["status"] = "COMPLETED"
    v["captured_true_wish"] = captured_true_wish
    v["captured_wish_type"] = captured_wish_type
    touch(v)

    wish = STORE["wishes"][team["wish_id"]]
    wish["wish_type"] = captured_wish_type
    wish["true_wish_description"] = captured_true_wish
    wish["determined_at"] = now()
    wish["status"] = "DETERMINED"
    touch(wish)

    team["status"] = "COMPLETED"
    touch(team)

    for other in STORE["visits"].values():
        if (
            other["wish_team_id"] == team["id"]
            and other["id"] != v["id"]
            and other["status"] == "SCHEDULED"
        ):
            other["status"] = "CANCELLED"
            touch(other)

    return ok(ser_visit(v))

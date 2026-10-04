"""Member endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch
from errors import (
    ApiError,
    ERR_CLUB_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from logic import get_member, is_int, serialize, sort_items
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    require_fields(body, ["tier", "birth_year", "home_club_id"])
    if body["tier"] not in ("CLUB", "PLUS"):
        raise ApiError(ERR_INVALID_REQUEST, "tier must be CLUB or PLUS.", 400)
    if not is_int(body["birth_year"]) or body["birth_year"] < 1000 or body["birth_year"] > 9999:
        raise ApiError(ERR_INVALID_REQUEST, "birth_year must be a 4-digit integer.", 400)
    if body["home_club_id"] not in STORE.clubs:
        raise ApiError(ERR_CLUB_NOT_FOUND, "home_club_id does not reference an existing club.", 404)
    tender_status = body.get("tender_status", "OK")
    if tender_status not in ("OK", "DECLINED"):
        raise ApiError(ERR_INVALID_REQUEST, "tender_status must be OK or DECLINED.", 400)

    member = new_entity()
    member.update({
        "tier": body["tier"],
        "birth_year": body["birth_year"],
        "home_club_id": body["home_club_id"],
        "status": "ACTIVE",
        "tender_status": tender_status,
        "cash_rewards_pending_cents": 0,
        "cash_rewards_posted_cents": 0,
        "lifetime_charged_cents": 0,
        "unscanned_strikes": 0,
    })
    STORE.members[member["id"]] = member
    return success(serialize(member), status=201)


@bp.get("/members/<member_id>")
def get_member_route(member_id):
    get_context()
    return success(serialize(get_member(member_id)))


@bp.get("/members")
def list_members():
    get_context()
    limit, offset = get_pagination(request.args)
    members = list(STORE.members.values())
    for f in ("home_club_id", "tier", "status"):
        v = request.args.get(f)
        if v is not None:
            members = [m for m in members if m[f] == v]
    members = sort_items(members)
    page, page_meta = paginate(members, limit, offset)
    return success([serialize(m) for m in page], response_type="array", pagination=page_meta)


@bp.get("/members/<member_id>/scan-sessions")
def member_sessions(member_id):
    get_context()
    member = get_member(member_id)
    limit, offset = get_pagination(request.args)
    sessions = [s for s in STORE.sessions.values() if s["member_id"] == member["id"]]
    v = request.args.get("status")
    if v is not None:
        sessions = [s for s in sessions if s["status"] == v]
    sessions = sort_items(sessions)
    page, page_meta = paginate(sessions, limit, offset)
    return success([serialize(s) for s in page], response_type="array", pagination=page_meta)


@bp.post("/members/<member_id>/reinstate")
def reinstate(member_id):
    _, role = get_context()
    require_role(role, ["LossPreventionOfficer"])
    member = get_member(member_id)
    member["status"] = "ACTIVE"
    member["unscanned_strikes"] = 0
    touch(member)
    return success(serialize(member))


@bp.post("/members/<member_id>/rewards/settle")
def settle_rewards(member_id):
    from logic import REWARD_RATE
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    member = get_member(member_id)
    delta = 0
    if member["tier"] == "PLUS":
        for session in STORE.sessions.values():
            if session["member_id"] != member["id"]:
                continue
            if session["rewards_settled"]:
                continue
            if session["status"] not in ("PAID", "EXIT_PENDING", "FLAGGED", "EXITED"):
                continue
            delta += (session["qualifying_cents"] * REWARD_RATE) // 100
            session["rewards_settled"] = True
            touch(session)
    member["cash_rewards_posted_cents"] += delta
    touch(member)
    return success(serialize(member))

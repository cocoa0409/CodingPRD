"""Volunteer registration, listing, read, and the one-step status ladder."""

from flask import Blueprint, request

from auth import require_roles
from db import STORE, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_volunteer
from util import body_json, req_str, req_enum, pagination, paginate

bp = Blueprint("volunteers", __name__)

_NEXT_STATE = {"APPLIED": "TRAINED", "TRAINED": "ACTIVE", "ACTIVE": "INACTIVE"}
_ALL_STATES = {"APPLIED", "TRAINED", "ACTIVE", "INACTIVE"}


@bp.post("/wish-grant/volunteers")
@require_roles("WishCoordinator")
def create_volunteer():
    body = body_json()
    chapter_id = req_str(body, "chapter_id")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    if chapter_id not in STORE["chapters"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Chapter not found")
    v = new_entity(
        chapter_id=chapter_id,
        full_name=full_name,
        email=email,
        status="APPLIED",
    )
    STORE["volunteers"][v["id"]] = v
    return created(ser_volunteer(v))


@bp.get("/wish-grant/volunteers")
@require_roles("WishCoordinator", "ChapterDirector", "NationalDirector")
def list_volunteers():
    limit, offset = pagination()
    items = sorted(STORE["volunteers"].values(), key=lambda e: e["created_at"])
    chapter_id = request.args.get("chapter_id")
    status = request.args.get("status")
    if chapter_id is not None:
        items = [v for v in items if v["chapter_id"] == chapter_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_volunteer(v) for v in page], total, limit, offset, has_more)


@bp.get("/wish-grant/volunteers/<vid>")
@require_roles("WishCoordinator", "ChapterDirector", "NationalDirector", "Volunteer")
def get_volunteer(vid):
    v = STORE["volunteers"].get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Volunteer not found")
    return ok(ser_volunteer(v))


@bp.post("/wish-grant/volunteers/<vid>/transition")
@require_roles("WishCoordinator")
def transition_volunteer(vid):
    v = STORE["volunteers"].get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Volunteer not found")
    body = body_json()
    target = req_enum(body, "target_state", _ALL_STATES)
    nxt = _NEXT_STATE.get(v["status"])
    if nxt is None or target != nxt:
        raise ApiError(
            "ERR_INVALID_VOLUNTEER_STATE", 409,
            "Volunteer cannot transition from %s to %s" % (v["status"], target),
        )
    v["status"] = target
    touch(v)
    return ok(ser_volunteer(v))

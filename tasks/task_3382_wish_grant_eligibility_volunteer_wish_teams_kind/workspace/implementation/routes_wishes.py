"""Wish list / read."""

from flask import Blueprint, request

from auth import require_roles
from db import STORE
from errors import ApiError
from resp import ok, list_resp
from serialize import ser_wish
from util import pagination, paginate

bp = Blueprint("wishes", __name__)

_ROLES = (
    "WishCoordinator", "ChapterDirector", "NationalDirector",
    "EligibilityReviewer", "Volunteer",
)


@bp.get("/wish-grant/wishes")
@require_roles(*_ROLES)
def list_wishes():
    limit, offset = pagination()
    items = sorted(STORE["wishes"].values(), key=lambda e: e["created_at"])
    child_id = request.args.get("child_id")
    chapter_id = request.args.get("chapter_id")
    referral_id = request.args.get("referral_id")
    status = request.args.get("status")
    wish_type = request.args.get("wish_type")
    urgency = request.args.get("urgency")
    if child_id is not None:
        items = [w for w in items if w["child_id"] == child_id]
    if chapter_id is not None:
        items = [w for w in items if w["chapter_id"] == chapter_id]
    if referral_id is not None:
        items = [w for w in items if w["referral_id"] == referral_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if wish_type is not None:
        items = [w for w in items if w["wish_type"] == wish_type]
    if urgency is not None:
        items = [w for w in items if w["urgency"] == urgency]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_wish(w) for w in page], total, limit, offset, has_more)


@bp.get("/wish-grant/wishes/<wid>")
@require_roles(*_ROLES)
def get_wish(wid):
    w = STORE["wishes"].get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    return ok(ser_wish(w))

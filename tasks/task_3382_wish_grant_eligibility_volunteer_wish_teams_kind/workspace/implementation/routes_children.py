"""Child read/list and treatment-window wholesale replacement."""

from flask import Blueprint, request

from auth import require_roles
from db import STORE, touch
from errors import ApiError
from resp import ok, list_resp
from serialize import ser_child
from util import body_json, req_field, parse_date, pagination, paginate, bad

bp = Blueprint("children", __name__)


@bp.get("/wish-grant/children")
@require_roles("WishCoordinator", "EligibilityReviewer", "MedicalProvider", "ChapterDirector")
def list_children():
    limit, offset = pagination()
    items = sorted(STORE["children"].values(), key=lambda e: e["created_at"])
    chapter_id = request.args.get("chapter_id")
    if chapter_id is not None:
        items = [c for c in items if c["chapter_id"] == chapter_id]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_child(c) for c in page], total, limit, offset, has_more)


@bp.get("/wish-grant/children/<cid>")
@require_roles(
    "WishCoordinator", "EligibilityReviewer", "MedicalProvider",
    "ChapterDirector", "Volunteer",
)
def get_child(cid):
    c = STORE["children"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Child not found")
    return ok(ser_child(c))


@bp.patch("/wish-grant/children/<cid>")
@require_roles("MedicalProvider")
def patch_child(cid):
    c = STORE["children"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Child not found")
    body = body_json()
    windows = req_field(body, "treatment_windows")
    if not isinstance(windows, list):
        bad("treatment_windows must be an array")
    validated = []
    for entry in windows:
        try:
            if not isinstance(entry, dict):
                raise ValueError
            s_raw = entry["start_date"]
            e_raw = entry["end_date"]
            s = parse_date(s_raw, "start_date")
            e = parse_date(e_raw, "end_date")
        except (KeyError, ValueError, ApiError):
            raise ApiError(
                "ERR_TREATMENT_WINDOW_INVALID", 422,
                "Each treatment window needs valid start_date <= end_date",
            )
        if s > e:
            raise ApiError(
                "ERR_TREATMENT_WINDOW_INVALID", 422,
                "treatment window start_date must be <= end_date",
            )
        validated.append({"start_date": s_raw, "end_date": e_raw})
    c["treatment_windows"] = validated
    touch(c)
    return ok(ser_child(c))

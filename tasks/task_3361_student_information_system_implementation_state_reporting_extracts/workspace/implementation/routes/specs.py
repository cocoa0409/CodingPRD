"""StateCollectionSpec endpoints: create/list, publish, retire."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import spec_out
from validators import (body, opt_int, opt_num, req_dt, req_enum, req_obj,
                        req_str)

bp = Blueprint("specs", __name__)

FUNDING_METHODS = {"ADM", "COUNT_DATE"}


def _get_spec_or_404(sid):
    s = store["specs"].get(sid)
    if not s:
        raise ApiError("ERR_SPEC_NOT_FOUND", 404,
                       "No collection spec with the given id")
    return s


@bp.post("/sis/collection-specs")
def create_spec():
    _uid, role = auth_context()
    data = body()
    state_code = req_str(data, "state_code")
    funding_method = req_enum(data, "funding_method", FUNDING_METHODS)
    attendance_code_map = req_obj(data, "attendance_code_map")
    discipline_code_map = req_obj(data, "discipline_code_map")
    program_code_map = req_obj(data, "program_code_map")
    opens_at = req_dt(data, "submission_window_opens_at")
    closes_at = req_dt(data, "submission_window_closes_at")
    chronic_absence_threshold = opt_num(data, "chronic_absence_threshold", 0.10)
    auto_withdraw_streak = opt_int(data, "auto_withdraw_streak", 10)
    min_membership_days = opt_int(data, "min_membership_days", 10)
    if auto_withdraw_streak <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "auto_withdraw_streak must be > 0")
    if min_membership_days < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "min_membership_days must be >= 0")
    require_role(role, {"PlatformAdmin"})
    if not (closes_at > opens_at):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "submission_window_closes_at must be after submission_window_opens_at")
    s = {"id": new_id(), "state_code": state_code,
         "funding_method": funding_method,
         "attendance_code_map": attendance_code_map,
         "discipline_code_map": discipline_code_map,
         "program_code_map": program_code_map,
         "submission_window_opens_at": opens_at,
         "submission_window_closes_at": closes_at,
         "chronic_absence_threshold": chronic_absence_threshold,
         "auto_withdraw_streak": auto_withdraw_streak,
         "min_membership_days": min_membership_days,
         "status": "DRAFT"}
    stamp_new(s)
    store["specs"][s["id"]] = s
    return ok_obj(spec_out(s), 201)


@bp.get("/sis/collection-specs")
def list_specs():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    items = [s for s in store["specs"].values()
             if (state_code is None or s["state_code"] == state_code)
             and (status is None or s["status"] == status)]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([spec_out(s) for s in page], total, limit, offset)


@bp.post("/sis/collection-specs/<sid>/publish")
def publish_spec(sid):
    _uid, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    s = _get_spec_or_404(sid)
    if s["status"] != "DRAFT":
        raise ApiError("ERR_SPEC_NOT_DRAFT", 409,
                       "Publish requires spec DRAFT")
    if not (s["attendance_code_map"] and s["discipline_code_map"]
            and s["program_code_map"]):
        raise ApiError("ERR_SPEC_MAPS_INCOMPLETE", 409,
                       "Publish requires all three code maps non-empty")
    # Auto-retire cascade: any other PUBLISHED spec of the same state_code.
    for other in store["specs"].values():
        if (other["id"] != s["id"] and other["state_code"] == s["state_code"]
                and other["status"] == "PUBLISHED"):
            other["status"] = "RETIRED"
            touch(other)
    s["status"] = "PUBLISHED"
    touch(s)
    return ok_obj(spec_out(s))


@bp.post("/sis/collection-specs/<sid>/retire")
def retire_spec(sid):
    _uid, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    s = _get_spec_or_404(sid)
    if s["status"] != "PUBLISHED":
        raise ApiError("ERR_SPEC_NOT_PUBLISHED", 409,
                       "Retire requires spec PUBLISHED")
    s["status"] = "RETIRED"
    touch(s)
    return ok_obj(spec_out(s))

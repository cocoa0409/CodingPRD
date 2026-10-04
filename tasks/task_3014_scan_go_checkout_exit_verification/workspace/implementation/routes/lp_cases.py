"""Loss prevention case endpoints."""

from flask import Blueprint, request

from db import STORE, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_LP_CASE_NOT_OPEN,
    ERR_SO_DUTY_VIOLATION,
)
from logic import get_lp_case, serialize, sort_items
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("lp_cases", __name__)


@bp.get("/loss-prevention-cases/<case_id>")
def get_case(case_id):
    get_context()
    return success(serialize(get_lp_case(case_id)))


@bp.get("/loss-prevention-cases")
def list_cases():
    get_context()
    limit, offset = get_pagination(request.args)
    cases = list(STORE.lp_cases.values())
    for f in ("session_id", "member_id", "club_id", "status"):
        v = request.args.get(f)
        if v is not None:
            cases = [c for c in cases if c[f] == v]
    cases = sort_items(cases)
    page, page_meta = paginate(cases, limit, offset)
    return success([serialize(c) for c in page], response_type="array", pagination=page_meta)


@bp.post("/loss-prevention-cases/<case_id>/acknowledge")
def acknowledge(case_id):
    _, role = get_context()
    require_role(role, ["LossPreventionOfficer"])
    case = get_lp_case(case_id)
    if case["status"] != "OPEN":
        raise ApiError(ERR_LP_CASE_NOT_OPEN,
                       "acknowledge requires an OPEN case.", 409)
    case["status"] = "ACKNOWLEDGED"
    touch(case)
    return success(serialize(case))


@bp.post("/loss-prevention-cases/<case_id>/escalate")
def escalate(case_id):
    _, role = get_context()
    require_role(role, ["LossPreventionOfficer"])
    case = get_lp_case(case_id)
    if case["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError(ERR_LP_CASE_NOT_OPEN,
                       "escalate requires an OPEN or ACKNOWLEDGED case.", 409)
    case["status"] = "ESCALATED"
    touch(case)
    return success(serialize(case))


@bp.post("/loss-prevention-cases/<case_id>/resolve")
def resolve(case_id):
    user_id, role = get_context()
    require_role(role, ["LossPreventionOfficer"])
    case = get_lp_case(case_id)
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("DISMISSED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "outcome must be DISMISSED or CONFIRMED.", 400)
    if case["status"] == "RESOLVED":
        raise ApiError(ERR_LP_CASE_NOT_OPEN,
                       "resolve attempted on a RESOLVED case.", 409)
    if case["flagging_associate_id"] is not None and user_id == case["flagging_associate_id"]:
        raise ApiError(ERR_SO_DUTY_VIOLATION,
                       "The flagging associate cannot resolve their own case.", 403)
    case["outcome"] = outcome
    case["status"] = "RESOLVED"
    touch(case)
    if outcome == "DISMISSED":
        member = STORE.members[case["member_id"]]
        member["unscanned_strikes"] = max(0, member["unscanned_strikes"] - 1)
        touch(member)
    return success(serialize(case))

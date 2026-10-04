# routes/judges.py — judge administration.
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_judge
from constants import ROLE_COURT_ADMINISTRATOR
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_int, fk, pagination_params,
                    filter_param, sorted_page)

bp = Blueprint("judges", __name__)


@bp.post("/judges")
def create_judge():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # tier 3: body foreign keys in declared input order
    court_id = fk(body, "court_id")
    court = db.courts.get(court_id) if court_id is not None else None
    if court_id is not None and court is None:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    # tier 10: shape
    court_id = req_str(body, "court_id")
    if court_id not in db.courts:
        # unreachable in practice (tier 3 already fired); kept for safety
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    full_name = req_str(body, "full_name")
    max_pending = req_int(body, "max_pending_cases", min_v=1)
    judge = {
        "id": str(uuid.uuid4()),
        "court_id": court_id,
        "full_name": full_name,
        "max_pending_cases": max_pending,
    }
    db.stamp_new(judge)
    db.stamp_common(judge)
    db.judges[judge["id"]] = judge
    return success(serialize_judge(judge), response_type="object", status=201)


@bp.get("/judges")
def list_judges():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.judges.values())
    court_id = filter_param("court_id")
    if court_id is not None:
        records = [j for j in records if j["court_id"] == court_id]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_judge(j) for j in page], total, limit,
                         offset)


@bp.get("/judges/<judgeId>")
def get_judge(judgeId):
    get_auth()  # all roles
    judge = db.judges.get(judgeId)
    if judge is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", "Judge id does not exist")
    return success(serialize_judge(judge), response_type="object", status=200)

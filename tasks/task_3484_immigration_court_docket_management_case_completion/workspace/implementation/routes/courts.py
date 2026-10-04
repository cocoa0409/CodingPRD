# routes/courts.py — court administration and docket-review runs.
import uuid

from flask import Blueprint

import db
import docket
from auth import get_auth, require_role, ALL_ROLES
from computed import serialize_court, serialize_docket_review
from constants import ROLE_COURT_ADMINISTRATOR
from envelope import success
from errors import ApiError
from inputs import get_body, req_str, req_int, fk

bp = Blueprint("courts", __name__)


@bp.post("/courts")
def create_court():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # tier 9 (uniqueness) precedes tier-10 shape per PRD §2.6; evaluate it on
    # the raw value whenever it is well-formed enough to compare.
    code = fk(body, "court_code")
    if code is not None and any(c["court_code"] == code
                                for c in db.courts.values()):
        raise ApiError("ERR_COURT_CODE_NOT_UNIQUE",
                       "court_code '%s' already exists" % code)
    # tier 10: shape
    court_code = req_str(body, "court_code")
    name = req_str(body, "name")
    city = req_str(body, "city")
    goal = req_int(body, "annual_completion_goal", min_v=1)
    cap = req_int(body, "detained_daily_hearing_capacity", min_v=0)
    court = {
        "id": str(uuid.uuid4()),
        "court_code": court_code,
        "name": name,
        "city": city,
        "annual_completion_goal": goal,
        "detained_daily_hearing_capacity": cap,
    }
    db.stamp_new(court)
    db.stamp_common(court)
    db.courts[court["id"]] = court
    return success(serialize_court(court), response_type="object", status=201)


@bp.get("/courts/<courtId>")
def get_court(courtId):
    get_auth()  # all roles
    court = db.courts.get(courtId)
    if court is None:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    return success(serialize_court(court), response_type="object", status=200)


@bp.post("/courts/<courtId>/docket-reviews")
def run_review(courtId):
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    court = db.courts.get(courtId)
    if court is None:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    review = docket.run_docket_review(court)
    return success(serialize_docket_review(review), response_type="object",
                   status=201)

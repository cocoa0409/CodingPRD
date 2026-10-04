# routes/programs.py — Legal Orientation Programs (LOP).
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_program
from constants import ROLE_COURT_ADMINISTRATOR
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_int, opt_bool, fk, is_int, invalid,
                    pagination_params, filter_param, sorted_page)

bp = Blueprint("programs", __name__)


@bp.post("/orientation-programs")
def create_program():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # tier 3
    court_id = fk(body, "court_id")
    if court_id is not None and court_id not in db.courts:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    # tier 10
    court_id = req_str(body, "court_id")
    if court_id not in db.courts:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    program_name = req_str(body, "program_name")
    coverage_pct = req_int(body, "coverage_pct", min_v=0, max_v=100)
    active = opt_bool(body, "active", default=True)
    p = {
        "id": str(uuid.uuid4()),
        "court_id": court_id,
        "program_name": program_name,
        "coverage_pct": coverage_pct,
        "active": active,
    }
    db.stamp_new(p)
    db.stamp_common(p)
    db.programs[p["id"]] = p
    return success(serialize_program(p), response_type="object", status=201)


@bp.get("/orientation-programs")
def list_programs():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.programs.values())
    court_id = filter_param("court_id")
    if court_id is not None:
        records = [p for p in records if p["court_id"] == court_id]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_program(p) for p in page], total, limit,
                         offset)


@bp.get("/orientation-programs/<programId>")
def get_program(programId):
    get_auth()  # all roles
    p = db.programs.get(programId)
    if p is None:
        # generic 404 for LegalOrientationProgram references (PRD §2.6 tier 3)
        raise ApiError("ERR_NOT_FOUND",
                       "LegalOrientationProgram id does not exist")
    return success(serialize_program(p), response_type="object", status=200)


@bp.post("/orientation-programs/<programId>/set-coverage")
def set_coverage(programId):
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    p = db.programs.get(programId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND",
                       "LegalOrientationProgram id does not exist")
    body = get_body()
    # tier 10: optional coverage_pct / active, each validated when present
    if "coverage_pct" in body and body["coverage_pct"] is not None:
        v = body["coverage_pct"]
        if not is_int(v) or v < 0 or v > 100:
            invalid("field 'coverage_pct' must be an integer in 0..100")
        p["coverage_pct"] = v
    if "active" in body and body["active"] is not None:
        if not isinstance(body["active"], bool):
            invalid("field 'active' must be a boolean")
        p["active"] = body["active"]
    # increments version by 1; only hearings created afterwards re-derive
    # the LOP duration factor (PRD §3.1)
    db.touch(p)
    return success(serialize_program(p), response_type="object", status=200)

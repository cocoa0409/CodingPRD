"""Engineer registration endpoint (PRD 3.5)."""
import uuid

from flask import Blueprint

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, get_body
from response import success

bp = Blueprint("engineers", __name__)


@bp.post("/lab/engineers")
def create_engineer():
    authenticate({"ServiceDispatcher", "PlatformAdmin"})
    body = get_body()
    name = body.get("name")
    territory = body.get("territory_code")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "name is required")
    if not isinstance(territory, str) or not territory.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "territory_code is required")
    skills = body.get("skills")
    if (
        not isinstance(skills, list)
        or len(skills) == 0
        or any(s not in D.SKILLS for s in skills)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "skills must be a non-empty array of BREAK_FIX, PM, APP_SUPPORT, METHOD_DEV, INSTALL",
        )
    status = body.get("status", "ACTIVE")
    if status not in D.ENGINEER_STATUSES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "status must be one of ACTIVE, INACTIVE"
        )
    now = dbmod.now()
    eng = {
        "id": str(uuid.uuid4()),
        "name": name,
        "territory_code": territory,
        "skills": list(skills),
        "status": status,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.engineers[eng["id"]] = eng
    return success(D.engineer_json(eng), code=201)

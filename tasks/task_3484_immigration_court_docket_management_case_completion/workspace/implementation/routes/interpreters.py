# routes/interpreters.py — interpreter pool administration.
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_interpreter
from constants import ROLE_COURT_ADMINISTRATOR
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_int, req_lang_list, fk,
                    pagination_params, filter_param, sorted_page)

bp = Blueprint("interpreters", __name__)


@bp.post("/interpreters")
def create_interpreter():
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
    full_name = req_str(body, "full_name")
    language_codes = req_lang_list(body, "language_codes")
    cap = req_int(body, "daily_hearing_cap", min_v=1)
    it = {
        "id": str(uuid.uuid4()),
        "court_id": court_id,
        "full_name": full_name,
        "language_codes": list(language_codes),
        "daily_hearing_cap": cap,
    }
    db.stamp_new(it)
    db.stamp_common(it)
    db.interpreters[it["id"]] = it
    return success(serialize_interpreter(it), response_type="object",
                   status=201)


@bp.get("/interpreters")
def list_interpreters():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.interpreters.values())
    court_id = filter_param("court_id")
    if court_id is not None:
        records = [i for i in records if i["court_id"] == court_id]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_interpreter(i) for i in page], total,
                         limit, offset)


@bp.get("/interpreters/<interpreterId>")
def get_interpreter(interpreterId):
    get_auth()  # all roles
    it = db.interpreters.get(interpreterId)
    if it is None:
        raise ApiError("ERR_INTERPRETER_NOT_FOUND",
                       "Interpreter id does not exist")
    return success(serialize_interpreter(it), response_type="object",
                   status=200)

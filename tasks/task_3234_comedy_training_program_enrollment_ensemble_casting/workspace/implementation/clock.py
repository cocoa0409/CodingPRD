"""Logical clock test-driving endpoint."""
from flask import Blueprint
from store import store, parse_dt
from middleware import auth, json_body, require_fields
from response import success_obj
from errors import invalid_request

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["current_utc"])
    try:
        parse_dt(body["current_utc"])
    except Exception:
        invalid_request("current_utc must be an ISO 8601 datetime")
    store.clock_utc = body["current_utc"]
    return success_obj({"current_utc": store.clock_utc})

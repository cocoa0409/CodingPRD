"""Platform logical clock endpoint — mounted at the server root, deliberately
OUTSIDE the /gas-supply prefix (PRD 2.4)."""
from flask import Blueprint

from helpers import authenticate, require_role, json_body, v_dt, respond
from store import clock_set, parse_dt
from domain import sweep

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    raw = v_dt(body, "current_utc")
    dt = parse_dt(raw)
    clock_set(dt)
    sweep(dt)
    return respond({})

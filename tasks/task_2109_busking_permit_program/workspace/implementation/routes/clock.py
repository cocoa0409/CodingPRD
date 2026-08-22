"""The logical program clock (PRD section 2.5)."""
from flask import Blueprint, request

import db
from body import Body
from middleware import PERMIT_OFFICER, require_roles
from response import ok_object
from utils import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    target = body.req_dt("to_iso8601")
    previous = db.set_now(target)
    return ok_object({"current_utc": fmt_dt(db.now()), "previous_utc": fmt_dt(previous)})

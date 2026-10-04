# =============================================================================
# POST /_clock/set_current_utc — test-driving logical clock (roles: Any)
# =============================================================================
from flask import Blueprint

import db
from middleware import get_body, req_str
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    value = req_str(body, "current_utc")
    db.set_clock(value)
    return success_object({"current_utc": db.get_clock()}, 200)

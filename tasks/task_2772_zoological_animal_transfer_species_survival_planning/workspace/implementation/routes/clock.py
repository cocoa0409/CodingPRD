from flask import Blueprint

from core import auth, body, get_instant, ok, set_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@auth("AccreditationAdmin")
def set_current_utc():
    b = body()
    moment, _raw = get_instant(b, "current_utc", required=True)
    set_clock(moment)
    return ok({})

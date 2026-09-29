from flask import Blueprint

import middleware as mw
import response
import util

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    mw.auth("SystemAdmin")
    data = mw.body()
    instant = mw.req_instant(data, "current_utc")
    util.set_clock(instant)
    return response.ok({"current_utc": util.fmt_instant(instant)})

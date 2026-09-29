"""Logical clock control (PRD 2.4)."""
from flask import Blueprint

import store
import validation as v
from auth import REGULATOR, endpoint
from envelope import ok

bp = Blueprint("misc", __name__)


@bp.post("/epr/_clock/set_current_utc")
@endpoint([REGULATOR])
def set_current_utc():
    body = v.body()
    moment = v.req_instant(body, "current_utc")
    store.set_clock(moment)
    return ok({"current_utc": store.fmt_instant(moment)})

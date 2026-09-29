"""The logical clock (PRD 2.4)."""

from flask import Blueprint

import auth
import envelope
import shape
from store import set_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.gate(("ProgramManager",))
    data = shape.body()
    instant = shape.req_dt(data, "current_utc")
    set_clock(instant)
    return envelope.ok({})

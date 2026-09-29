"""The logical-clock test surface (PRD section 2.4)."""

from flask import Blueprint

import store
from auth import ALL_ROLES, endpoint
from envelope import single
from validators import body, instant_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc(user_id, role):
    payload = body()
    moment = instant_field(payload, "current_utc")
    store.set_clock(moment)
    return single({})

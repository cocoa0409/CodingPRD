"""The logical clock (PRD 2.5): every role may drive it, no entity is mutated."""

from flask import Blueprint

import authz
import envelope
import store
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authz.actor(authz.ROLES)
    payload = validate.body()
    instant = validate.instant(payload, "current_utc")
    store.set_clock(instant)
    return envelope.object_response({"current_utc": store.iso(instant)})

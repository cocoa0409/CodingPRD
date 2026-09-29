"""Test-driving logical clock (PRD section 2.10)."""

from flask import Blueprint

import store
import validate
from auth import require_roles
from envelope import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ParkOpsAdmin")
def set_current_utc():
    data = validate.body()
    moment = validate.instant_field(data, "to_iso8601")
    store.set_clock(moment)
    return ok({"current_utc": store.now_iso()})

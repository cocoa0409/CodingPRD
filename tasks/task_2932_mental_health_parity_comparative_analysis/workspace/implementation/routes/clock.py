"""The logical compliance clock (PRD 2.5)."""

from flask import Blueprint

import recompute
import shape
from auth import guard
from enums import ALL_ROLES
from envelope import success
from errors import ApiError
from store import clock_now, clock_now_iso, db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(*ALL_ROLES)
def set_current_utc():
    payload = shape.body()
    _text, moment = shape.req_instant(payload, "current_utc")
    # Step 33: the clock is monotonic.
    if moment <= clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.clock = moment
    administrator_count, plan_year_count = recompute.recompute_world()
    return success({
        "current_utc": clock_now_iso(),
        "recomputed_administrator_count": administrator_count,
        "recomputed_plan_year_count": plan_year_count,
    })

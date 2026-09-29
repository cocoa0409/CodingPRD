from flask import Blueprint

import cascades
from common import (body, clock_set, envelope_object, fmt_instant, get_instant,
                    require)

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    """The administrative clock.  Deliberately mounted outside /inland-marine."""
    require("UnderwritingManager")
    b = body()
    current_utc = get_instant(b, "current_utc")
    clock_set(current_utc)
    # Expiry is not requested, it is discovered when the clock moves.
    expired_policy_ids, expired_floater_ids = cascades.expire_policies_and_floaters()
    return envelope_object({
        "current_utc": fmt_instant(current_utc),
        "expired_policy_ids": expired_policy_ids,
        "expired_floater_ids": expired_floater_ids,
    }, 200)

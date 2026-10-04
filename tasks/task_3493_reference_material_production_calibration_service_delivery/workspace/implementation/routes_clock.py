"""The logical clock test-driving endpoint — mounted at the server root
(NOT under /metrology), per PRD section 2.4. Setting the clock fires the
certificate-expiration sweep."""

from flask import Blueprint

from db import get_clock, set_clock
from engine import expiration_sweep
from util import auth_context, body, ok_object, render_domain, require_role, v_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    target = v_dt(b, "to_iso8601")
    set_clock(target)
    expired, held = expiration_sweep()
    return ok_object(
        {
            "current_utc": render_domain(get_clock()),
            "expired_certificate_count": expired,
            "transitioned_lot_count": held,
        },
        200,
    )

"""Platform-only logical clock driver (PRD section 2.5)."""
from flask import Blueprint

import constants as C
import logical_clock
import response
import services
import validate as v
from middleware import endpoint

bp = Blueprint("platform", __name__)


@bp.post("/community-care/_clock/set_current_utc")
@endpoint([C.ROLE_PLATFORM_ADMIN])
def set_clock(user_id, role):
    b = v.body()
    to_dt = v.req_datetime(b, "to_iso8601")
    logical_clock.set_current(to_dt)
    # The three sweeps run in their pinned order on every set:
    # (1) episode expiry, (2) documentation overdue + suspension cascade,
    # (3) auto-close.
    services.run_sweeps()
    return response.ok({"current_utc": logical_clock.now_iso()})

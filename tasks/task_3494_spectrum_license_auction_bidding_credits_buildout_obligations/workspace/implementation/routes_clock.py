"""POST /_clock/set_current_utc — deliberately mounted OUTSIDE the
/spectrum-auctions prefix (PRD §2.4). Sets the logical clock and runs the
maintenance sweeps. Restricted to AuctionAdmin."""
from flask import Blueprint

import store
import sweeps
from errors import success
from helpers import auth, require_role, body, req_present, as_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    target = as_datetime(req_present(b, "to_iso8601"), "to_iso8601")
    store.set_clock(target)
    sweeps.run_clock_sweeps()
    return success({"current_utc": store.render_domain(store.now())}, 200)

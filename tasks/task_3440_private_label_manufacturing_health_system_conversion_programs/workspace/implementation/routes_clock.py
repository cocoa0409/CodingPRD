"""The logical clock test-driving endpoint (PRD 2.4).

Mounted OUTSIDE the /supply business prefix: POST /_clock/set_current_utc.
"""
from flask import Blueprint

import db
import helpers as H

bp = Blueprint('clock', __name__)


@bp.post('/_clock/set_current_utc')
def set_current_utc():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    body = H.get_body()
    dt = H.v_datetime(H.required(body, 'to_iso8601'), 'to_iso8601')
    db.set_clock(dt)
    return H.success({'current_utc': db.clock_iso()}, 200)

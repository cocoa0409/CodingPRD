"""Logical clock endpoint (PRD 2.4): advance time and run scheduled sweeps."""
from flask import Blueprint

import cascade
import db
from errors import ERR_VALIDATION, ApiError
from middleware import _is_str, get_body, require_roles, validate_body
from response import success

bp = Blueprint('clock', __name__)


@bp.post('/ja-programs/_clock/set_current_utc')
def set_current_utc():
    require_roles('PlatformAdmin')
    body = get_body()
    validate_body(body, {'to_iso8601': (True, _is_str)})
    target = db.parse_datetime(body['to_iso8601'])
    if target is None:
        raise ApiError(ERR_VALIDATION, 'to_iso8601 must be a valid ISO 8601 timestamp', 400)
    db.set_clock(target)
    cascade.run_sweeps()
    return success({'current_utc': db.render_dt(db.CLOCK['now'])})

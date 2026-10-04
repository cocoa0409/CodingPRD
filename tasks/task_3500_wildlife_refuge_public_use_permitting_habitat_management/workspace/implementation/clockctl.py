"""The logical clock control (PRD 2.5). This endpoint is deliberately OUTSIDE
the /refuge business surface: POST /_clock/set_current_utc (no prefix).
RefugeManager only; fires the five pinned auto-transition classes in order."""
from flask import Blueprint
import store
from envelope import ok, fail
from auth import endpoint
from util import get_body, parse_iso_dt
import engine

bp = Blueprint('clockctl', __name__)


@bp.route('/_clock/set_current_utc', methods=['POST'], strict_slashes=False)
@endpoint(['RefugeManager'])
def set_current_utc(role, uid):
    body = get_body()
    target = parse_iso_dt(body.get('to_iso8601'))
    if target is None:
        fail('ERR_INVALID_REQUEST', 'to_iso8601 is required and must be an ISO 8601 timestamp')
    engine.set_clock(target)
    return ok({'current_utc': store.render_clock()})

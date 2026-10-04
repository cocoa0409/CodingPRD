"""POST /_clock/set_current_utc"""

from flask import Blueprint, request

import db
from middleware import require_role
from response import success_object
from errors import err, ERR_INVALID_REQUEST
from services import core

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    dt = core.parse_dt(to_iso8601, "to_iso8601")
    db.set_clock(dt)
    expired_ids = core.sweep_expired_consents()
    # recompute all institution statuses (window aging)
    for inst in list(db.institutions.values()):
        core.recompute_institution_health(inst)
    return success_object({
        "now_iso8601": db.now_iso(),
        "expired_consent_ids": expired_ids,
    })

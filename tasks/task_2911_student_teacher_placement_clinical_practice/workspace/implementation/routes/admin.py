"""The administrative logical-clock endpoint (PRD 2.5)."""

from flask import Blueprint, request

import clock
import envelope
import shapes
from auth import endpoint

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdmin"])
def set_current_utc():
    body = shapes.body_of(request)
    current_utc = shapes.req_instant(body, "current_utc")
    clock.set_now(current_utc)
    return envelope.ok({})

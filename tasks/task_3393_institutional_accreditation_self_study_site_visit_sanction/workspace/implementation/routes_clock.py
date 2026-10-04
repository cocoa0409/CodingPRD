"""Logical clock administration (PRD §2.4)."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, _parse_iso_datetime
from errors import ERR_VALIDATION, raise_err
from helpers import get_body, req_string
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/accreditation/_clock/set_current_utc")
def set_current_utc():
    actor = authenticate()
    require_role(actor, ["CommissionAdmin"])
    body = get_body()
    raw = req_string(body, "to_iso8601")
    dt = _parse_iso_datetime(raw)
    if dt is None:
        raise_err(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime")
    STORE.set_clock(dt, raw)
    return success_object({"current_utc": STORE.clock_verbatim})

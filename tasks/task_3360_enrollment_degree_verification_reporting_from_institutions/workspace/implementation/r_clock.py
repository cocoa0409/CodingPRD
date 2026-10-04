"""Logical clock control (PRD §2.4): strictly-forward advance with the pinned
six-step transition processing order. Default: 2026-09-01T00:00:00Z.
"""
from flask import Blueprint

import cascade
import db
from auth import ROLE_CLEARINGHOUSE_OPS, authenticate, require_role
from core import ERR_VALIDATION, fmt_dt_sec, get_body, ok_object, raise_err, req_date

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    data = get_body()
    target = req_date(data, "to_iso8601")
    if not target > db.now():
        raise_err(ERR_VALIDATION, "to_iso8601 must be strictly later than the current logical time")
    cascade.process_clock(target)
    return ok_object({"current_utc": fmt_dt_sec(db.now())})

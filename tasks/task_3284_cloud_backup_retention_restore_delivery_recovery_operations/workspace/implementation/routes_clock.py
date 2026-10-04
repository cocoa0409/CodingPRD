"""Logical clock control (PRD 2.5)."""

from flask import Blueprint, request

import auth
from response import object_response
from store import store
from util import parse_instant, req_str

bp = Blueprint("clock", __name__, url_prefix="/backup-provider")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    body = request.get_json(silent=True) or {}
    instant = parse_instant(req_str(body, "current_utc"), "current_utc")
    store.set_clock(instant)
    return object_response({})
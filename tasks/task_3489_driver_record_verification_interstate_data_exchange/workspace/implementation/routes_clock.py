"""Logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

import store
import validation as v
from response import ok

bp = Blueprint("clock", __name__, url_prefix="/driver-exchange")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    data = v.body()
    store.db.clock = v.req_datetime(data, "to_iso8601")
    return ok({})

"""The logical clock and the migration-readiness projection."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import validate
from response import iso, num
from validate import SYSTEM_ADMIN

bp = Blueprint("misc", __name__, url_prefix=common.PREFIX)


@bp.post("/_clock/set_current_utc")
def set_clock():
    validate.authenticate([SYSTEM_ADMIN])
    body = validate.get_body()
    instant = validate.req_dt(body, "to_iso8601")
    db.store.clock = instant
    return response.ok({"current_utc": iso(instant)})


@bp.get("/migration-readiness")
def migration_readiness():
    validate.authenticate(common.ANY_ROLE)
    basis = validate.filter_enum("basis", enums.READINESS_BASES) or "STRICT"
    agency_id = validate.filter_str("agency_id")
    result = compute.migration_readiness(basis, agency_id)
    result["readiness_pct"] = num(result["readiness_pct"])
    return response.ok(result)

"""Settlement routes and the logical-clock control (PRD 3.9, 3.11)."""

from flask import Blueprint

from constants import ROLES
from errors import ERR_INVALID_REQUEST, ApiError
from routes import RawPayload, endpoint, json_body, query_params
from services import clock as clock_module
from services import settlement
from services.lookup import get_bridge_program, get_disbursement
from store import db
from timeutil import parse_iso
from validation import body_of, get_str

bp = Blueprint("settlements", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]
PROGRAM_ADMIN = ROLES[4]


# The summary path is registered before the ``{id}`` read so that
# ``/knock/disbursements/summary`` is never captured as an entity id.
@bp.get("/knock/disbursements/summary")
@endpoint([COORDINATOR, PROGRAM_ADMIN])
def summary(actor):
    params = query_params()
    program_id = params.get("bridge_program_id")
    if program_id:
        get_bridge_program(program_id)
    return RawPayload(settlement.summary(program_id))


@bp.post("/knock/disbursements")
@endpoint([COORDINATOR], status=201)
def record(actor):
    return settlement.record_disbursement(json_body())


@bp.get("/knock/disbursements")
@endpoint([COORDINATOR])
def list_disbursements(actor):
    params = query_params()
    records = db.all("disbursements")
    for field in ("bridge_program_id", "source_kind"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/disbursements/<disbursement_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, disbursement_id):
    return get_disbursement(disbursement_id)


@bp.post("/_clock/set_current_utc")
@endpoint([COORDINATOR])
def set_clock(actor):
    data = body_of(json_body())
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str) or parse_iso(to_iso8601) is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant.")
    current = clock_module.advance(to_iso8601)
    return RawPayload({"current_utc": current})
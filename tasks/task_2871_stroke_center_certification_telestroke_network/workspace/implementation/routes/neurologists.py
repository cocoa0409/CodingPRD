"""On-call neurologists and the availability dimension (PRD 3.1)."""
from flask import Blueprint

import db
import response as resp
from constants import ONCALL_STATES
from errors import fail
from middleware import (
    Field,
    STATE_CODE_PATTERN,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)

bp = Blueprint("neurologists", __name__)

CREATE_SPEC = [
    Field("full_name", "str", min_len=1, max_len=120),
    Field("home_center_id", "str"),
    Field("licensed_state_codes", "list", item_kind="str", non_empty_list=True,
          item_pattern=STATE_CODE_PATTERN),
    Field("board_certified", "bool"),
    Field("roster_rank", "int", minimum=1, maximum=999),
    Field("concurrent_consult_limit", "int", required=False, minimum=1, maximum=5,
          default=2),
]

STATE_SPEC = [Field("on_call_state", "str", enum=ONCALL_STATES)]

DECLARED_MOVES = {
    ("OFF_DUTY", "ON_CALL"),
    ("ON_CALL", "OFF_DUTY"),
    ("ON_CALL", "UNAVAILABLE"),
    ("UNAVAILABLE", "ON_CALL"),
}


@bp.route("/neurologists", methods=["POST"])
def create_neurologist():
    authenticate(("ProgramCoordinator",))
    body = read_body(CREATE_SPEC)
    center = load_ref("centers", body["home_center_id"])
    record = {
        "full_name": body["full_name"],
        "home_center_id": center["id"],
        "licensed_state_codes": list(body["licensed_state_codes"]),
        "board_certified": body["board_certified"],
        "roster_rank": body["roster_rank"],
        "concurrent_consult_limit": body["concurrent_consult_limit"],
        "on_call_state": "OFF_DUTY",
        "active_consult_count": 0,
        "last_consult_completed_at": None,
        "completed_consult_count": 0,
    }
    db.insert("neurologists", record)
    return resp.object_response(record, 201)


@bp.route("/neurologists/<record_id>", methods=["GET"])
def read_neurologist(record_id):
    authenticate("any")
    return resp.object_response(load_path("neurologists", record_id))


@bp.route("/neurologists", methods=["GET"])
def list_neurologists():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("neurologists"), {
        "home_center_id": "home_center_id",
        "on_call_state": "on_call_state",
        "board_certified": "board_certified",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/neurologists/<record_id>/on-call-state", methods=["POST"])
def move_on_call_state(record_id):
    authenticate(("Neurologist", "ProgramCoordinator"))
    record = load_path("neurologists", record_id)
    body = read_body(STATE_SPEC)
    target = body["on_call_state"]
    current = record["on_call_state"]
    if (current, target) not in DECLARED_MOVES:
        fail("ERR_INVALID_ONCALL_TRANSITION",
             "%s -> %s is not a declared availability move." % (current, target))
    if current == "OFF_DUTY" and target == "ON_CALL":
        center = db.get("centers", record["home_center_id"])
        if center is None or center["certification_status"] in ("SUSPENDED", "WITHDRAWN"):
            fail("ERR_INVALID_ONCALL_TRANSITION",
                 "The neurologist's home facility cannot field on-call cover.")
    if current == "ON_CALL" and target == "OFF_DUTY":
        if record["active_consult_count"] != 0:
            fail("ERR_INVALID_ONCALL_TRANSITION",
                 "A neurologist holding live consults cannot go off duty.")
    db.setf(record, "on_call_state", target)
    return resp.object_response(record)

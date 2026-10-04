"""VotingSystem endpoints (PRD 3.1).

REGISTERED on create; auto-FIELDED by the first certified campaign (handled in
domains.campaigns); FIELDED -> RETIRED by PlatformAdmin only, and only when no
unit of the system remains non-RETIRED. REGISTERED -> RETIRED is not offered.
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from envelope import ok_object
from errors import err_invalid_state, err_not_found
from store import db
from util import stamp_new, touch
from validation import body_json, no_extra, req_enum, req_str

bp = Blueprint("systems", __name__)

HARDWARE_CLASSES = {"OPTICAL_SCANNER", "BALLOT_MARKING_DEVICE", "CENTRAL_TABULATOR"}
SYSTEM_STATES = {"REGISTERED", "FIELDED", "RETIRED"}
SYSTEM_ACTORS = {"RETIRED": {"PlatformAdmin"}}


@bp.post("/evote/voting-systems")
def create_voting_system():
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    body = body_json()
    no_extra(body, {"vendor_name", "model_name", "software_baseline_version", "hardware_class"})
    rec = stamp_new({})
    rec.update({
        "vendor_name": req_str(body, "vendor_name"),
        "model_name": req_str(body, "model_name"),
        "software_baseline_version": req_str(body, "software_baseline_version"),
        "hardware_class": req_enum(body, "hardware_class", HARDWARE_CLASSES),
        "status": "REGISTERED",
    })
    db.voting_systems[rec["id"]] = rec
    return ok_object(rec, 201)


def get_system_or_404(system_id):
    system = db.voting_systems.get(system_id)
    if system is None:
        err_not_found("voting system not found")
    return system


@bp.get("/evote/voting-systems/<system_id>")
def get_voting_system(system_id):
    auth_context()
    return ok_object(get_system_or_404(system_id), 200)


@bp.post("/evote/voting-systems/<system_id>/transitions")
def voting_system_transition(system_id):
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    ts = peek_to_state()
    require_transition_actor(role, ts, SYSTEM_ACTORS)
    system = get_system_or_404(system_id)
    body = body_json()
    no_extra(body, {"to_state"})
    to_state = req_enum(body, "to_state", SYSTEM_STATES)
    # Only FIELDED -> RETIRED exists on the client surface.
    if to_state != "RETIRED" or system["status"] != "FIELDED":
        err_invalid_state("voting system cannot transition from %s to %s" % (system["status"], to_state))
    for unit in db.equipment_units.values():
        if unit["voting_system_id"] == system_id and unit["operational_status"] != "RETIRED":
            err_invalid_state("system still has non-retired equipment units")
    system["status"] = "RETIRED"
    touch(system)
    return ok_object(system, 200)

"""Crisis episodes and hospital-to-home transition oversight."""
from flask import Blueprint

import auth
import clock
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("crisis", __name__)

TRIGGER_TYPES = ("HOSPITAL_ADMISSION", "FALL", "CAREGIVER_NO_SHOW",
                 "ACUTE_BEHAVIORAL", "ELDER_ABUSE_SUSPICION")
EPISODE_STATUSES = ("OPEN", "STABILIZED", "TRANSITION_OVERSIGHT", "CLOSED")
SETTLED_ENTRY_STATUSES = ("APPROVED", "INVOICED", "REJECTED", "VOIDED")

FILTERS = {
    "client_id": "client_id",
    "assigned_care_manager_id": "assigned_care_manager_id",
    "status": "status",
}


@bp.route("/care/crisis-episodes", methods=["POST"])
def create_episode():
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    trigger_type = v.req_enum(body, "trigger_type", TRIGGER_TYPES)
    hospital_name = v.opt_str(body, "hospital_name")
    client = lookup.need_client(client_id)
    record = new_record({
        "client_id": client_id,
        "assigned_care_manager_id": actor.user_id,
        "trigger_type": trigger_type,
        "hospital_name": hospital_name,
        "opened_at": clock.now(),
        "stabilized_at": None,
        "discharge_at": None,
        "closed_at": None,
        "status": "OPEN",
        "readmission_count": 0,
    })
    db.episodes[record["id"]] = record
    touch(client)
    return envelope.created(serialize.episode(record))


@bp.route("/care/crisis-episodes", methods=["GET"])
def list_episodes():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.episodes.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.episode(r) for r in records], limit, offset)


@bp.route("/care/crisis-episodes/<episode_id>", methods=["GET"])
def read_episode(episode_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_episode(episode_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.episode(record))


@bp.route("/care/crisis-episodes/<episode_id>/state", methods=["PATCH"])
def episode_state(episode_id):
    auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", EPISODE_STATUSES)
    discharge_at = None
    if to_state == "TRANSITION_OVERSIGHT":
        discharge_at = v.req_dt(body, "discharge_at")
    v.opt_str(body, "note")
    record = lookup.need_episode(episode_id)
    client = db.clients[record["client_id"]]
    if to_state == "STABILIZED":
        if record["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "STABILIZED is only reachable from OPEN.")
        record["stabilized_at"] = clock.now()
        record["status"] = "STABILIZED"
        touch(record)
        touch(client)
    elif to_state == "TRANSITION_OVERSIGHT":
        if record["status"] != "STABILIZED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "TRANSITION_OVERSIGHT is only reachable from "
                           "STABILIZED.")
        standing = [a for a in db.authorizations.values()
                    if a["client_id"] == client["id"]
                    and a["auth_status"] in derive.AUTHORIZED_SET]
        if not standing:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The practice does not accept oversight of a "
                           "discharge home with no standing coverage.")
        record["discharge_at"] = discharge_at
        record["status"] = "TRANSITION_OVERSIGHT"
        touch(record)
        touch(client)
    elif to_state == "OPEN":
        if record["status"] != "TRANSITION_OVERSIGHT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "OPEN is only reachable again from "
                           "TRANSITION_OVERSIGHT.")
        record["readmission_count"] = record["readmission_count"] + 1
        record["stabilized_at"] = None
        record["status"] = "OPEN"
        touch(record)
    else:
        if record["status"] != "TRANSITION_OVERSIGHT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CLOSED is only reachable from "
                           "TRANSITION_OVERSIGHT.")
        for entry in db.time_entries.values():
            if entry["crisis_episode_id"] == record["id"] and \
                    entry["status"] not in SETTLED_ENTRY_STATUSES:
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "Crisis time is still awaiting review.")
        record["closed_at"] = clock.now()
        record["status"] = "CLOSED"
        touch(record)
        touch(client)
    return envelope.ok(serialize.episode(record))

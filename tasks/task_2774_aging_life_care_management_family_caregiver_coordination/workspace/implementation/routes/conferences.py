"""Family conferences and the decisions documented at them."""
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

bp = Blueprint("conferences", __name__)

CONF_STATUSES = ("SCHEDULED", "CONVENED", "DOCUMENTED", "RESCHEDULED",
                 "CANCELLED")
DECISION_TYPES = ("VENDOR_ENGAGEMENT", "PLACEMENT_CHANGE", "CARE_LEVEL_CHANGE",
                  "ESCALATE_GUARDIANSHIP_PETITION", "ESCALATE_APS_REPORT")
DECISION_STATUSES = ("RECORDED", "RATIFIED", "ESCALATED", "ESCALATION_ACCEPTED",
                     "ESCALATION_DECLINED", "RESCINDED")
STRONG_SURROGATE_ROLES = ("POA_HEALTHCARE", "GUARDIAN")

CONF_FILTERS = {"client_id": "client_id", "status": "status"}
DECISION_FILTERS = {
    "family_conference_id": "family_conference_id",
    "decided_by_contact_id": "decided_by_contact_id",
    "decision_type": "decision_type",
    "status": "status",
}


@bp.route("/care/family-conferences", methods=["POST"])
def create_conference():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    scheduled_start = v.req_dt(body, "scheduled_start")
    scheduled_end = v.req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise v.bad("'scheduled_end' must be strictly later than "
                    "'scheduled_start'.")
    invited = v.req_str_list(body, "invited_contact_ids", 1, 12, unique=True)
    agenda = v.opt_str(body, "agenda")
    lookup.need_client(client_id)
    contacts = [lookup.need_contact(cid) for cid in invited]
    for contact in contacts:
        if contact["client_id"] != client_id:
            raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                           "An invitation list may not reach into another "
                           "family.")
    record = new_record({
        "client_id": client_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "invited_contact_ids": invited,
        "attended_contact_ids": [],
        "agenda": agenda,
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "quorum_met": False,
        "convened_at": None,
    })
    db.conferences[record["id"]] = record
    return envelope.created(serialize.conference(record))


@bp.route("/care/family-conferences", methods=["GET"])
def list_conferences():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.conferences.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, CONF_FILTERS,
                                    v.filters(CONF_FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.conference(r) for r in records],
                         limit, offset)


@bp.route("/care/family-conferences/<conference_id>", methods=["GET"])
def read_conference(conference_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_conference(conference_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.conference(record))


@bp.route("/care/family-conferences/<conference_id>/state", methods=["PATCH"])
def conference_state(conference_id):
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", CONF_STATUSES)
    attended = None
    rescheduled_start = None
    rescheduled_end = None
    if to_state == "CONVENED":
        attended = v.req_str_list(body, "attended_contact_ids", 1, 12,
                                  unique=True)
    if to_state == "RESCHEDULED":
        rescheduled_start = v.req_dt(body, "rescheduled_start")
        rescheduled_end = v.req_dt(body, "rescheduled_end")
        if rescheduled_end <= rescheduled_start:
            raise v.bad("'rescheduled_end' must be strictly later than "
                        "'rescheduled_start'.")
    v.opt_str(body, "reason")
    record = lookup.need_conference(conference_id)
    client = db.clients[record["client_id"]]
    if to_state == "CONVENED":
        if record["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CONVENED is only reachable from SCHEDULED.")
        invited = set(record["invited_contact_ids"])
        if not set(attended).issubset(invited):
            raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                           "An attendee who was never invited may not be "
                           "recorded.")
        quorum_met, _ = derive.quorum_evaluation(record, attended, client)
        if not quorum_met:
            raise ApiError("ERR_QUORUM_NOT_MET",
                           "Quorum does not hold for this attendance list.")
        record["attended_contact_ids"] = attended
        record["quorum_met"] = True
        record["convened_at"] = clock.now()
        record["status"] = "CONVENED"
        touch(record)
    elif to_state == "DOCUMENTED":
        if record["status"] != "CONVENED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DOCUMENTED is only reachable from CONVENED.")
        surviving = [d for d in db.decisions.values()
                     if d["family_conference_id"] == record["id"]
                     and d["status"] != "RESCINDED"]
        if not surviving:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A conference with nothing surviving to record "
                           "cannot be closed out.")
        record["status"] = "DOCUMENTED"
        touch(record)
    elif to_state == "RESCHEDULED":
        if record["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "RESCHEDULED is only reachable from SCHEDULED.")
        record["scheduled_start"] = rescheduled_start
        record["scheduled_end"] = rescheduled_end
        record["reschedule_count"] = record["reschedule_count"] + 1
        record["status"] = "RESCHEDULED"
        touch(record)
    elif to_state == "SCHEDULED":
        if record["status"] != "RESCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "SCHEDULED is only reachable from RESCHEDULED.")
        record["status"] = "SCHEDULED"
        touch(record)
    else:
        if record["status"] not in ("SCHEDULED", "RESCHEDULED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CANCELLED is not reachable from %s."
                           % record["status"])
        record["status"] = "CANCELLED"
        touch(record)
    return envelope.ok(serialize.conference(record))


@bp.route("/care/conference-decisions", methods=["POST"])
def create_decision():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    conference_id = v.req_str(body, "family_conference_id", 1, None)
    contact_id = v.req_str(body, "decided_by_contact_id", 1, None)
    decision_type = v.req_enum(body, "decision_type", DECISION_TYPES)
    decision_text = v.req_str(body, "decision_text", 1, 2000)
    capacity_basis = v.opt_str(body, "capacity_basis")
    contact = lookup.need_contact(contact_id)
    conference = lookup.need_conference(conference_id)
    client = db.clients[conference["client_id"]]
    if client["capacity_status"] != "PRESUMED_CAPABLE" and not capacity_basis:
        raise ApiError("ERR_CAPACITY_BASIS_REQUIRED",
                       "An evidentiary basis is mandatory for a client who is "
                       "not presumed capable.")
    if not contact["is_surrogate_decision_maker"] or (
            client["capacity_status"] == "ADJUDICATED_INCAPACITATED"
            and contact["contact_role"] not in STRONG_SURROGATE_ROLES):
        raise ApiError("ERR_SURROGATE_AUTHORITY_MISSING",
                       "The named decision maker holds no adequate surrogate "
                       "authority.")
    if not conference["quorum_met"]:
        raise ApiError("ERR_QUORUM_NOT_MET",
                       "A decision may not be documented against a conference "
                       "that never reached quorum.")
    if contact["client_id"] != conference["client_id"]:
        raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                       "The deciding contact belongs to a different client.")
    record = new_record({
        "family_conference_id": conference_id,
        "decided_by_contact_id": contact_id,
        "decision_type": decision_type,
        "decision_text": decision_text,
        "capacity_basis": capacity_basis,
        "status": "RECORDED",
        "ratified_at": None,
        "escalated_at": None,
        "rescinded_reason": None,
    })
    db.decisions[record["id"]] = record
    touch(conference)
    return envelope.created(serialize.decision(record))


@bp.route("/care/conference-decisions", methods=["GET"])
def list_decisions():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.decisions.values())
    if scope is not None:
        records = [r for r in records
                   if _decision_client_id(r) == scope]
    records = lookup.filter_records(records, DECISION_FILTERS,
                                    v.filters(DECISION_FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.decision(r) for r in records], limit, offset)


@bp.route("/care/conference-decisions/<decision_id>", methods=["GET"])
def read_decision(decision_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_decision(decision_id)
    auth.family_read_guard(actor, _decision_client_id(record))
    return envelope.ok(serialize.decision(record))


def _decision_client_id(record):
    conference = db.conferences.get(record["family_conference_id"])
    return None if conference is None else conference["client_id"]


@bp.route("/care/conference-decisions/<decision_id>/state", methods=["PATCH"])
def decision_state(decision_id):
    actor = auth.actor_for(auth.ROLE_SUPERVISOR)
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", DECISION_STATUSES)
    note = v.opt_str(body, "note")
    record = lookup.need_decision(decision_id)
    auth.resolve_supervisor(actor)
    conference = db.conferences[record["family_conference_id"]]
    client = db.clients[conference["client_id"]]
    if to_state == "RATIFIED":
        if record["status"] != "RECORDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "RATIFIED is only reachable from RECORDED.")
        if conference["status"] not in ("CONVENED", "DOCUMENTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The parent conference has not been convened.")
        if not conference["quorum_met"]:
            raise ApiError("ERR_QUORUM_NOT_MET",
                           "The parent conference never reached quorum.")
        record["ratified_at"] = clock.now()
        record["status"] = "RATIFIED"
        touch(record)
    elif to_state == "ESCALATED":
        if record["status"] != "RATIFIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "ESCALATED is only reachable from RATIFIED.")
        if record["decision_type"] not in derive.ESCALATION_TYPES or \
                client["capacity_status"] not in (
                    "DIMINISHED_DOCUMENTED", "ADJUDICATED_INCAPACITATED") or \
                conference["status"] != "DOCUMENTED":
            raise ApiError("ERR_ESCALATION_PRECONDITION_UNMET",
                           "The escalation preconditions do not hold.")
        record["escalated_at"] = clock.now()
        record["status"] = "ESCALATED"
        touch(record)
        touch(client)
    elif to_state in ("ESCALATION_ACCEPTED", "ESCALATION_DECLINED"):
        if record["status"] != "ESCALATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "%s is only reachable from ESCALATED." % to_state)
        record["status"] = to_state
        touch(record)
        if to_state == "ESCALATION_ACCEPTED" and \
                record["decision_type"] == "ESCALATE_GUARDIANSHIP_PETITION":
            derive.guardianship_adjudication_cascade(client, record)
        touch(client)
    elif to_state == "RESCINDED":
        if record["status"] not in ("RECORDED", "RATIFIED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "RESCINDED is not reachable from %s."
                           % record["status"])
        record["rescinded_reason"] = note
        record["status"] = "RESCINDED"
        touch(record)
        derive.decision_rescinded_cascade(record)
        touch(client)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested." % to_state)
    return envelope.ok(serialize.decision(record))

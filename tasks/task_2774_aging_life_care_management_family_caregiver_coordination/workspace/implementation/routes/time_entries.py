"""Billable time capture, rating and supervisory review."""
from flask import Blueprint

import auth
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("time_entries", __name__)

SERVICE_TYPES = ("ASSESSMENT", "CARE_COORDINATION", "CRISIS_RESPONSE", "TRAVEL",
                 "CONFERENCE")
ENTRY_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "INVOICED",
                  "VOIDED")
LIVE_EPISODE_STATUSES = ("OPEN", "STABILIZED", "TRANSITION_OVERSIGHT")

OWNERSHIP = {
    "SUBMITTED": (auth.ROLE_CARE_MANAGER,),
    "DRAFT": (auth.ROLE_CARE_MANAGER,),
    "APPROVED": (auth.ROLE_SUPERVISOR,),
    "REJECTED": (auth.ROLE_SUPERVISOR,),
    "VOIDED": (auth.ROLE_SUPERVISOR,),
}

FILTERS = {
    "client_id": "client_id",
    "care_manager_id": "care_manager_id",
    "approved_by_care_manager_id": "approved_by_care_manager_id",
    "invoice_id": "invoice_id",
    "crisis_episode_id": "crisis_episode_id",
    "status": "status",
    "service_date": "service_date",
}


def _crisis_context(service_type, episode, client_id, episode_id):
    """Crisis time must have a crisis to point at, and other time must not."""
    if service_type == "CRISIS_RESPONSE":
        if episode_id is None:
            raise ApiError("ERR_CRISIS_CONTEXT_REQUIRED",
                           "Crisis time requires a crisis episode.")
        if episode["status"] not in LIVE_EPISODE_STATUSES:
            raise ApiError("ERR_CRISIS_CONTEXT_REQUIRED",
                           "The named episode is closed.")
        if episode["client_id"] != client_id:
            raise ApiError("ERR_CRISIS_CONTEXT_REQUIRED",
                           "The named episode belongs to a different client.")
    elif episode_id is not None:
        raise ApiError("ERR_CRISIS_CONTEXT_REQUIRED",
                       "Only crisis time may name a crisis episode.")


def _guard_overlap(candidate_cm, start_at, end_at):
    for entry in derive.care_manager_entries(candidate_cm):
        if derive.half_open_overlaps(entry["start_at"], entry["end_at"],
                                     start_at, end_at):
            raise ApiError("ERR_TIME_ENTRY_OVERLAP",
                           "This interval overlaps another entry of the same "
                           "care manager.")


def _guard_travel_buffer(candidate_cm, start_at, end_at, service_location_id):
    previous = None
    following = None
    for entry in derive.care_manager_entries(candidate_cm):
        if entry["end_at"] <= start_at:
            if previous is None or entry["end_at"] > previous["end_at"]:
                previous = entry
        elif entry["start_at"] >= end_at:
            if following is None or entry["start_at"] < following["start_at"]:
                following = entry
    limit = derive.TRAVEL_BUFFER_MINUTES * 60
    if previous is not None and \
            previous["service_location_id"] != service_location_id and \
            (start_at - previous["end_at"]).total_seconds() < limit:
        raise ApiError("ERR_TRAVEL_BUFFER_VIOLATION",
                       "A location change requires at least 30 minutes of "
                       "travel time.")
    if following is not None and \
            following["service_location_id"] != service_location_id and \
            (following["start_at"] - end_at).total_seconds() < limit:
        raise ApiError("ERR_TRAVEL_BUFFER_VIOLATION",
                       "A location change requires at least 30 minutes of "
                       "travel time.")


def _guard_daily_cap(candidate_cm, service_date, rounded_minutes):
    total = rounded_minutes
    for entry in derive.care_manager_entries(candidate_cm):
        if entry["service_date"] == service_date:
            total += entry["rounded_minutes"]
    if total > derive.DAILY_BILLABLE_CAP_MINUTES:
        raise ApiError("ERR_DAILY_CAP_EXCEEDED",
                       "The care manager's daily billable cap of 600 minutes "
                       "would be exceeded.")


@bp.route("/care/time-entries", methods=["POST"])
def create_time_entry():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    care_manager_id = v.req_str(body, "care_manager_id", 1, None)
    service_type = v.req_enum(body, "service_type", SERVICE_TYPES)
    start_at = v.req_dt(body, "start_at")
    end_at = v.req_dt(body, "end_at")
    if end_at <= start_at:
        raise v.bad("'end_at' must be strictly later than 'start_at'.")
    service_location_id = v.req_str(body, "service_location_id", 1, 40)
    episode_id = v.opt_str(body, "crisis_episode_id")
    note = v.opt_str(body, "note")
    client = lookup.need_client(client_id)
    care_manager = lookup.need_care_manager(care_manager_id)
    episode = None
    if episode_id is not None:
        episode = lookup.need_episode(episode_id)
    if client["status"] == "DISCHARGED":
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                       "Time may not be logged against a discharged client.")
    _crisis_context(service_type, episode, client_id, episode_id)
    _guard_overlap(care_manager_id, start_at, end_at)
    _guard_travel_buffer(care_manager_id, start_at, end_at,
                         service_location_id)
    rated = derive.rate_time_entry(client, care_manager, service_type, start_at,
                                   end_at, episode)
    _guard_daily_cap(care_manager_id, rated["service_date"],
                     rated["rounded_minutes"])
    record = new_record({
        "client_id": client_id,
        "care_manager_id": care_manager_id,
        "approved_by_care_manager_id": None,
        "invoice_id": None,
        "crisis_episode_id": episode_id,
        "service_type": service_type,
        "start_at": start_at,
        "end_at": end_at,
        "service_location_id": service_location_id,
        "service_date": rated["service_date"],
        "raw_minutes": rated["raw_minutes"],
        "rounded_minutes": rated["rounded_minutes"],
        "rate_multiplier": rated["rate_multiplier"],
        "after_hours_factor": rated["after_hours_factor"],
        "billable_amount_cents": rated["billable_amount_cents"],
        "status": "DRAFT",
        "note": note,
    })
    db.time_entries[record["id"]] = record
    touch(client)
    return envelope.created(serialize.time_entry(record))


@bp.route("/care/time-entries", methods=["GET"])
def list_time_entries():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.time_entries.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.time_entry(r) for r in records],
                         limit, offset)


@bp.route("/care/time-entries/<time_entry_id>", methods=["GET"])
def read_time_entry(time_entry_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_time_entry(time_entry_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.time_entry(record))


@bp.route("/care/time-entries/<time_entry_id>/state", methods=["PATCH"])
def time_entry_state(time_entry_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    auth.owns_target(actor, OWNERSHIP, v.raw_field(body, "to_state"))
    to_state = v.req_enum(body, "to_state", ENTRY_STATUSES)
    v.opt_str(body, "reason")
    record = lookup.need_time_entry(time_entry_id)
    if to_state in ("SUBMITTED", "DRAFT") and \
            actor.user_id != record["care_manager_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the entry's author may drive this transition.")
    auth.resolve_supervisor(actor)
    client = db.clients[record["client_id"]]
    if to_state == "SUBMITTED":
        if record["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "SUBMITTED is only reachable from DRAFT.")
        record["status"] = "SUBMITTED"
        touch(record)
    elif to_state in ("APPROVED", "REJECTED"):
        if record["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "%s is only reachable from SUBMITTED." % to_state)
        if actor.user_id == record["care_manager_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "A supervisor may not review their own time.")
        if to_state == "APPROVED":
            record["approved_by_care_manager_id"] = actor.user_id
            record["status"] = "APPROVED"
            touch(record)
        else:
            record["status"] = "REJECTED"
            touch(record)
            touch(client)
    elif to_state == "DRAFT":
        if record["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DRAFT is only reachable from REJECTED.")
        record["status"] = "DRAFT"
        touch(record)
        touch(client)
    elif to_state == "VOIDED":
        if record["status"] not in ("DRAFT", "SUBMITTED", "APPROVED",
                                   "REJECTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "VOIDED is not reachable from %s."
                           % record["status"])
        if record["invoice_id"] is not None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An entry sitting on an issued invoice must be "
                           "released by voiding that invoice first.")
        record["status"] = "VOIDED"
        touch(record)
        touch(client)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested." % to_state)
    return envelope.ok(serialize.time_entry(record))

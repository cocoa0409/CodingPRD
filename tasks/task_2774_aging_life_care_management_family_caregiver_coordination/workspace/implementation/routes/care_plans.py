"""Care-plan authoring, family approval and the supersession chain."""
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

bp = Blueprint("care_plans", __name__)

STATUSES = ("DRAFT", "PENDING_FAMILY_APPROVAL", "ACTIVE", "REJECTED",
            "SUPERSEDED", "WITHDRAWN")

OWNERSHIP = {
    "PENDING_FAMILY_APPROVAL": (auth.ROLE_CARE_MANAGER,),
    "DRAFT": (auth.ROLE_CARE_MANAGER,),
    "ACTIVE": (auth.ROLE_FAMILY,),
    "REJECTED": (auth.ROLE_FAMILY,),
}

FILTERS = {
    "client_id": "client_id",
    "source_assessment_id": "source_assessment_id",
    "supersedes_care_plan_id": "supersedes_care_plan_id",
    "approved_by_contact_id": "approved_by_contact_id",
    "status": "status",
}

DEFAULT_REVIEW_INTERVAL_DAYS = 90
MIN_REVIEW_INTERVAL_DAYS = 30
MAX_REVIEW_INTERVAL_DAYS = 365


def _surrogate_of(actor, client_id):
    """A plan decision may only be driven by that client's surrogate."""
    contact = db.contacts.get(actor.user_id)
    if contact is None or contact["client_id"] != client_id or \
            not contact["is_surrogate_decision_maker"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only a surrogate family decision maker of this client "
                       "may drive the family-approval decision.")
    return contact


@bp.route("/care/care-plans", methods=["POST"])
def create_care_plan():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    source_assessment_id = v.req_str(body, "source_assessment_id", 1, None)
    expected_client_version = v.req_int(body, "expected_client_version", 1)
    goals = v.req_str_list(body, "goals", 1, 12)
    review_interval_days = v.opt_int(body, "review_interval_days",
                                     DEFAULT_REVIEW_INTERVAL_DAYS,
                                     MIN_REVIEW_INTERVAL_DAYS,
                                     MAX_REVIEW_INTERVAL_DAYS)
    supersedes_care_plan_id = v.opt_str(body, "supersedes_care_plan_id")
    client = lookup.need_client(client_id)
    assessment = lookup.need_assessment(source_assessment_id)
    predecessor = None
    if supersedes_care_plan_id is not None:
        predecessor = lookup.need_care_plan(supersedes_care_plan_id)
    if expected_client_version != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION",
                       "The client has moved on since it was last read.")
    if assessment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSESSMENT_NOT_ACCEPTED",
                       "A care plan may only be authored from an ACCEPTED "
                       "assessment.")
    if assessment["client_id"] != client_id:
        raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                       "The source assessment belongs to a different client.")
    if predecessor is not None and predecessor["client_id"] != client_id:
        raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                       "The superseded plan belongs to a different client.")
    record = new_record({
        "client_id": client_id,
        "source_assessment_id": source_assessment_id,
        "supersedes_care_plan_id": supersedes_care_plan_id,
        "approved_by_contact_id": None,
        "goals": goals,
        "review_interval_days": review_interval_days,
        "pinned_assessment_version": assessment["version"],
        "status": "DRAFT",
        "rejection_rounds": 0,
        "activated_at": None,
    })
    db.care_plans[record["id"]] = record
    touch(client)
    return envelope.created(serialize.care_plan(record))


@bp.route("/care/care-plans", methods=["GET"])
def list_care_plans():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.care_plans.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.care_plan(r) for r in records], limit, offset)


@bp.route("/care/care-plans/<care_plan_id>", methods=["GET"])
def read_care_plan(care_plan_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_care_plan(care_plan_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.care_plan(record))


@bp.route("/care/care-plans/<care_plan_id>/state", methods=["PATCH"])
def care_plan_state(care_plan_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_FAMILY,
                           auth.ROLE_SUPERVISOR)
    body = v.json_body()
    auth.owns_target(actor, OWNERSHIP, v.raw_field(body, "to_state"))
    to_state = v.req_enum(body, "to_state", STATUSES)
    v.opt_str(body, "decision_note")
    record = lookup.need_care_plan(care_plan_id)
    client = db.clients[record["client_id"]]
    if to_state in ("ACTIVE", "REJECTED"):
        _surrogate_of(actor, record["client_id"])
    if to_state == "PENDING_FAMILY_APPROVAL":
        _send_for_approval(record, client)
    elif to_state == "ACTIVE":
        _activate(record, client, actor)
    elif to_state == "REJECTED":
        if record["status"] != "PENDING_FAMILY_APPROVAL":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REJECTED is only reachable from "
                           "PENDING_FAMILY_APPROVAL.")
        record["rejection_rounds"] = record["rejection_rounds"] + 1
        record["status"] = "REJECTED"
        touch(record)
    elif to_state == "DRAFT":
        if record["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DRAFT is only reachable from REJECTED.")
        record["status"] = "DRAFT"
        touch(record)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is only reachable as a cascade." % to_state)
    return envelope.ok(serialize.care_plan(record))


def _send_for_approval(record, client):
    if record["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "PENDING_FAMILY_APPROVAL is only reachable from DRAFT "
                       "or REJECTED.")
    if client["status"] == "DISCHARGED":
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE", "The client is discharged.")
    assessment = db.assessments.get(record["source_assessment_id"])
    if assessment is None or assessment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSESSMENT_NOT_ACCEPTED",
                       "The source assessment is no longer ACCEPTED.")
    if record["pinned_assessment_version"] != assessment["version"]:
        raise ApiError("ERR_PINNED_ASSESSMENT_STALE",
                       "The source assessment has moved on since this plan was "
                       "authored.")
    surrogates = [c for c in db.contacts.values()
                  if c["client_id"] == client["id"] and
                  c["is_surrogate_decision_maker"]]
    if not surrogates:
        raise ApiError("ERR_SURROGATE_AUTHORITY_MISSING",
                       "The client has no surrogate decision maker to answer.")
    record["status"] = "PENDING_FAMILY_APPROVAL"
    touch(record)


def _activate(record, client, actor):
    if record["status"] != "PENDING_FAMILY_APPROVAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "ACTIVE is only reachable from PENDING_FAMILY_APPROVAL.")
    if derive.risk_posture(client) == "CRISIS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A plan may not be activated while the client is in "
                       "crisis.")
    if client["capacity_status"] != "PRESUMED_CAPABLE" and \
            not client.get("capacity_basis"):
        raise ApiError("ERR_CAPACITY_BASIS_REQUIRED",
                       "The evidentiary basis for relying on a surrogate has "
                       "not been documented.")
    record["approved_by_contact_id"] = actor.user_id
    record["activated_at"] = clock.now()
    record["status"] = "ACTIVE"
    touch(record)
    predecessor_id = record["supersedes_care_plan_id"]
    if predecessor_id is not None:
        predecessor = db.care_plans.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "ACTIVE":
            derive.supersede_plan(predecessor)
    if client["status"] == "ASSESSMENT_IN_PROGRESS":
        client["status"] = "ACTIVE_CARE"
    touch(client)

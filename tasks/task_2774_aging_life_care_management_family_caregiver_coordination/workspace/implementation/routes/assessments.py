"""The comprehensive geriatric assessment and its supervisory review."""
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

bp = Blueprint("assessments", __name__)

STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "ACCEPTED", "WITHDRAWN")

OWNERSHIP = {
    "SUBMITTED": (auth.ROLE_CARE_MANAGER,),
    "DRAFT": (auth.ROLE_CARE_MANAGER,),
    "ACCEPTED": (auth.ROLE_SUPERVISOR,),
    "REVISION_REQUESTED": (auth.ROLE_SUPERVISOR,),
}

FILTERS = {
    "client_id": "client_id",
    "care_manager_id": "care_manager_id",
    "reviewed_by_care_manager_id": "reviewed_by_care_manager_id",
    "status": "status",
}


@bp.route("/care/assessments", methods=["POST"])
def create_assessment():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    care_manager_id = v.req_str(body, "care_manager_id", 1, None)
    domain_scores = v.req_domain_scores(body)
    narrative = v.opt_str(body, "narrative")
    client = lookup.need_client(client_id)
    lookup.need_care_manager(care_manager_id)
    if client["status"] == "DISCHARGED":
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                       "An assessment may not be opened against a discharged client.")
    first = not any(a["client_id"] == client_id for a in db.assessments.values())
    record = new_record({
        "client_id": client_id,
        "care_manager_id": care_manager_id,
        "reviewed_by_care_manager_id": None,
        "domain_scores": domain_scores,
        "narrative": narrative,
        "status": "DRAFT",
        "revision_round": 0,
        "screening_acuity": None,
        "comprehensive_acuity": None,
        "accepted_at": None,
    })
    db.assessments[record["id"]] = record
    if first and client["status"] == "PROSPECT":
        client["status"] = "ASSESSMENT_IN_PROGRESS"
        touch(client)
    return envelope.created(serialize.assessment(record))


@bp.route("/care/assessments", methods=["GET"])
def list_assessments():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.assessments.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.assessment(r) for r in records], limit, offset)


@bp.route("/care/assessments/<assessment_id>", methods=["GET"])
def read_assessment(assessment_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_assessment(assessment_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.assessment(record))


@bp.route("/care/assessments/<assessment_id>", methods=["PATCH"])
def edit_assessment(assessment_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    has_scores = "domain_scores" in body and body.get("domain_scores") is not None
    has_narrative = "narrative" in body
    if not has_scores and not has_narrative:
        raise v.bad("Supply at least one of 'domain_scores' or 'narrative'.")
    domain_scores = v.req_domain_scores(body) if has_scores else None
    narrative = v.opt_str(body, "narrative") if has_narrative else None
    record = lookup.need_assessment(assessment_id)
    if actor.user_id != record["care_manager_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the authoring care manager may edit this assessment.")
    if has_scores:
        if record["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "domain_scores may only be edited while the assessment "
                           "is DRAFT.")
    elif record["status"] not in ("DRAFT", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A narrative correction is only permitted while the "
                       "assessment is DRAFT or ACCEPTED.")
    if has_scores:
        record["domain_scores"] = domain_scores
    if has_narrative:
        record["narrative"] = narrative
    touch(record)
    return envelope.ok(serialize.assessment(record))


@bp.route("/care/assessments/<assessment_id>/state", methods=["PATCH"])
def assessment_state(assessment_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    auth.owns_target(actor, OWNERSHIP, v.raw_field(body, "to_state"))
    to_state = v.req_enum(body, "to_state", STATUSES)
    v.opt_str(body, "review_note")
    record = lookup.need_assessment(assessment_id)
    client = db.clients.get(record["client_id"])
    if to_state == "WITHDRAWN":
        if record["status"] == "DRAFT" and actor.role != auth.ROLE_CARE_MANAGER:
            raise ApiError("ERR_UNAUTHORIZED",
                           "Withdrawal from DRAFT belongs to the CareManager.")
        if record["status"] in ("SUBMITTED", "REVISION_REQUESTED") and \
                actor.role != auth.ROLE_SUPERVISOR:
            raise ApiError("ERR_UNAUTHORIZED",
                           "Withdrawal from %s belongs to the PracticeSupervisor."
                           % record["status"])
    auth.resolve_supervisor(actor)
    if to_state in ("SUBMITTED", "DRAFT") and \
            actor.user_id != record["care_manager_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the authoring care manager may drive this transition.")
    if to_state == "SUBMITTED":
        if record["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "SUBMITTED is only reachable from DRAFT.")
        if client["status"] == "DISCHARGED":
            raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                           "The client is discharged.")
        record["screening_acuity"] = derive.screening_acuity(record["domain_scores"])
        record["status"] = "SUBMITTED"
        touch(record)
    elif to_state in ("ACCEPTED", "REVISION_REQUESTED"):
        if record["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "%s is only reachable from SUBMITTED." % to_state)
        if actor.user_id == record["care_manager_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "A supervisor may not review an assessment they authored.")
        record["reviewed_by_care_manager_id"] = actor.user_id
        if to_state == "ACCEPTED":
            record["comprehensive_acuity"] = derive.comprehensive_acuity(
                record["domain_scores"])
            record["accepted_at"] = clock.now()
            record["status"] = "ACCEPTED"
            touch(record)
            touch(client)
        else:
            record["status"] = "REVISION_REQUESTED"
            touch(record)
        return envelope.ok(serialize.assessment(record))
    elif to_state == "DRAFT":
        if record["status"] != "REVISION_REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DRAFT is only reachable from REVISION_REQUESTED.")
        record["revision_round"] = record["revision_round"] + 1
        record["screening_acuity"] = None
        record["status"] = "DRAFT"
        touch(record)
    elif to_state == "WITHDRAWN":
        if record["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "WITHDRAWN is not reachable from %s." % record["status"])
        for plan in db.care_plans.values():
            if plan["source_assessment_id"] == record["id"] and \
                    plan["status"] in ("PENDING_FAMILY_APPROVAL", "ACTIVE"):
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "A care plan is still relying on this assessment.")
        record["status"] = "WITHDRAWN"
        touch(record)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested." % to_state)
    return envelope.ok(serialize.assessment(record))

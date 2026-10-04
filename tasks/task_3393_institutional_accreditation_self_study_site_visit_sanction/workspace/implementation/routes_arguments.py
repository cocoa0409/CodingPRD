"""Assurance arguments and evidence items (PRD §3.4)."""
from flask import Blueprint, request

import constants as C
from auth import (authenticate, check_liaison_chain, institution_of_argument,
                  institution_of_cycle, institution_of_evidence, require_role)
from calculations import readiness_score
from db import STORE
from errors import (ERR_ASSURANCE_ARGUMENT_NOT_FOUND,
                    ERR_EVIDENCE_ITEM_NOT_FOUND,
                    ERR_INSUFFICIENT_EVIDENCE_COVERAGE, ERR_INVALID_STATE,
                    ERR_MAX_REVISIONS_EXCEEDED, ERR_REVIEW_CYCLE_NOT_FOUND,
                    ERR_REVIEWER_NOT_ASSIGNED, ERR_SEGREGATION_OF_DUTIES,
                    raise_err)
from helpers import (fetch_or_404, get_body, new_entity, paginate, req_bool,
                     req_enum, req_string, serialize, touch)
from response import success_list, success_object

bp = Blueprint("arguments", __name__)


def _argument_evidence(argument_id):
    return [e for e in STORE.evidence_items.values()
            if e["assurance_argument_id"] == argument_id]


def _recompute_team_readiness(argument):
    argument["readiness_team_verified"] = readiness_score(
        _argument_evidence(argument["id"]), "TEAM_VERIFIED")
    touch(argument)


@bp.post("/accreditation/review-cycles/<cycle_id>/assurance-arguments")
def create_argument(cycle_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    check_liaison_chain(actor, cycle["institution_id"])
    body = get_body()
    narrative = req_string(body, "narrative_text")
    if cycle["status"] != "MATERIALS_OPEN":
        raise_err(ERR_INVALID_STATE, "Arguments may be drafted only while the cycle is MATERIALS_OPEN")
    argument = new_entity({
        "review_cycle_id": cycle_id,
        "narrative_text": narrative,
        "status": "DRAFT",
        "revision_count": 0,
        "readiness_self_reported": None,
        "readiness_team_verified": None,
        "submitted_at": None,
        "locked_at": None,
    })
    STORE.assurance_arguments[argument["id"]] = argument
    return success_object(serialize(argument), code=201)


@bp.get("/accreditation/review-cycles/<cycle_id>/assurance-arguments")
def list_arguments(cycle_id):
    actor = authenticate()
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, cycle["institution_id"])
    items = [a for a in STORE.assurance_arguments.values() if a["review_cycle_id"] == cycle_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/assurance-arguments/<argument_id>")
def get_argument(argument_id):
    actor = authenticate()
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, institution_of_argument(argument))
    return success_object(serialize(argument))


@bp.post("/accreditation/assurance-arguments/<argument_id>/submit")
def submit_argument(argument_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    check_liaison_chain(actor, institution_of_argument(argument))
    if argument["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err(ERR_INVALID_STATE, "Only a DRAFT or REVISION_REQUESTED argument can be submitted")
    if argument["status"] == "DRAFT":
        cycle = STORE.review_cycles.get(argument["review_cycle_id"])
        if cycle is None or cycle["status"] != "MATERIALS_OPEN":
            raise_err(ERR_INVALID_STATE, "First submission requires the cycle to be MATERIALS_OPEN")
    items = _argument_evidence(argument_id)
    per_criterion_ok = all(
        sum(1 for e in items if e["criterion_code"] == code) >= C.MIN_EVIDENCE_PER_CRITERION
        for code in C.CRITERION_CODES)
    if not per_criterion_ok or len(items) < C.ARGUMENT_MIN_TOTAL_EVIDENCE:
        raise_err(ERR_INSUFFICIENT_EVIDENCE_COVERAGE,
                  "Each criterion needs >= 3 evidence items and the argument >= 15 in total")
    argument["status"] = "SUBMITTED"
    argument["submitted_at"] = STORE.now_iso()
    argument["readiness_self_reported"] = readiness_score(items, "SELF_REPORTED")
    touch(argument)
    return success_object(serialize(argument))


@bp.post("/accreditation/assurance-arguments/<argument_id>/request-revision")
def request_revision(argument_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    if argument["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED argument can be sent back for revision")
    if argument["revision_count"] >= C.MAX_ARGUMENT_REVISIONS:
        # The call fails AND the argument still transitions to terminal (§3.4).
        argument["status"] = "REJECTED_AS_INSUFFICIENT"
        touch(argument)
        raise_err(ERR_MAX_REVISIONS_EXCEEDED,
                  "revision_count is already at the maximum; argument rejected as insufficient")
    argument["revision_count"] += 1
    argument["status"] = "REVISION_REQUESTED"
    touch(argument)
    return success_object(serialize(argument))


@bp.post("/accreditation/assurance-arguments/<argument_id>/lock")
def lock_argument(argument_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    if argument["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED argument can be locked")
    cycle = STORE.review_cycles.get(argument["review_cycle_id"])
    if cycle is None or cycle["status"] != "EVALUATION_ACTIVE":
        raise_err(ERR_INVALID_STATE, "Locking requires the cycle to be EVALUATION_ACTIVE")
    argument["status"] = "REVIEW_LOCKED"
    argument["locked_at"] = STORE.now_iso()
    argument["readiness_team_verified"] = readiness_score(
        _argument_evidence(argument_id), "TEAM_VERIFIED")
    touch(argument)
    return success_object(serialize(argument))


@bp.post("/accreditation/assurance-arguments/<argument_id>/evidence-items")
def create_evidence(argument_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    check_liaison_chain(actor, institution_of_argument(argument))
    body = get_body()
    criterion_code = req_enum(body, "criterion_code", C.CRITERION_CODES)
    evidence_type = req_enum(body, "evidence_type", C.EVIDENCE_TYPES)
    title = req_string(body, "title")
    document_uri = req_string(body, "document_uri")
    if argument["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err(ERR_INVALID_STATE, "Evidence may be attached only while DRAFT or REVISION_REQUESTED")
    item = new_entity({
        "assurance_argument_id": argument_id,
        "criterion_code": criterion_code,
        "evidence_type": evidence_type,
        "title": title,
        "document_uri": document_uri,
        "verified": False,
        "verified_by_reviewer_id": None,
    })
    STORE.evidence_items[item["id"]] = item
    return success_object(serialize(item), code=201)


@bp.get("/accreditation/assurance-arguments/<argument_id>/evidence-items")
def list_evidence(argument_id):
    actor = authenticate()
    argument = fetch_or_404(STORE.assurance_arguments, argument_id, ERR_ASSURANCE_ARGUMENT_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, institution_of_argument(argument))
    items = _argument_evidence(argument_id)
    criterion = request.args.get("criterion_code")
    if criterion is not None:
        items = [e for e in items if e["criterion_code"] == criterion]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/evidence-items/<item_id>/verify")
def verify_evidence(item_id):
    actor = authenticate()
    require_role(actor, ["PeerReviewer"])
    item = fetch_or_404(STORE.evidence_items, item_id, ERR_EVIDENCE_ITEM_NOT_FOUND)
    argument = STORE.assurance_arguments.get(item["assurance_argument_id"])
    cycle = STORE.review_cycles.get(argument["review_cycle_id"]) if argument else None
    body = get_body()
    verified = req_bool(body, "verified")
    if argument is None or argument["status"] != "REVIEW_LOCKED":
        raise_err(ERR_INVALID_STATE, "Evidence can be verified only while the argument is REVIEW_LOCKED")
    # Segregation of duties (§2.10): the liaison of the institution under
    # review may never verify evidence.
    if actor.user_id == cycle["institution_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The institution's liaison may never verify evidence")
    bound = False
    for a in STORE.team_assignments.values():
        if a["reviewer_id"] != actor.user_id:
            continue
        if a["response"] != "ACCEPTED" or a["status"] != "ACTIVE":
            continue
        team = STORE.review_teams.get(a["review_team_id"])
        if team is not None and team["review_cycle_id"] == cycle["id"] and team["status"] != "DISBANDED":
            bound = True
            break
    if not bound:
        raise_err(ERR_REVIEWER_NOT_ASSIGNED,
                  "Verifier must be an ACCEPTED member of the cycle's team")
    item["verified"] = verified
    item["verified_by_reviewer_id"] = actor.user_id if verified else None
    touch(item)
    _recompute_team_readiness(argument)
    return success_object(serialize(item))

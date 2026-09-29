"""ChangeEvent endpoints and the classification fork (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, g

import clock
import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError
from money import MONEY_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)
from services import derive

bp = Blueprint("change_events", __name__)

ORIGINS = (
    "OWNER_DIRECTIVE",
    "DESIGN_DEVELOPMENT",
    "FIELD_CONDITION",
    "SUBCONTRACTOR_DEFAULT",
    "ALLOWANCE_OVERRUN",
)
CLASSIFICATIONS = (
    "SCOPE_CHANGE",
    "CONTINGENCY_USE_OWNER",
    "CONTINGENCY_USE_CONSTRUCTION",
)
EVENT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "CLASSIFIED",
    "REJECTED",
)
REVIEW_ACTIONS = ("BEGIN_REVIEW", "REQUEST_REVISION", "REJECT")
DRAW_OWNER_APPROVAL_THRESHOLD = Decimal("50000.00")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


@bp.route("/change-events", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_change_event():
    body = v.json_body()
    project_id = v.get_id(body, "project_id", required=True)
    description = v.get_str(body, "description", required=True, min_len=1, max_len=1000)
    estimated_amount = v.get_money(
        body, "estimated_amount", required=True, positive=True
    )
    origin = v.get_enum(body, "origin", ORIGINS, required=True)
    qualification_item_id = v.get_id(body, "qualification_item_id", required=False)
    source_subcontract_id = v.get_id(body, "source_subcontract_id", required=False)

    project = lookups.project(project_id)
    item = None
    subcontract = None
    if qualification_item_id is not None:
        item = lookups.qualification_item(qualification_item_id)
    if source_subcontract_id is not None:
        subcontract = lookups.resource(
            db.subcontracts, source_subcontract_id, "subcontract"
        )

    if item is not None:
        owner_project = lookups.project_of_qualification_item(item)
        if owner_project is None or owner_project["id"] != project["id"]:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "qualification_item_id belongs to a different project",
            )
    if subcontract is not None:
        owner_project = lookups.project_of_subcontract(subcontract)
        if owner_project is None or owner_project["id"] != project["id"]:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "source_subcontract_id belongs to a different project",
            )

    event = new_record({
        "project_id": project["id"],
        "qualification_item_id": qualification_item_id,
        "source_subcontract_id": source_subcontract_id,
        "description": description,
        "estimated_amount": estimated_amount,
        "origin": origin,
        "classification": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "classified_by_user_id": None,
        "classified_at": None,
        "review_note": None,
        "revision_count": 0,
    })
    db.change_events[event["id"]] = event
    return resp.created(serializers.change_event(event))


@bp.route("/change-events/<cid>/submit", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def submit_change_event(cid):
    body = v.json_body()
    v.get_str(body, "submit_note", required=False, min_len=0)
    event = lookups.change_event(cid)
    project = lookups.project(event["project_id"])
    guards.require_gmp_executed(project)
    if event["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_CHANGE_EVENT_STATE_INVALID",
            "status is %s; submit requires DRAFT or REVISION_REQUESTED"
            % event["status"],
        )
    if event["origin"] == "ALLOWANCE_OVERRUN":
        item = db.qualification_items.get(event["qualification_item_id"]) \
            if event["qualification_item_id"] else None
        if item is None or item["item_type"] != "ALLOWANCE":
            raise ApiError(
                "ERR_CHANGE_EVENT_STATE_INVALID",
                "an ALLOWANCE_OVERRUN change event must name a qualification item "
                "whose item_type is ALLOWANCE",
            )
    event["status"] = "SUBMITTED"
    event["submitted_by_user_id"] = g.user_id
    touch(event)
    return resp.ok(serializers.change_event(event))


@bp.route("/change-events/<cid>/review", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def review_change_event(cid):
    body = v.json_body()
    action = v.get_enum(body, "action", REVIEW_ACTIONS, required=True)
    review_note = v.get_str(body, "review_note", required=False, min_len=0)
    event = lookups.change_event(cid)
    if action == "BEGIN_REVIEW":
        if event["status"] != "SUBMITTED":
            raise ApiError(
                "ERR_CHANGE_EVENT_STATE_INVALID",
                "status is %s; BEGIN_REVIEW requires SUBMITTED" % event["status"],
            )
        event["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_REVISION":
        if event["status"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_CHANGE_EVENT_STATE_INVALID",
                "status is %s; REQUEST_REVISION requires UNDER_REVIEW"
                % event["status"],
            )
        event["status"] = "REVISION_REQUESTED"
        event["revision_count"] = event["revision_count"] + 1
    else:
        if event["status"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_CHANGE_EVENT_STATE_INVALID",
                "status is %s; REJECT requires UNDER_REVIEW" % event["status"],
            )
        event["status"] = "REJECTED"
    if review_note is not None:
        event["review_note"] = review_note
    touch(event)
    return resp.ok(serializers.change_event(event))


def _mint_amendment(project, event):
    proposal = new_record({
        "project_id": project["id"],
        "proposal_type": "AMENDMENT",
        "based_on_estimate_id": None,
        "change_event_id": event["id"],
        "cost_of_work_total": MONEY_ZERO,
        "general_conditions_total": MONEY_ZERO,
        "owner_contingency_amount": MONEY_ZERO,
        "construction_contingency_amount": MONEY_ZERO,
        "amount_delta": event["estimated_amount"],
        "provisional_fee_amount": MONEY_ZERO,
        "insurance_amount": MONEY_ZERO,
        "cm_fee_amount": MONEY_ZERO,
        "gmp_amount": q2(project["gmp_amount"] + event["estimated_amount"]),
        "status": "DRAFT",
        "owner_decision_note": None,
        "revision_count": 0,
        "superseded_by_proposal_id": None,
    })
    db.proposals[proposal["id"]] = proposal
    derive.rollup_amendments(project)
    derive.mark_reconciled_estimates_stale(project)
    return proposal


def _requires_owner_approval(project, contingency_type, amount, origin):
    """PRD 3.7 approval requirement, evaluated once at mint time."""
    if contingency_type == "OWNER":
        return True
    if amount > DRAW_OWNER_APPROVAL_THRESHOLD:
        return True
    if project["contingency_posture"] == "CONSTRAINED":
        return True
    if origin == "SUBCONTRACTOR_DEFAULT_PREMIUM":
        return True
    return False


def _mint_draw(project, event, contingency_type):
    draw = new_record({
        "project_id": project["id"],
        "change_event_id": event["id"],
        "source_subcontract_id": None,
        "contingency_type": contingency_type,
        "origin": "CHANGE_EVENT_CLASSIFICATION",
        "amount": event["estimated_amount"],
        "requires_owner_approval": _requires_owner_approval(
            project, contingency_type, event["estimated_amount"],
            "CHANGE_EVENT_CLASSIFICATION",
        ),
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "posted_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    db.draws[draw["id"]] = draw
    return draw


@bp.route("/change-events/<cid>/classify", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE, CONSTRUCTION_MANAGER)
def classify_change_event(cid):
    body = v.json_body()
    classification = v.get_enum(
        body, "classification", CLASSIFICATIONS, required=True
    )
    v.get_str(body, "classification_note", required=False, min_len=0)
    event = lookups.change_event(cid)
    project = lookups.project(event["project_id"])

    guards.require_not_settled(project)
    guards.require_gmp_executed(project)
    if event["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_CHANGE_EVENT_STATE_INVALID",
            "status is %s; classify requires UNDER_REVIEW" % event["status"],
        )
    if event["submitted_by_user_id"] is not None \
            and g.user_id == event["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the operator that submitted the change event may not classify it",
        )

    event["status"] = "CLASSIFIED"
    event["classification"] = classification
    event["classified_by_user_id"] = g.user_id
    event["classified_at"] = clock.now()

    if classification == "SCOPE_CHANGE":
        _mint_amendment(project, event)
    elif classification == "CONTINGENCY_USE_OWNER":
        _mint_draw(project, event, "OWNER")
    else:
        _mint_draw(project, event, "CONSTRUCTION")

    touch(event)
    touch(project)
    return resp.ok(serializers.change_event(event))


@bp.route("/change-events", methods=["GET"])
@endpoint(*READ_ROLES)
def list_change_events():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    qualification_item_id = v.query_filter("qualification_item_id")
    source_subcontract_id = v.query_filter("source_subcontract_id")
    status = v.query_filter("status", EVENT_STATUSES)
    classification = v.query_filter("classification", CLASSIFICATIONS)
    origin = v.query_filter("origin", ORIGINS)
    rows = []
    for row in db.change_events.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if qualification_item_id is not None \
                and row["qualification_item_id"] != qualification_item_id:
            continue
        if source_subcontract_id is not None \
                and row["source_subcontract_id"] != source_subcontract_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if classification is not None and row["classification"] != classification:
            continue
        if origin is not None and row["origin"] != origin:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing(
        [serializers.change_event(r) for r in page], limit, offset, total
    )


@bp.route("/change-events/<cid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_change_event(cid):
    return resp.ok(serializers.change_event(lookups.change_event(cid)))

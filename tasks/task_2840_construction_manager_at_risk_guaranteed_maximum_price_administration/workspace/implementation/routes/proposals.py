"""GmpProposal endpoints (PRD 3.2)."""
from flask import Blueprint

import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError
from money import MONEY_ZERO, RATIO_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)
from services import derive, pricing

bp = Blueprint("proposals", __name__)

PROPOSAL_TYPES = ("BASE", "AMENDMENT")
PROPOSAL_STATUSES = (
    "DRAFT",
    "OWNER_REVIEW",
    "RETURNED_FOR_REVISION",
    "EXECUTED",
    "REJECTED",
    "SUPERSEDED",
)
SUPERSEDABLE = ("DRAFT", "OWNER_REVIEW", "RETURNED_FOR_REVISION")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


@bp.route("/gmp-proposals", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_proposal():
    body = v.json_body()
    project_id = v.get_id(body, "project_id", required=True)
    based_on_estimate_id = v.get_id(body, "based_on_estimate_id", required=True)
    cost_of_work_total = v.get_money(
        body, "cost_of_work_total", required=True, positive=True
    )
    general_conditions_total = v.get_money(
        body, "general_conditions_total", required=True
    )
    owner_contingency_amount = v.get_money(
        body, "owner_contingency_amount", required=True
    )
    construction_contingency_amount = v.get_money(
        body, "construction_contingency_amount", required=True, positive=True
    )
    expected_project_version = v.get_int(
        body, "expected_project_version", required=True
    )

    project = lookups.project(project_id)
    estimate = lookups.estimate(based_on_estimate_id)

    if project["version"] != expected_project_version:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version %s does not match %s"
            % (expected_project_version, project["version"]),
        )

    guards.require_gmp_not_executed(project)

    if estimate["status"] != "RECONCILED":
        raise ApiError(
            "ERR_ESTIMATE_STATE_INVALID",
            "based_on_estimate_id status is %s, not RECONCILED" % estimate["status"],
        )
    if estimate["project_id"] != project["id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "based_on_estimate_id belongs to a different project",
        )

    figures = pricing.gmp_buildup(
        project["cm_fee_pct"],
        project["insurance_rate"],
        cost_of_work_total,
        general_conditions_total,
        owner_contingency_amount,
        construction_contingency_amount,
    )

    proposal = new_record({
        "project_id": project["id"],
        "proposal_type": "BASE",
        "based_on_estimate_id": estimate["id"],
        "change_event_id": None,
        "cost_of_work_total": cost_of_work_total,
        "general_conditions_total": general_conditions_total,
        "owner_contingency_amount": owner_contingency_amount,
        "construction_contingency_amount": construction_contingency_amount,
        "amount_delta": MONEY_ZERO,
        "provisional_fee_amount": figures["provisional_fee_amount"],
        "insurance_amount": figures["insurance_amount"],
        "cm_fee_amount": figures["cm_fee_amount"],
        "gmp_amount": figures["gmp_amount"],
        "status": "DRAFT",
        "owner_decision_note": None,
        "revision_count": 0,
        "superseded_by_proposal_id": None,
    })
    db.proposals[proposal["id"]] = proposal

    for other in list(db.proposals.values()):
        if other["id"] == proposal["id"]:
            continue
        if other["project_id"] != project["id"]:
            continue
        if other["proposal_type"] != "BASE":
            continue
        if other["status"] not in SUPERSEDABLE:
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_proposal_id"] = proposal["id"]
        touch(other)

    touch(project)
    return resp.created(serializers.proposal(proposal))


@bp.route("/gmp-proposals/<pid>/submit", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def submit_proposal(pid):
    body = v.json_body()
    v.get_str(body, "cover_note", required=False, min_len=0)
    proposal = lookups.proposal(pid)
    if proposal["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError(
            "ERR_PROPOSAL_STATE_INVALID",
            "proposal status is %s; submit requires DRAFT or RETURNED_FOR_REVISION"
            % proposal["status"],
        )
    project = lookups.project(proposal["project_id"])

    if proposal["proposal_type"] == "BASE":
        estimate = db.estimates.get(proposal["based_on_estimate_id"])
        if estimate is None or estimate["status"] != "RECONCILED":
            raise ApiError(
                "ERR_ESTIMATE_STATE_INVALID",
                "the based_on_estimate_id is no longer RECONCILED",
            )
    else:
        event = db.change_events.get(proposal["change_event_id"])
        if (event is None or event["status"] != "CLASSIFIED"
                or event["classification"] != "SCOPE_CHANGE"):
            raise ApiError(
                "ERR_CHANGE_EVENT_STATE_INVALID",
                "the linked change event is not CLASSIFIED as SCOPE_CHANGE",
            )

    proposal["status"] = "OWNER_REVIEW"
    touch(proposal)

    if proposal["proposal_type"] == "BASE":
        if project["gmp_status"] != "GMP_UNDER_REVIEW":
            project["gmp_status"] = "GMP_UNDER_REVIEW"
            touch(project)
    return resp.ok(serializers.proposal(proposal))


def _execute_base(project, proposal):
    project["gmp_status"] = "EXECUTED"
    project["gmp_amount"] = proposal["gmp_amount"]
    project["cost_of_work_budget_total"] = proposal["cost_of_work_total"]
    project["general_conditions_total"] = proposal["general_conditions_total"]
    project["insurance_amount"] = proposal["insurance_amount"]
    project["cm_fee_amount"] = proposal["cm_fee_amount"]
    project["owner_contingency_original"] = proposal["owner_contingency_amount"]
    project["owner_contingency_remaining"] = proposal["owner_contingency_amount"]
    project["construction_contingency_original"] = \
        proposal["construction_contingency_amount"]
    project["construction_contingency_remaining"] = \
        proposal["construction_contingency_amount"]
    project["contingency_drawn_to_cost_total"] = MONEY_ZERO
    derive.rollup_amendments(project)
    derive.apply_posture(project)


def _execute_amendment(project, proposal):
    delta = proposal["amount_delta"]
    project["gmp_amount"] = q2(project["gmp_amount"] + delta)
    project["cost_of_work_budget_total"] = q2(
        project["cost_of_work_budget_total"] + delta
    )
    derive.rollup_amendments(project)


@bp.route("/gmp-proposals/<pid>/decide", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def decide_proposal(pid):
    body = v.json_body()
    decision = v.get_enum(
        body, "decision", ("EXECUTE", "RETURN", "REJECT"), required=True
    )
    owner_decision_note = v.get_str(
        body, "owner_decision_note", required=False, min_len=0
    )
    proposal = lookups.proposal(pid)
    if proposal["status"] != "OWNER_REVIEW":
        raise ApiError(
            "ERR_PROPOSAL_STATE_INVALID",
            "proposal status is %s; a decision requires OWNER_REVIEW"
            % proposal["status"],
        )
    project = lookups.project(proposal["project_id"])
    is_base = proposal["proposal_type"] == "BASE"

    if decision == "REJECT" and is_base:
        raise ApiError(
            "ERR_PROPOSAL_STATE_INVALID",
            "REJECT is only permitted on an AMENDMENT proposal",
        )
    if decision == "EXECUTE":
        if is_base:
            guards.require_gmp_not_executed(project)
        else:
            guards.require_gmp_executed(project)

    if owner_decision_note is not None:
        proposal["owner_decision_note"] = owner_decision_note

    project_changed = False
    if decision == "EXECUTE":
        proposal["status"] = "EXECUTED"
        if is_base:
            _execute_base(project, proposal)
        else:
            _execute_amendment(project, proposal)
        project_changed = True
    elif decision == "RETURN":
        proposal["status"] = "RETURNED_FOR_REVISION"
        proposal["revision_count"] = proposal["revision_count"] + 1
        if is_base:
            if project["gmp_status"] == "GMP_UNDER_REVIEW":
                project["gmp_status"] = "PRECONSTRUCTION"
                project_changed = True
        else:
            derive.rollup_amendments(project)
    else:
        proposal["status"] = "REJECTED"
        derive.rollup_amendments(project)
        project_changed = True

    touch(proposal)
    if project_changed:
        touch(project)
    return resp.ok(serializers.proposal(proposal))


@bp.route("/gmp-proposals", methods=["GET"])
@endpoint(*READ_ROLES)
def list_proposals():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    based_on = v.query_filter("based_on_estimate_id")
    change_event_id = v.query_filter("change_event_id")
    superseded_by = v.query_filter("superseded_by_proposal_id")
    proposal_type = v.query_filter("proposal_type", PROPOSAL_TYPES)
    status = v.query_filter("status", PROPOSAL_STATUSES)
    rows = []
    for row in db.proposals.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if based_on is not None and row["based_on_estimate_id"] != based_on:
            continue
        if change_event_id is not None and row["change_event_id"] != change_event_id:
            continue
        if superseded_by is not None and row["superseded_by_proposal_id"] != superseded_by:
            continue
        if proposal_type is not None and row["proposal_type"] != proposal_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing([serializers.proposal(r) for r in page], limit, offset, total)


@bp.route("/gmp-proposals/<pid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_proposal(pid):
    return resp.ok(serializers.proposal(lookups.proposal(pid)))

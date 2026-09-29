"""Corrective action plans and the remediation liability ledger (PRD 3.8)."""

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import actor, guard
from enums import ALL_ROLES, CAP_CLOSURE_OUTCOMES, CAP_DECISION_OUTCOMES, REMEDY_TYPES
from envelope import success
from errors import ApiError
from helpers import list_response
from store import db, lookup_path, new_row, touch

bp = Blueprint("corrective_action_plans", __name__)


@bp.route("/corrective-action-plans", methods=["POST"])
@guard("PlanSponsor", "ComplianceOfficer")
def create_cap():
    payload = shape.body()
    raw_item = shape.raw_fk(payload, "nqtl_item_id")
    if raw_item is not None and raw_item not in db.nqtl_items:
        raise ApiError("ERR_NQTL_ITEM_NOT_FOUND")

    item_id = shape.req_string(payload, "nqtl_item_id", 1, None)
    remedy_type = shape.req_enum(payload, "remedy_type", REMEDY_TYPES)
    affected_claims_count = shape.req_int(payload, "affected_claims_count", 0, None)
    average_claim_cents = shape.req_int(payload, "average_claim_cents", 0, None)
    target_text, _target_date = shape.req_date(payload, "target_completion_date")

    item = db.nqtl_items[item_id]
    plan_year = recompute.plan_year_of_item(item)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if item["status"] != "VIOLATION":
        raise ApiError("ERR_ITEM_NOT_IN_VIOLATION")

    row = new_row({
        "nqtl_item_id": item_id,
        "remedy_type": remedy_type,
        "affected_claims_count": affected_claims_count,
        "average_claim_cents": average_claim_cents,
        "target_completion_date": target_text,
        "reprocessing_liability_cents": calc.reprocessing_liability_cents(
            remedy_type, affected_claims_count, average_claim_cents),
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    db.caps[row["id"]] = row
    return success(serialize.corrective_action_plan(row), 201)


@bp.route("/corrective-action-plans/<cap_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_cap(cap_id):
    row = lookup_path(db.caps, cap_id, "ERR_CAP_NOT_FOUND")
    return success(serialize.corrective_action_plan(row))


@bp.route("/corrective-action-plans", methods=["GET"])
@guard(*ALL_ROLES)
def list_caps():
    return list_response(db.caps.values(), serialize.corrective_action_plan,
                         ("nqtl_item_id", "status", "remedy_type"))


@bp.route("/corrective-action-plans/<cap_id>/decision", methods=["POST"])
@guard("ComplianceOfficer")
def decide_cap(cap_id):
    cap = lookup_path(db.caps, cap_id, "ERR_CAP_NOT_FOUND")
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", CAP_DECISION_OUTCOMES)
    shape.opt_string(payload, "decision_note", 1, None)

    item = db.nqtl_items.get(cap["nqtl_item_id"])
    plan_year = recompute.plan_year_of_cap(cap)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if cap["status"] != "DRAFT":
        raise ApiError("ERR_CAP_NOT_DRAFT")
    if item is None or item["status"] != "VIOLATION":
        raise ApiError("ERR_ITEM_NOT_IN_VIOLATION")
    # Step 19: whoever found the violation may not decide the remedy.
    if item["determination_recorded_by_user_id"] == actor():
        raise ApiError("ERR_APPROVER_IS_DETERMINER")
    # Step 34: the board's ceiling is evaluated last.
    if outcome == "APPROVED" and plan_year is not None:
        projected = (plan_year["remediation_liability_cents"]
                     + cap["reprocessing_liability_cents"])
        if projected > plan_year["remediation_liability_cap_cents"]:
            raise ApiError("ERR_LIABILITY_CAP_EXCEEDED")

    if outcome == "APPROVED":
        cap["status"] = "APPROVED"
        cap["approved_by_user_id"] = actor()
        touch(cap)
        if plan_year is not None:
            recompute.recompute_plan_year(plan_year, bump=True)
    else:
        cap["status"] = "REJECTED"
        touch(cap)
        if plan_year is not None:
            recompute.recompute_plan_year(plan_year)
    return success(serialize.corrective_action_plan(cap))


@bp.route("/corrective-action-plans/<cap_id>/closure", methods=["POST"])
@guard("ComplianceOfficer")
def close_cap(cap_id):
    cap = lookup_path(db.caps, cap_id, "ERR_CAP_NOT_FOUND")
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", CAP_CLOSURE_OUTCOMES)
    shape.opt_string(payload, "closure_note", 1, None)

    item = db.nqtl_items.get(cap["nqtl_item_id"])
    plan_year = recompute.plan_year_of_cap(cap)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if cap["status"] != "APPROVED":
        raise ApiError("ERR_CAP_NOT_APPROVED")
    if outcome == "COMPLETED" and (item is None or item["status"] != "VIOLATION"):
        raise ApiError("ERR_ITEM_NOT_IN_VIOLATION")

    cap["status"] = outcome
    touch(cap)
    if outcome == "COMPLETED":
        item["status"] = "REMEDIATED"
        touch(item)
        recompute.create_participant_notice(item, "CORRECTION_COMPLETED",
                                           "CAP_CLOSURE_CASCADE")
    if plan_year is not None:
        recompute.recompute_plan_year(plan_year, bump=True)
    return success(serialize.corrective_action_plan(cap))

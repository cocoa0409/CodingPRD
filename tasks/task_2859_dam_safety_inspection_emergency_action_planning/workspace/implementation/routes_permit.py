"""Permitting construction, repair and removal (PRD Section 3.6)."""

from flask import Blueprint, request

import calc
import guards
import services
from common import (
    ApiError, body_dict, ok, ok_list, pagination, q_enum, q_str,
    v_dt, v_enum, v_int, v_string,
)
from derive import (
    dam_hazard_class, dam_latest_accepted_inspection, dam_latest_eap_status,
    dam_safety_status, owner_is_delinquent, paginate, serialize_permit,
)
from store import db, insert, touch

bp = Blueprint("permits", __name__)


def _price(permit, dam, owner):
    return calc.permit_fees(permit["estimated_project_cost_cents"], permit["permit_type"],
                            dam_hazard_class(dam), owner_is_delinquent(owner["id"]))


@bp.route("/permits", methods=["POST"])
def create_permit():
    user_id, role = guards.authenticate(request, ("DamOwner",))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    permit_type = v_enum(body, "permit_type", calc.PERMIT_TYPES)
    scope_description = v_string(body, "scope_description", min_len=1)
    estimated_project_cost_cents = v_int(body, "estimated_project_cost_cents", minimum=1)
    proposed_start_date = v_dt(body, "proposed_start_date")
    dam = guards.get_dam(dam_id)
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, dam["owner_id"])
    guards.check_dam_operable(dam, block_removal_permitted=True)
    guards.check_dam_classified(dam)

    owner = guards.get_owner(dam["owner_id"])
    fees = calc.permit_fees(estimated_project_cost_cents, permit_type,
                            dam_hazard_class(dam), owner_is_delinquent(owner["id"]))
    permit = insert(db.permits, {
        "dam_id": dam["id"],
        "owner_id": dam["owner_id"],
        "review_engineer_id": None,
        "permit_type": permit_type,
        "scope_description": scope_description,
        "estimated_project_cost_cents": estimated_project_cost_cents,
        "proposed_start_date": proposed_start_date,
        "base_fee_cents": fees["base_fee_cents"],
        "engineering_review_fee_cents": fees["engineering_review_fee_cents"],
        "delinquency_surcharge_cents": fees["delinquency_surcharge_cents"],
        "volume_credit_cents": fees["volume_credit_cents"],
        "total_fee_cents": fees["total_fee_cents"],
        "status": "SUBMITTED",
        "decision_findings": None,
        "conditions": None,
        "revision_count": 0,
        "issued_at": None,
    })
    if fees["total_fee_cents"] != 0:
        services.post_ledger_entry(
            owner["id"], "PERMIT_REVIEW_FEE", fees["total_fee_cents"],
            services.SYSTEM_USER_ID, source_ref=permit["id"],
            memo="Permit review fee at application")
    return ok(serialize_permit(permit), 201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def read_permit(permit_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    permit = guards.get_permit(permit_id)
    guards.check_identity(user_id, role)
    return ok(serialize_permit(permit))


@bp.route("/permits", methods=["GET"])
def list_permits():
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    owner_id = q_str("owner_id")
    review_engineer_id = q_str("review_engineer_id")
    permit_type = q_enum("permit_type", calc.PERMIT_TYPES)
    status = q_enum("status", calc.PERMIT_STATUSES)
    guards.check_identity(user_id, role)
    rows = list(db.permits.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if review_engineer_id is not None:
        rows = [r for r in rows if r["review_engineer_id"] == review_engineer_id]
    if permit_type is not None:
        rows = [r for r in rows if r["permit_type"] == permit_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = paginate(rows, limit, offset, serialize_permit)
    return ok_list(data, limit, offset, total)


@bp.route("/permits/<permit_id>/assign-review", methods=["POST"])
def assign_permit_review(permit_id):
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    review_engineer_id = v_string(body, "review_engineer_id", min_len=1)
    permit = guards.get_permit(permit_id)
    engineer = guards.get_engineer(review_engineer_id)
    guards.check_permit_state(permit, ("SUBMITTED",))
    guards.check_license_active(engineer)
    # Rung 37: the reviewer may not be the engineer of record on the dam's
    # latest accepted inspection.
    dam = guards.get_dam(permit["dam_id"])
    latest_accepted = dam_latest_accepted_inspection(dam["id"])
    if latest_accepted is not None and latest_accepted["engineer_id"] == engineer["id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the engineer of record on the latest accepted inspection may not review this permit")
    permit["review_engineer_id"] = engineer["id"]
    permit["status"] = "UNDER_ENGINEERING_REVIEW"
    touch(permit)
    return ok(serialize_permit(permit))


@bp.route("/permits/<permit_id>/decision", methods=["POST"])
def decide_permit(permit_id):
    user_id, role = guards.authenticate(request, ("Engineer",))
    body = body_dict()
    decision = v_enum(body, "decision", ("ISSUE", "DENY", "RETURN"))
    findings = v_string(body, "findings", min_len=1)
    conditions = v_string(body, "conditions", required=False)
    permit = guards.get_permit(permit_id)
    engineer = guards.check_identity(user_id, role)
    # Rung 8 is skipped entirely while review_engineer_id is null: such a permit
    # is still SUBMITTED and is reported as ERR_PERMIT_INVALID_STATE instead.
    if permit["review_engineer_id"] is not None:
        guards.check_assigned_engineer(user_id, permit["review_engineer_id"])
    guards.check_permit_state(permit, ("UNDER_ENGINEERING_REVIEW",))
    guards.check_license_active(engineer)
    dam = guards.get_dam(permit["dam_id"])
    owner = guards.get_owner(permit["owner_id"])
    hazard_class = dam_hazard_class(dam)
    # Rung 22: construction on an UNSATISFACTORY structure is barred.
    if permit["permit_type"] == "CONSTRUCTION" and dam_safety_status(dam) == "UNSATISFACTORY":
        raise ApiError("ERR_UNSAFE_DAM_PERMIT_BLOCKED",
                       "construction is barred while the dam is rated UNSATISFACTORY")
    # Rung 23: a HIGH-hazard dam needs an approved emergency action plan.
    if hazard_class == "HIGH" and dam_latest_eap_status(dam["id"]) != "APPROVED":
        raise ApiError("ERR_EAP_NOT_APPROVED",
                       "a HIGH-hazard dam requires an approved emergency action plan")
    # Rungs 35 and 36: the fiscal gates guard the decision itself.
    guards.check_owner_not_delinquent(owner["id"])
    guards.check_financial_assurance(owner, hazard_class)

    permit["decision_findings"] = findings
    if decision == "ISSUE":
        permit["status"] = "ISSUED"
        permit["issued_at"] = db.clock
        permit["conditions"] = conditions
        touch(permit)
        if permit["permit_type"] == "REMOVAL" and dam["regulatory_status"] == "REGISTERED":
            dam["regulatory_status"] = "REMOVAL_PERMITTED"
            touch(dam)
    elif decision == "DENY":
        permit["status"] = "DENIED"
        touch(permit)
    else:
        permit["status"] = "RETURNED_FOR_REVISION"
        touch(permit)
    return ok(serialize_permit(permit))


@bp.route("/permits/<permit_id>/resubmit", methods=["POST"])
def resubmit_permit(permit_id):
    user_id, role = guards.authenticate(request, ("DamOwner",))
    body = body_dict()
    scope_description = v_string(body, "scope_description", min_len=1)
    estimated_project_cost_cents = v_int(body, "estimated_project_cost_cents", minimum=1)
    permit = guards.get_permit(permit_id)
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, permit["owner_id"])
    guards.check_permit_state(permit, ("RETURNED_FOR_REVISION",))
    dam = guards.get_dam(permit["dam_id"])
    owner = guards.get_owner(permit["owner_id"])

    previous_total = permit["total_fee_cents"]
    permit["scope_description"] = scope_description
    permit["estimated_project_cost_cents"] = estimated_project_cost_cents
    permit["revision_count"] = permit["revision_count"] + 1
    permit["review_engineer_id"] = None
    permit["status"] = "SUBMITTED"
    fees = calc.permit_fees(estimated_project_cost_cents, permit["permit_type"],
                            dam_hazard_class(dam), owner_is_delinquent(owner["id"]))
    permit.update(fees)
    touch(permit)

    delta = fees["total_fee_cents"] - previous_total
    if delta > 0:
        services.post_ledger_entry(
            owner["id"], "PERMIT_REVIEW_FEE", delta, services.SYSTEM_USER_ID,
            source_ref=permit["id"], memo="Permit review fee adjustment on resubmission")
    elif delta < 0:
        services.post_ledger_entry(
            owner["id"], "FEE_VOID", delta, services.SYSTEM_USER_ID,
            source_ref=permit["id"], memo="Permit review fee void on resubmission")
    return ok(serialize_permit(permit))

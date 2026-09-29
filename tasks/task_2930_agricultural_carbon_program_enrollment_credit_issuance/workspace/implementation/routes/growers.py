"""Grower onboarding, standing and the reconciliation read."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import common, serialize

bp = Blueprint("growers", __name__)

OPERATOR_TYPES = ("SOLE_PROPRIETOR", "LLC", "PARTNERSHIP", "CORPORATION", "TRUST")

LIST_FILTERS = {
    "status": ("status", "str"),
    "mailing_state": ("mailing_state", "str"),
}


@bp.route("/growers", methods=["POST"])
def create_grower():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    legal_name = v.v_str(body, "legal_name")
    if len(legal_name) > 200:
        v.bad("Field 'legal_name' may not exceed 200 characters.")
    operator_type = v.v_enum(body, "operator_type", OPERATOR_TYPES)
    tax_id = v.v_str(body, "tax_id")
    mailing_state = v.v_str(body, "mailing_state")
    if len(mailing_state) != 2 or not mailing_state.isalpha() or mailing_state != mailing_state.upper():
        v.bad("Field 'mailing_state' must be exactly two upper-case letters.")

    row = db.common_fields()
    row.update({
        "legal_name": legal_name,
        "operator_type": operator_type,
        "tax_id": tax_id,
        "mailing_state": mailing_state,
        "status": "ACTIVE",
        "suspension_reason": None,
        "total_enrolled_acres": Decimal("0.00"),
        "lifetime_credits_issued": 0,
        "net_paid_cents": 0,
        "outstanding_clawback_cents": 0,
        "reversal_count": 0,
    })
    db.growers[row["id"]] = row
    return resp.object_response(serialize.grower(row), 201)


@bp.route("/growers", methods=["GET"])
def list_growers():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_REGISTRY_OFFICER)
    rows = common.apply_filters(db.growers.values(), LIST_FILTERS)
    return resp.paginate(rows, serialize.grower)


@bp.route("/growers/<grower_id>", methods=["GET"])
def read_grower(grower_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_REGISTRY_OFFICER)
    row = common.get_grower(grower_id)
    mw.require_grower_owner(row["id"])
    return resp.object_response(serialize.grower(row))


@bp.route("/growers/<grower_id>/ledger-summary", methods=["GET"])
def ledger_summary(grower_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_REGISTRY_OFFICER)
    grower = common.get_grower(grower_id)

    buffer_contributed = 0
    for batch in db.credit_batches.values():
        enrollment = db.enrollments.get(batch["enrollment_id"])
        if enrollment is None or enrollment["grower_id"] != grower["id"]:
            continue
        if batch["issuance_status"] == "ISSUED":
            buffer_contributed += batch["buffer_credits"]

    accrued = 0
    paid = 0
    clawed_back = 0
    for payment in db.grower_payments.values():
        enrollment = db.enrollments.get(payment["enrollment_id"])
        if enrollment is None or enrollment["grower_id"] != grower["id"]:
            continue
        if payment["status"] == "ACCRUED":
            accrued += payment["net_amount_cents"]
        elif payment["status"] == "PAID":
            paid += payment["net_amount_cents"]
        elif payment["status"] == "CLAWED_BACK":
            clawed_back += payment["net_amount_cents"]

    return resp.object_response({
        "grower_id": grower["id"],
        "lifetime_credits_issued": grower["lifetime_credits_issued"],
        "buffer_contributed_credits": buffer_contributed,
        "accrued_total_cents": accrued,
        "paid_total_cents": paid,
        "clawed_back_total_cents": clawed_back,
        "outstanding_clawback_cents": grower["outstanding_clawback_cents"],
    })


@bp.route("/growers/<grower_id>/suspend", methods=["POST"])
def suspend_grower(grower_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    grower = common.get_grower(grower_id)
    body = v.json_body()
    reason = v.v_str(body, "suspension_reason")
    if grower["status"] != "ACTIVE":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE grower may be suspended.")
    common.suspend_grower_cascade(grower, reason)
    return resp.object_response(serialize.grower(grower))


@bp.route("/growers/<grower_id>/reinstate", methods=["POST"])
def reinstate_grower(grower_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    grower = common.get_grower(grower_id)
    v.json_body()
    if grower["status"] != "SUSPENDED":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a SUSPENDED grower may be reinstated.")
    common.reinstate_grower_cascade(grower)
    return resp.object_response(serialize.grower(grower))

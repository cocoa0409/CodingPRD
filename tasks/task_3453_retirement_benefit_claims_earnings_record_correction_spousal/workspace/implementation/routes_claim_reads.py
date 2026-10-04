"""Claim collection list and claim-scoped sub-resource lists: payments,
overpayment cases, payee cases, recomputation events. Lists are sorted by
created_at ASC and paginated with the envelope's limit/offset fields.
"""

from flask import Blueprint, request

from db import store, created_key
from envelope import ok, paginate
from errors import ApiError, ERR_CLAIM_NOT_FOUND, ERR_FORBIDDEN_OWNERSHIP
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    claimant_owns,
    is_claimant,
    require_role,
)
from serializers import (
    claim_dict,
    overpayment_dict,
    payee_dict,
    payment_dict,
    recomputation_dict,
)

bp = Blueprint("claim_reads", __name__)

LIST_ROLES = {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, ROLE_PROGRAM_ADMINISTRATOR, ROLE_CLAIMANT}
NARROW_ROLES = {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, ROLE_CLAIMANT}


def _load_claim(claim_id):
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"No claim with id {claim_id}.")
    return c


@bp.route("/ssa/claims", methods=["GET"])
def list_claims():
    ctx = authenticate()
    require_role(ctx, LIST_ROLES)
    f_worker = request.args.get("worker_id")
    f_relationship = request.args.get("relationship_id")
    f_status = request.args.get("status")
    if is_claimant(ctx):
        if f_worker is not None and f_worker != ctx["user_id"]:
            raise ApiError(
                ERR_FORBIDDEN_OWNERSHIP, "Claimant may only list their own claims."
            )
        f_worker = ctx["user_id"]
    rows = list(store.claims.values())
    if f_worker is not None:
        rows = [c for c in rows if c["worker_id"] == f_worker]
    if f_relationship is not None:
        rows = [c for c in rows if c["relationship_id"] == f_relationship]
    if f_status is not None:
        rows = [c for c in rows if c["status"] == f_status]
    rows.sort(key=created_key)
    page, fields = paginate(rows)
    return ok([claim_dict(c) for c in page], page=fields)


def _list_claim_children(claim_id, table, serializer, roles):
    ctx = authenticate()
    require_role(ctx, roles)
    claim = _load_claim(claim_id)
    claimant_owns(ctx, claim["worker_id"])
    rows = [r for r in table.values() if r["claim_id"] == claim_id]
    rows.sort(key=created_key)
    page, fields = paginate(rows)
    return ok([serializer(r) for r in page], page=fields)


@bp.route("/ssa/claims/<claim_id>/payments", methods=["GET"])
def list_payments(claim_id):
    return _list_claim_children(claim_id, store.payments, payment_dict, LIST_ROLES)


@bp.route("/ssa/claims/<claim_id>/overpayment-cases", methods=["GET"])
def list_overpayment_cases(claim_id):
    return _list_claim_children(claim_id, store.overpayments, overpayment_dict, NARROW_ROLES)


@bp.route("/ssa/claims/<claim_id>/payee-cases", methods=["GET"])
def list_payee_cases(claim_id):
    return _list_claim_children(claim_id, store.payees, payee_dict, NARROW_ROLES)


@bp.route("/ssa/claims/<claim_id>/recomputation-events", methods=["GET"])
def list_recomputation_events(claim_id):
    return _list_claim_children(claim_id, store.recomputations, recomputation_dict, LIST_ROLES)

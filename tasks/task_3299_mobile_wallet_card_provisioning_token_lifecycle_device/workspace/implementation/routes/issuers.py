# =============================================================================
# Issuers: create, get, activate, suspend, offboard, fee-projection,
# agreement listing
# =============================================================================
from flask import Blueprint

import db
from domain import (
    active_agreement_for_issuer, auths_for_issuer, compute_fee,
    offboard_issuer_cascade, suspend_issuer_cascade,
)
from errors import ApiError
from helpers import list_response, new_common_row, resolve_issuer
from middleware import get_body, req_str, require_roles
from response import success_object

bp = Blueprint("issuers", __name__)


@bp.post("/issuers")
def create_issuer():
    body = get_body()
    issuer_name = req_str(body, "issuer_name")
    country_code = req_str(body, "country_code")
    require_roles(["PlatformAdmin"])
    row = new_common_row({
        "issuer_name": issuer_name,
        "country_code": country_code,
        "status": "DRAFT",
    })
    db.issuers[row["id"]] = row
    return success_object(row, 201)


@bp.get("/issuers/<issuerId>")
def get_issuer(issuerId):
    return success_object(resolve_issuer(issuerId), 200)


@bp.post("/issuers/<issuerId>/activate")
def activate_issuer(issuerId):
    require_roles(["PlatformAdmin"])
    issuer = resolve_issuer(issuerId)
    if issuer["status"] == "DRAFT":
        # DRAFT -> ACTIVE requires at least one ACTIVE agreement
        if active_agreement_for_issuer(issuer["id"]) is None:
            raise ApiError("ERR_AGREEMENT_REQUIRED",
                           "Issuer activation requires at least one ACTIVE agreement")
        issuer["status"] = "ACTIVE"
    elif issuer["status"] == "SUSPENDED":
        # Reactivation does NOT auto-resume tokens
        issuer["status"] = "ACTIVE"
    else:
        raise ApiError("ERR_INVALID_STATE",
                       f"Issuer cannot be activated from {issuer['status']}")
    db.touch(issuer)
    return success_object(issuer, 200)


@bp.post("/issuers/<issuerId>/suspend")
def suspend_issuer(issuerId):
    require_roles(["PlatformAdmin"])
    issuer = resolve_issuer(issuerId)
    if issuer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Issuer cannot be suspended from {issuer['status']}")
    issuer["status"] = "SUSPENDED"
    db.touch(issuer)
    suspend_issuer_cascade(issuer)
    return success_object(issuer, 200)


@bp.post("/issuers/<issuerId>/offboard")
def offboard_issuer(issuerId):
    require_roles(["PlatformAdmin"])
    issuer = resolve_issuer(issuerId)
    if issuer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       f"Issuer cannot be offboarded from {issuer['status']}")
    issuer["status"] = "OFFBOARDED"
    db.touch(issuer)
    offboard_issuer_cascade(issuer)
    return success_object(issuer, 200)


@bp.get("/issuers/<issuerId>/fee-projection")
def fee_projection(issuerId):
    require_roles(["IssuerOperator", "PlatformAdmin", "CustomerService"])
    issuer = resolve_issuer(issuerId)
    approved_auths = auths_for_issuer(issuer["id"], {"APPROVED"})
    pending_auths = auths_for_issuer(issuer["id"], {"PENDING"})
    agreement = active_agreement_for_issuer(issuer["id"])

    def fee_of(auth):
        if agreement is None:
            return 0
        return compute_fee(auth["amount_cents"], agreement)

    approved_fee = sum(fee_of(a) for a in approved_auths)
    projected_fee = approved_fee + sum(fee_of(a) for a in pending_auths)
    return success_object({
        "projected_fee_cents": projected_fee,
        "approved_fee_cents": approved_fee,
        "authorization_count": len(approved_auths) + len(pending_auths),
    }, 200)


@bp.get("/issuers/<issuerId>/agreements")
def list_issuer_agreements(issuerId):
    resolve_issuer(issuerId)
    rows = [a for a in db.issuer_agreements.values() if a["issuer_id"] == issuerId]
    return list_response(rows)

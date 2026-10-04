# =============================================================================
# Issuer agreements: create, get, activate, supersede, terminate
# =============================================================================
from flask import Blueprint

import db
from domain import suspend_issuer_cascade
from errors import ApiError
from helpers import new_common_row, resolve_agreement, resolve_issuer
from middleware import get_body, opt_bool, opt_int, req_int, req_str, require_roles
from response import success_object

bp = Blueprint("issuer_agreements", __name__)

TERMS_FIELDS = [
    "branding_color", "branding_logo_ref", "terms_version",
    "fee_bps", "fee_cap_cents", "express_transit_supported",
    "effective_at", "expires_at",
]


def _read_terms_payload(body):
    """Schema-validated terms payload. Missing/typed-wrong -> ERR_VALIDATION."""
    terms = {
        "branding_color": req_str(body, "branding_color"),
        "branding_logo_ref": req_str(body, "branding_logo_ref"),
        "terms_version": req_str(body, "terms_version"),
        "fee_bps": req_int(body, "fee_bps"),
        "fee_cap_cents": req_int(body, "fee_cap_cents"),
        "fee_floor_cents": opt_int(body, "fee_floor_cents", 0),
        "express_transit_supported": opt_bool(body, "express_transit_supported", None),
        "effective_at": req_str(body, "effective_at"),
        "expires_at": req_str(body, "expires_at"),
    }
    if terms["express_transit_supported"] is None:
        raise ApiError("ERR_VALIDATION", "express_transit_supported is required")
    return terms


def _validate_terms(terms):
    """Business terms validation (ERR_TERMS_VALIDATION_FAILED, 422):
    fees non-negative, cap positive, cap not below floor, branding present."""
    if terms["fee_bps"] < 0 or terms["fee_floor_cents"] < 0:
        raise ApiError("ERR_TERMS_VALIDATION_FAILED", "Fees must be non-negative")
    if terms["fee_cap_cents"] <= 0:
        raise ApiError("ERR_TERMS_VALIDATION_FAILED", "fee_cap_cents must be positive")
    if terms["fee_cap_cents"] < terms["fee_floor_cents"]:
        raise ApiError("ERR_TERMS_VALIDATION_FAILED", "fee_cap_cents below fee_floor_cents")
    if not terms["branding_color"] or not terms["branding_logo_ref"]:
        raise ApiError("ERR_TERMS_VALIDATION_FAILED", "Branding color and logo are required")


@bp.post("/issuer-agreements")
def create_agreement():
    body = get_body()
    terms = _read_terms_payload(body)
    issuer_id = req_str(body, "issuer_id")
    require_roles(["PlatformAdmin"])
    resolve_issuer(issuer_id)
    _validate_terms(terms)
    row = new_common_row(dict(terms, issuer_id=issuer_id, status="PENDING"))
    db.issuer_agreements[row["id"]] = row
    return success_object(row, 201)


@bp.get("/issuer-agreements/<agreementId>")
def get_agreement(agreementId):
    return success_object(resolve_agreement(agreementId), 200)


@bp.post("/issuer-agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    require_roles(["PlatformAdmin"])
    agreement = resolve_agreement(agreementId)
    if agreement["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       f"Agreement cannot be activated from {agreement['status']}")
    # Priority 20: issuer not OFFBOARDED; no other ACTIVE agreement
    issuer = db.issuers.get(agreement["issuer_id"])
    if issuer is None or issuer["status"] == "OFFBOARDED":
        raise ApiError("ERR_ISSUER_NOT_ACTIVE", "Parent issuer is OFFBOARDED")
    for other in db.issuer_agreements.values():
        if (other["issuer_id"] == agreement["issuer_id"]
                and other["id"] != agreement["id"]
                and other["status"] == "ACTIVE"):
            raise ApiError("ERR_AGREEMENT_OVERLAP",
                           "An ACTIVE agreement already exists for this issuer")
    agreement["status"] = "ACTIVE"
    db.touch(agreement)
    return success_object(agreement, 200)


@bp.post("/issuer-agreements/<agreementId>/supersede")
def supersede_agreement(agreementId):
    body = get_body()
    terms = _read_terms_payload(body)
    require_roles(["PlatformAdmin"])
    agreement = resolve_agreement(agreementId)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Agreement cannot be superseded from {agreement['status']}")
    _validate_terms(terms)
    agreement["status"] = "SUPERSEDED"
    db.touch(agreement)
    # New agreement for the same issuer, born directly ACTIVE
    row = new_common_row(dict(terms, issuer_id=agreement["issuer_id"], status="ACTIVE"))
    db.issuer_agreements[row["id"]] = row
    # Tokens stay put; future auths use the new agreement's fee schedule.
    return success_object(row, 200)


@bp.post("/issuer-agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    require_roles(["PlatformAdmin"])
    agreement = resolve_agreement(agreementId)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Agreement cannot be terminated from {agreement['status']}")
    agreement["status"] = "TERMINATED"
    db.touch(agreement)
    # If this was the issuer's last ACTIVE agreement, issuer -> SUSPENDED
    # (firing the issuer-suspension token cascade)
    still_active = any(
        a["issuer_id"] == agreement["issuer_id"] and a["status"] == "ACTIVE"
        for a in db.issuer_agreements.values()
    )
    if not still_active:
        issuer = db.issuers.get(agreement["issuer_id"])
        if issuer is not None and issuer["status"] == "ACTIVE":
            issuer["status"] = "SUSPENDED"
            db.touch(issuer)
            suspend_issuer_cascade(issuer)
    return success_object(agreement, 200)

"""FranchiseAgreement endpoints (PRD 3.7, 2.7, 2.8).

POST /franchise/agreements, GET /franchise/agreements[/{id}]
POST /franchise/agreements/{id}/offer|activate|renew|activate-renewal|suspend|reinstate|expire
"""
from flask import Blueprint

import cascades
import derived
from auth import guard
from config import AGREEMENT_LIVE, CERTIFICATION_LEVELS, RENEWAL_WINDOW_DAYS
from errors import ApiError
from fetch import get_agreement, get_franchisee, get_territory, paged, synthesize_assignment
from response import created, ok
from store import common_fields, db, days_from, now_dt, parse_instant, touch
from validate import (
    body,
    opt_rate,
    opt_str,
    reject_unknown,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("agreements", __name__)

CREATE_INPUT = [
    "agreement_number", "franchisee_id", "brand_id", "territory_id",
    "signed_on", "initial_term_months", "certification_level", "royalty_rate_override",
]


def _started_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    if agreement.get("lifecycle_status") in ("TERMINATED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return agreement


def _require_status(agreement, allowed):
    if agreement.get("lifecycle_status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _expiry_window_open(agreement):
    """renew requires expires_on strictly before (clock + 90 days)."""
    expires = parse_instant(agreement.get("expires_on") or "")
    if expires is None:
        return False
    return expires < days_from(now_dt(), RENEWAL_WINDOW_DAYS)


@bp.post("/franchise/agreements")
def create_agreement():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    agreement_number = req_str(b, "agreement_number")
    if any(a.get("agreement_number") == agreement_number for a in db.agreements.values()):
        raise ApiError("ERR_DUPLICATE_AGREEMENT_NUMBER")
    franchisee_id = req_id(b, "franchisee_id")
    brand_id = req_id(b, "brand_id")
    territory_id = req_id(b, "territory_id")
    signed_on = req_str(b, "signed_on")
    if parse_instant(signed_on) is None:
        raise ApiError("ERR_INVALID_REQUEST", "signed_on must be an ISO 8601 UTC instant.")
    term = req_int(b, "initial_term_months", minimum=12)
    certification = req_enum(b, "certification_level", CERTIFICATION_LEVELS)
    override = opt_rate(b, "royalty_rate_override")

    # Body foreign keys resolve in the order the input list declares them.
    if db.franchisees.get(franchisee_id) is None:
        raise ApiError("ERR_FRANCHISEE_NOT_FOUND")
    if db.brands.get(brand_id) is None:
        raise ApiError("ERR_BRAND_NOT_FOUND")
    if db.territories.get(territory_id) is None:
        raise ApiError("ERR_TERRITORY_NOT_FOUND")

    record = common_fields()
    record.update({
        "_kind": "FranchiseAgreement",
        "agreement_number": agreement_number,
        "franchisee_id": franchisee_id,
        "brand_id": brand_id,
        "territory_id": territory_id,
        "signed_on": signed_on,
        "initial_term_months": term,
        "certification_level": certification,
        "royalty_rate_override": (None if override is None else str(override)),
        "lifecycle_status": "DRAFT",
        "standards_status": "COMPLIANT",
        "cumulative_royalty_cents": 0,
        "cumulative_referral_net_cents": 0,
        "open_remediation_count": 0,
        "audit_due_iso": None,
        "renewal_clock_iso": None,
    })
    derived.refresh_agreement(record)
    db.agreements[record["id"]] = record
    return created(record)


@bp.get("/franchise/agreements/<agreement_id>")
def read_agreement(agreement_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    agreement = get_agreement(agreement_id)
    derived.refresh_agreement(agreement)
    return ok(agreement)


@bp.get("/franchise/agreements")
def list_agreements():
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    records = list(db.agreements.values())
    for agreement in records:
        derived.refresh_agreement(agreement)
    return paged(
        db.agreements,
        "brand_id", "franchisee_id", "territory_id", "lifecycle_status", "standards_status",
        rows=records,
    )


@bp.post("/franchise/agreements/<agreement_id>/offer")
def offer_agreement(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["DRAFT"])
    signed = parse_instant(agreement.get("signed_on") or "")
    expires = parse_instant(agreement.get("expires_on") or "")
    if signed is None or expires is None or not expires > signed:
        raise ApiError("ERR_INVALID_STATE")
    agreement["lifecycle_status"] = "OFFERED"
    touch(agreement)
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["OFFERED"])

    territory = db.territories.get(agreement.get("territory_id"))
    if territory is None or territory.get("status") != "AWARDED":
        raise ApiError("ERR_AGREEMENT_TERRITORY_NOT_AWARDED")
    for other in db.agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other.get("territory_id") != agreement.get("territory_id"):
            continue
        if other.get("lifecycle_status") in AGREEMENT_LIVE:
            raise ApiError("ERR_TERRITORY_ALREADY_AGREED")

    agreement["lifecycle_status"] = "ACTIVE"
    touch(agreement)
    cascades.activate_agreement_territory(agreement)
    franchisee = db.franchisees.get(agreement.get("franchisee_id"))
    if franchisee is not None and franchisee.get("status") == "PROSPECT":
        franchisee["status"] = "ACTIVE"
    cascades.recompute_franchisee(franchisee)
    synthesize_assignment(territory["id"], agreement.get("franchisee_id"),
                          agreement["id"], "INITIAL_AWARD")
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/renew")
def renew_agreement(agreement_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    if role == "FranchiseeOperator" and uid != agreement.get("franchisee_id"):
        raise ApiError("ERR_UNAUTHORIZED")
    _require_status(agreement, ["ACTIVE"])
    if not _expiry_window_open(agreement):
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED")
    derived.refresh_agreement(agreement)
    if agreement.get("standards_status") == "DEFAULT":
        raise ApiError("ERR_STANDARDS_DEFAULTED")
    agreement["lifecycle_status"] = "RENEWAL_PENDING"
    agreement["renewal_clock_iso"] = derived.now_iso()
    touch(agreement)
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/activate-renewal")
def activate_renewal(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["RENEWAL_PENDING"])
    derived.refresh_agreement(agreement)
    if int(agreement.get("open_remediation_count") or 0) != 0:
        raise ApiError("ERR_OPEN_REMEDIATION")
    if agreement.get("standards_status") == "DEFAULT":
        raise ApiError("ERR_STANDARDS_DEFAULTED")
    agreement["lifecycle_status"] = "ACTIVE"
    agreement["renewal_clock_iso"] = None
    touch(agreement)
    synthesize_assignment(agreement.get("territory_id"), agreement.get("franchisee_id"),
                          agreement["id"], "INITIAL_AWARD")
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["reason"])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["ACTIVE"])
    agreement["lifecycle_status"] = "SUSPENDED"
    touch(agreement)
    cascades.stand_down_agreement_territory(agreement)
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/reinstate")
def reinstate_agreement(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["SUSPENDED"])
    territory = db.territories.get(agreement.get("territory_id"))
    if territory is None or territory.get("status") != "PENDING_REALLOCATION":
        raise ApiError("ERR_INVALID_STATE")
    agreement["lifecycle_status"] = "ACTIVE"
    touch(agreement)
    cascades.reinstate_agreement_territory(agreement)
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))
    return ok(agreement)


@bp.post("/franchise/agreements/<agreement_id>/expire")
def expire_agreement(agreement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    agreement = _started_agreement(agreement_id)
    _require_status(agreement, ["ACTIVE", "RENEWAL_PENDING"])
    expires = parse_instant(agreement.get("expires_on") or "")
    if expires is None or now_dt() < expires:
        raise ApiError("ERR_AGREEMENT_NOT_EXPIRABLE")
    agreement["lifecycle_status"] = "EXPIRED"
    touch(agreement)
    cascades.expire_agreement_cascade(agreement)
    return ok(agreement)
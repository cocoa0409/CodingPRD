"""Third-party administrator claims (PRD 3.8)."""
from flask import Blueprint, request

from clock import CLOCK
from db import db, new_entity, sorted_items
from errors import (
    raise_error,
    ERR_ALREADY_TERMINAL,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_TIER_INELIGIBLE,
    ERR_DUPLICATE_CLAIM,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_MISMATCH,
    ERR_SERVICE_REQUEST_NOT_FOUND,
)
from middleware import get_caller, require_role
from response import success_list, success_object
from services.reserve import post_entry, reserve_for_home, touch
from util import serialize
from validate import (
    apply_page,
    get_body,
    opt_nullable_str,
    pagination_params,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("claims", __name__)

DECIDE_OUTCOMES = {"ACCEPT", "DENY"}
CLAIM_TERMINAL = {"PAID", "DENIED"}
READ_ROLES = {"WarrantyManager", "WarrantyRep", "WarrantyAdministrator", "FinanceAdmin"}


def _get_claim_or_404(rid):
    claim = db["administrator_claims"].get(rid)
    if claim is None:
        raise_error(ERR_CLAIM_NOT_FOUND, f"administrator claim id does not resolve: {rid}")
    return claim


@bp.post("/administrator-claims")
def create_claim():
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    body = get_body()
    # Identifier resolution (precedence 4).
    sr_ref = body.get("service_request_id")
    sr = db["service_requests"].get(sr_ref) if isinstance(sr_ref, str) else None
    if isinstance(sr_ref, str) and sr_ref.strip() != "" and sr is None:
        raise_error(ERR_SERVICE_REQUEST_NOT_FOUND,
                    f"service request id does not resolve: {sr_ref}")
    req_str(body, "service_request_id")
    claimed_amount_cents = req_int(body, "claimed_amount_cents", positive=True)
    external_reference = opt_nullable_str(body, "external_reference")
    # Three gates, in order: uniqueness, program eligibility, tier eligibility.
    for existing in db["administrator_claims"].values():
        if existing["service_request_id"] == sr["id"]:
            raise_error(ERR_DUPLICATE_CLAIM,
                        "an administrator claim already exists for this service request")
    home = db["homes"].get(sr["home_id"])
    if home is None or home["warranty_program"] != "THIRD_PARTY_ADMINISTERED":
        raise_error(ERR_PROGRAM_MISMATCH,
                    "the home's warranty_program is not THIRD_PARTY_ADMINISTERED")
    if sr["status"] != "APPROVED" or sr["determined_tier"] != "STRUCTURAL":
        raise_error(ERR_CLAIM_TIER_INELIGIBLE,
                    "the request must be APPROVED with determined_tier STRUCTURAL")

    claim = new_entity()
    claim.update({
        "service_request_id": sr["id"],
        "home_id": sr["home_id"],  # denormalized at filing
        "claimed_amount_cents": claimed_amount_cents,
        "external_reference": external_reference,
        "status": "SUBMITTED",
        "approved_amount_cents": None,
        "denial_reason": None,
        "decided_at": None,
    })
    db["administrator_claims"][claim["id"]] = claim
    return success_object(serialize(claim), 201)


@bp.get("/administrator-claims/<rid>")
def fetch_claim(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    return success_object(serialize(_get_claim_or_404(rid)))


@bp.get("/administrator-claims")
def list_claims():
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    service_request_id = request.args.get("service_request_id")
    home_id = request.args.get("home_id")
    status = request.args.get("status")
    items = sorted_items("administrator_claims")
    if service_request_id is not None:
        items = [c for c in items if c["service_request_id"] == service_request_id]
    if home_id is not None:
        items = [c for c in items if c["home_id"] == home_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(c) for c in page], total, limit, offset)


@bp.post("/administrator-claims/<rid>/decide")
def decide_claim(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyAdministrator"})
    claim = _get_claim_or_404(rid)
    body = get_body()
    outcome = req_enum(body, "outcome", DECIDE_OUTCOMES)
    approved_amount_cents = None
    denial_reason = None
    if outcome == "ACCEPT":
        # An acceptance without a conforming amount fails request validation.
        approved_amount_cents = req_int(body, "approved_amount_cents")
        if approved_amount_cents <= 0 or approved_amount_cents > claim["claimed_amount_cents"]:
            raise_error(ERR_INVALID_REQUEST,
                        "approved_amount_cents must be positive and no more than the "
                        "claimed amount")
    else:
        denial_reason = req_str(body, "denial_reason")
    if claim["status"] in CLAIM_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"administrator claim is {claim['status']}")

    now = CLOCK.now()
    claim["decided_at"] = now
    if outcome == "ACCEPT":
        claim["status"] = "PAID"
        claim["approved_amount_cents"] = approved_amount_cents
        # The accepted claim credits the home's reserve with a RECOVERY entry.
        reserve = reserve_for_home(claim["home_id"])
        if reserve is not None:
            post_entry(reserve, "RECOVERY", approved_amount_cents, claim_ref=claim["id"])
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
    touch(claim)
    return success_object(serialize(claim))

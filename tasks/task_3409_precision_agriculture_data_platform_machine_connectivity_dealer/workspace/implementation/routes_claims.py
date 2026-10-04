"""Warranty claims and dealer settlement (PRD section 3.8)."""

from flask import Blueprint, request

from auth import (
    as_enum,
    as_int,
    as_pos_int,
    as_str,
    body_json,
    caller,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from constants import WARRANTY_MIN_COVERAGE_PCT
from db import STORES, now
from domain import (
    compute_payout,
    compute_uptime,
    new_record,
    serialize,
    touch,
)
from envelope import created, ok, ok_list
from errors import (
    ERR_DEALER_SUSPENDED,
    ERR_INSUFFICIENT_DATA_COVERAGE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ApiError,
    invalid_state,
)

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = {"DealerTechnician", "GrowerManager", "PlatformAdmin"}


@bp.post("/warranty-claims")
def create_claim():
    uid, role = caller()
    require_role(role, {"DealerTechnician"})
    b = body_json()
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    claim_amount_cents = as_pos_int(need(b, "claim_amount_cents"), "claim_amount_cents")
    parts_amount_cents = as_int(need(b, "parts_amount_cents"), "parts_amount_cents")
    description = as_str(need(b, "description"), "description")
    if parts_amount_cents < 0 or parts_amount_cents > claim_amount_cents:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "parts_amount_cents must be non-negative and no greater than claim_amount_cents",
        )
    machine = get_or_404("machines", machine_id, "machine")
    dealer = STORES["dealers"].get(uid)
    if dealer is None:
        raise ApiError(ERR_NOT_FOUND, 404, "caller dealer not found")
    # State gates in the PRD's listed order: machine IN_SERVICE, dealer ACTIVE
    if machine["lifecycle_status"] != "IN_SERVICE":
        raise invalid_state("machine is not IN_SERVICE")
    if dealer["status"] != "ACTIVE":
        raise ApiError(ERR_DEALER_SUSPENDED, 409, "dealer is SUSPENDED")
    rec = new_record(
        {
            "machine_id": machine_id,
            "organization_id": machine["organization_id"],
            "dealer_id": uid,
            "claim_amount_cents": claim_amount_cents,
            "parts_amount_cents": parts_amount_cents,
            "description": description,
            "status": "DRAFT",
            "coverage_pct_applied": None,
            "payout_cents": None,
            "decided_at": None,
            "settled_at": None,
        }
    )
    STORES["warranty_claims"][rec["id"]] = rec
    return created(serialize(rec))


def _claim_visible(c, role, uid):
    if role == "PlatformAdmin":
        return True
    if role == "GrowerManager":
        return uid == c["organization_id"]
    return c["dealer_id"] == uid  # DealerTechnician


@bp.get("/warranty-claims/<cid>")
def get_claim(cid):
    uid, role = caller()
    require_role(role, CLAIM_READ_ROLES)
    c = get_or_404("warranty_claims", cid, "warranty claim")
    if not _claim_visible(c, role, uid):
        raise access_denied("caller may not read this claim")
    return ok(serialize(c))


@bp.get("/warranty-claims")
def list_claims():
    uid, role = caller()
    require_role(role, CLAIM_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("machine_id", "dealer_id", "organization_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "GrowerManager" and org_filter is not None and org_filter != uid:
        raise access_denied("grower may list only its own organization")
    visible = lambda r: _claim_visible(r, role, uid)
    page, total, limit, offset = list_resources("warranty_claims", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/warranty-claims/<cid>/submit")
def submit_claim(cid):
    uid, role = caller()
    require_role(role, {"DealerTechnician"})
    c = get_or_404("warranty_claims", cid, "warranty claim")
    if c["dealer_id"] != uid:
        raise access_denied("claim belongs to another dealer")
    if c["status"] != "DRAFT":
        raise invalid_state("claim is not DRAFT")
    # Coverage gate: the conservative uptime score must reach the minimum;
    # exactly WARRANTY_MIN_COVERAGE_PCT passes
    conservative, _, _, _ = compute_uptime(c["machine_id"])
    if conservative < WARRANTY_MIN_COVERAGE_PCT:
        raise ApiError(
            ERR_INSUFFICIENT_DATA_COVERAGE, 409, "machine data coverage is insufficient"
        )
    c["status"] = "SUBMITTED"
    touch(c)
    dealer = STORES["dealers"].get(c["dealer_id"])
    if dealer is not None:
        dealer["warranty_reserve_cents"] += c["claim_amount_cents"]
        touch(dealer)
    return ok(serialize(c))


@bp.post("/warranty-claims/<cid>/decide")
def decide_claim(cid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    decision = as_enum(need(b, "decision"), "decision", {"APPROVE", "DENY"})
    c = get_or_404("warranty_claims", cid, "warranty claim")
    if c["status"] != "SUBMITTED":
        raise invalid_state("claim is not SUBMITTED")
    dealer = STORES["dealers"].get(c["dealer_id"])
    if decision == "APPROVE":
        machine = STORES["machines"].get(c["machine_id"])
        pct, payout = compute_payout(c, machine, dealer)
        c["coverage_pct_applied"] = pct
        c["payout_cents"] = payout
        c["status"] = "APPROVED"
    else:
        c["status"] = "DENIED"
        if dealer is not None:
            # Releases the reserve, exactly compensating the submit-time hold
            dealer["warranty_reserve_cents"] -= c["claim_amount_cents"]
            touch(dealer)
    c["decided_at"] = now()
    touch(c)
    return ok(serialize(c))


@bp.post("/warranty-claims/<cid>/settle")
def settle_claim(cid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    c = get_or_404("warranty_claims", cid, "warranty claim")
    if c["status"] != "APPROVED":
        raise invalid_state("claim is not APPROVED")
    dealer = STORES["dealers"].get(c["dealer_id"])
    if dealer is not None:
        dealer["warranty_reserve_cents"] -= c["claim_amount_cents"]
        dealer["warranty_paid_cents"] += c["payout_cents"]
        touch(dealer)
    c["status"] = "SETTLED"
    c["settled_at"] = now()
    touch(c)
    return ok(serialize(c))

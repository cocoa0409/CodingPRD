"""Warranty claim endpoints."""
from flask import Blueprint, request

import calc
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, now_logical, ok, paginate,
                  parse_dt, sort_by_created, new_common)
from routes.shops import require_roles
from routes.repairs import get_order_or_404

bp = Blueprint("warranty", __name__)

ROLES_READ_CLAIMS = {"NetworkAdmin", "NetworkAuditor", "ShopManager", "InsurerRep"}
ROLES_READ_ONE = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
DEFECT_CATEGORIES = {"WORKMANSHIP", "PART_DEFECT", "CORROSION", "PAINT_ADHESION",
                     "CALIBRATION_DRIFT"}


def get_claim_or_404(claim_id):
    claim = db.warranty_claims.get(claim_id)
    if not claim:
        raise ApiError("ERR_NOT_FOUND", 404, "Warranty claim not found")
    return claim


@bp.post("/network/repair-orders/<order_id>/warranty-claims")
def file_claim(order_id):
    require_roles("ShopManager", "NetworkAdmin")
    order = get_order_or_404(order_id)
    if request.headers.get("X-User-Role") == "ShopManager" \
            and request.headers.get("X-User-ID") != order["shop_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only file claims for their own shop")
    body = get_json()
    claimant = body.get("claimant_contact")
    defect = body.get("defect_category")
    amount = body.get("claim_amount_cents")
    now = now_logical()
    in_window = bool(order.get("completed_at")) and now <= calc.add_months(
        parse_dt(order["completed_at"], "completed_at"), calc.WARRANTY_MONTHS)
    if order["status"] != "WARRANTY_ACTIVE" or not in_window:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422,
                       "Order is not in WARRANTY_ACTIVE within the warranty window")
    if not isinstance(claimant, str) or not claimant:
        raise ApiError("ERR_INVALID_REQUEST", 400, "claimant_contact is required")
    if defect not in DEFECT_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"defect_category must be one of {sorted(DEFECT_CATEGORIES)}")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "claim_amount_cents must be an integer >= 0")
    claim = new_common()
    claim.update({
        "repair_order_id": order["id"],
        "claimant_contact": claimant,
        "defect_category": defect,
        "claim_amount_cents": amount,
        "filed_at": iso_ms(now),
        "status": "FILED",
        "filed_by_role": request.headers.get("X-User-Role"),
        "reviewed_by_user_id": None,
        "_filed_by_user_id": request.headers.get("X-User-ID"),
        "_resolved_at": None,
    })
    db.warranty_claims[claim["id"]] = claim
    return ok(serialize(claim), 201)


@bp.get("/network/repair-orders/<order_id>/warranty-claims")
def list_order_claims(order_id):
    require_roles(*ROLES_READ_CLAIMS)
    get_order_or_404(order_id)
    status = request.args.get("status")
    items = [c for c in db.warranty_claims.values()
             if c["repair_order_id"] == order_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(c) for c in page], 200, meta)


@bp.get("/network/warranty-claims/<claim_id>")
def get_claim(claim_id):
    require_roles(*ROLES_READ_ONE)
    return ok(serialize(get_claim_or_404(claim_id)))


def _check_not_filer(claim):
    if request.headers.get("X-User-ID") == claim.get("_filed_by_user_id"):
        raise ApiError("ERR_SELF_VERIFICATION", 422,
                       "The reviewer may not be the claim filer")


@bp.post("/network/warranty-claims/<claim_id>/review")
def review_claim(claim_id):
    require_roles("NetworkAdmin")
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not FILED")
    _check_not_filer(claim)
    claim["status"] = "UNDER_REVIEW"
    claim["reviewed_by_user_id"] = request.headers.get("X-User-ID")
    bump(claim)
    return ok(serialize(claim))


@bp.post("/network/warranty-claims/<claim_id>/escalate")
def escalate_claim(claim_id):
    require_roles("NetworkAdmin")
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW")
    if not (claim["defect_category"] == "PART_DEFECT"
            or claim["claim_amount_cents"] > calc.ESCALATION_THRESHOLD_CENTS):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Escalation requires a part defect or an over-threshold amount")
    claim["status"] = "ESCALATED"
    bump(claim)
    return ok(serialize(claim))


@bp.post("/network/warranty-claims/<claim_id>/resolve")
def resolve_claim(claim_id):
    require_roles("NetworkAdmin")
    claim = get_claim_or_404(claim_id)
    if claim["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Claim must be UNDER_REVIEW or ESCALATED to resolve")
    body = get_json()
    verdict = body.get("verdict")
    _check_not_filer(claim)
    must_escalate = (claim["defect_category"] == "PART_DEFECT"
                     or claim["claim_amount_cents"] > calc.ESCALATION_THRESHOLD_CENTS)
    if claim["status"] == "UNDER_REVIEW" and must_escalate:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Claim must be ESCALATED before resolution")
    if verdict not in ("ACCEPTED", "DENIED"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "verdict must be ACCEPTED or DENIED")
    order = db.repair_orders.get(claim["repair_order_id"])
    shop = db.shops.get(order["shop_id"]) if order else None
    if verdict == "ACCEPTED":
        remaining = order.get("_reserve_remaining", 0) if order else 0
        if claim["claim_amount_cents"] > remaining:
            raise ApiError("ERR_RESERVE_FLOOR", 422,
                           "Acceptance exceeds the order's remaining accrual")
        if shop and claim["claim_amount_cents"] > shop.get("warranty_reserve_cents", 0):
            raise ApiError("ERR_RESERVE_FLOOR", 422,
                           "Acceptance would drive the shop reserve below zero")
        claim["status"] = "RESOLVED_ACCEPTED"
        claim["_resolved_at"] = now_logical()
        bump(claim)
        if order:
            order["_reserve_remaining"] = remaining - claim["claim_amount_cents"]
            bump(order)
        if shop:
            shop["warranty_reserve_cents"] = shop["warranty_reserve_cents"] - claim["claim_amount_cents"]
            bump(shop)
    else:
        claim["status"] = "RESOLVED_DENIED"
        claim["_resolved_at"] = now_logical()
        bump(claim)
    return ok(serialize(claim))

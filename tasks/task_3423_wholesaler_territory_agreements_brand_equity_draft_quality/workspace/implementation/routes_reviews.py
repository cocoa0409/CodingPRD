"""Quarterly performance reviews and the corrective-plan loop (§3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import clock
import db
from auth import (ALL_ROLES, ROLE_BREWER_ADMIN, ROLE_BREWER_COMPLIANCE,
                  ROLE_WHOLESALER_PRINCIPAL, require_roles)
from db import touch
from envelope import created, ok, paginate
from errors import (ApiError, ERR_DUPLICATE_REVIEW, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_REVIEW_NOT_ACKNOWLEDGED,
                    ERR_WHOLESALER_NOT_ELIGIBLE)
from validate import field, get_body, validate_body

bp = Blueprint("reviews", __name__)

QUARTERS = ("Q1", "Q2", "Q3", "Q4")


def _pooled_freshness_index(wholesaler_id, period_year, period_quarter):
    """Volume-weighted freshness across the wholesaler's account audits whose
    conducted_at falls inside the quarter window, inclusive of both ends."""
    start, end = calc.quarter_window(period_year, period_quarter)
    total_bbl = Decimal("0")
    stale_bbl = Decimal("0")
    for audit in db.audits.values():
        account = db.accounts.get(audit["account_id"])
        if account is None or account["serving_wholesaler_id"] != wholesaler_id:
            continue
        conducted_at = clock.parse_iso(audit["conducted_at"])
        if conducted_at < start or conducted_at > end:
            continue
        for keg in audit["kegs"]:
            volume = calc.dec(keg["volume_bbl"])
            total_bbl += volume
            age_days = calc.whole_days(clock.parse_iso(keg["filled_at"]),
                                       conducted_at)
            if age_days >= calc.STALE_AGE_DAYS:
                stale_bbl += volume
    if total_bbl == 0:
        return Decimal("100.00")
    return calc.round2(Decimal("100") - Decimal("100") * stale_bbl / total_bbl)


def _spawn_corrective_plan(review, agreement):
    plan = db.stamped()
    plan.update({
        "review_id": review["id"],
        "status": "PROPOSED",
        "revision_count": 0,
        "resolution_notes": None,
        "target_snapshot": {
            "distribution_target_pct": agreement["distribution_target_pct"],
            "freshness_target_index": agreement["freshness_target_index"],
            "share_target_pct": agreement["share_target_pct"],
        },
    })
    db.plans[plan["id"]] = plan
    return plan


@bp.route("/performance-reviews", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_review(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "wholesaler_id": field("string", required=True),
        "period_year": field("integer", required=True),
        "period_quarter": field("enum", required=True, enum=QUARTERS),
        "distribution_pct": field("number", required=True),
        "share_pct": field("number", required=True),
    })
    wholesaler = db.wholesalers.get(data["wholesaler_id"])
    if wholesaler is None:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    if wholesaler["status"] not in ("APPOINTED", "SUSPENDED"):
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Wholesaler must be APPOINTED or SUSPENDED to be reviewed",
                       409)
    for existing in db.reviews.values():
        if (existing["wholesaler_id"] == wholesaler["id"]
                and existing["period_year"] == data["period_year"]
                and existing["period_quarter"] == data["period_quarter"]):
            raise ApiError(ERR_DUPLICATE_REVIEW,
                           "A review already exists for this wholesaler and period",
                           409)
    active_agreements = db.active_agreements_of(wholesaler["id"])
    agreement = active_agreements[0] if active_agreements else None
    profile = agreement["weighting_profile"] if agreement else "STANDARD"
    freshness = _pooled_freshness_index(wholesaler["id"], data["period_year"],
                                        data["period_quarter"])
    composite = calc.composite_score(data["distribution_pct"], freshness,
                                     data["share_pct"], profile)
    review = db.stamped()
    review.update({
        "wholesaler_id": wholesaler["id"],
        "period_year": data["period_year"],
        "period_quarter": data["period_quarter"],
        "distribution_pct": data["distribution_pct"],
        "share_pct": data["share_pct"],
        "freshness_index": float(freshness),
        "weighting_profile_snapshot": profile,
        "composite_score": float(composite),
        "status": "PUBLISHED",
        "dispute_reason": None,
    })
    db.reviews[review["id"]] = review
    if composite < calc.CORRECTIVE_FLOOR and agreement is not None:
        _spawn_corrective_plan(review, agreement)
    return created(review)


@bp.route("/performance-reviews/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_review(rid, user_id, caller_role):
    review = db.reviews.get(rid)
    if review is None:
        raise ApiError(ERR_NOT_FOUND, "Performance review not found", 404)
    return ok(review)


@bp.route("/performance-reviews/<rid>/response", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def review_response(rid, user_id, caller_role):
    review = db.reviews.get(rid)
    if review is None:
        raise ApiError(ERR_NOT_FOUND, "Performance review not found", 404)
    if review["wholesaler_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER,
                       "Only the reviewed wholesaler may respond", 403)
    data, _ = validate_body(get_body(), {
        "action": field("enum", required=True, enum=("ACKNOWLEDGE", "DISPUTE")),
        "dispute_reason": field("string", nullable=True),
    })
    if (data["action"] == "DISPUTE"
            and (data["dispute_reason"] is None or data["dispute_reason"] == "")):
        raise ApiError(ERR_INVALID_REQUEST,
                       "dispute_reason is required when action is DISPUTE", 400)
    if review["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Review response requires PUBLISHED status", 409)
    if data["action"] == "ACKNOWLEDGE":
        review["status"] = "ACKNOWLEDGED"
    else:
        review["status"] = "DISPUTED"
        review["dispute_reason"] = data["dispute_reason"]
    touch(review)
    return ok(review)


@bp.route("/performance-reviews/<rid>/corrective-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_review_plans(rid, user_id, caller_role):
    if rid not in db.reviews:
        raise ApiError(ERR_NOT_FOUND, "Performance review not found", 404)
    rows = [p for p in db.plans.values() if p["review_id"] == rid]
    return paginate(rows, status_filter=request.args.get("status"))


@bp.route("/corrective-plans/<pid>/activate", methods=["POST"])
@require_roles(ROLE_BREWER_COMPLIANCE)
def activate_plan(pid, user_id, caller_role):
    plan = db.plans.get(pid)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "Corrective plan not found", 404)
    if plan["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Activation requires PROPOSED status", 409)
    review = db.reviews.get(plan["review_id"])
    if review is None:
        raise ApiError(ERR_NOT_FOUND, "Performance review not found", 404)
    if review["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_REVIEW_NOT_ACKNOWLEDGED,
                       "The parent review is not ACKNOWLEDGED", 409)
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok(plan)


@bp.route("/corrective-plans/<pid>/resolve", methods=["POST"])
@require_roles(ROLE_BREWER_COMPLIANCE)
def resolve_plan(pid, user_id, caller_role):
    plan = db.plans.get(pid)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "Corrective plan not found", 404)
    data, _ = validate_body(get_body(), {
        "outcome": field("enum", required=True, enum=("VERIFIED", "FAILED")),
        "resolution_notes": field("string", nullable=True),
    })
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Resolution requires ACTIVE status", 409)
    plan["status"] = data["outcome"]
    plan["resolution_notes"] = data["resolution_notes"]
    touch(plan)
    if data["outcome"] == "VERIFIED":
        review = db.reviews.get(plan["review_id"])
        wholesaler = (db.wholesalers.get(review["wholesaler_id"])
                      if review is not None else None)
        if wholesaler is not None and wholesaler["status"] == "SUSPENDED":
            wholesaler["status"] = "APPOINTED"
            touch(wholesaler)
    return ok(plan)


@bp.route("/corrective-plans/<pid>/revise", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def revise_plan(pid, user_id, caller_role):
    plan = db.plans.get(pid)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "Corrective plan not found", 404)
    review = db.reviews.get(plan["review_id"])
    if review is None:
        raise ApiError(ERR_NOT_FOUND, "Performance review not found", 404)
    if review["wholesaler_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER,
                       "Only the reviewed wholesaler may revise the plan", 403)
    if plan["status"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Revision requires FAILED status", 409)
    plan["status"] = "PROPOSED"
    plan["revision_count"] += 1
    touch(plan)
    return ok(plan)

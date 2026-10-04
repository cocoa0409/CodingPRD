"""Transfer applications: submission, qualification review, ROFR, decision,
and the consummation cascade (§3.3, §3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import clock
import db
from auth import (ROLE_BREWER_ADMIN, ROLE_BREWER_COMPLIANCE,
                  ROLE_WHOLESALER_PRINCIPAL, require_roles)
from db import touch
from envelope import created, ok
from errors import (ApiError, ERR_AGREEMENT_NOT_ACTIVE,
                    ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_ROFR_WINDOW_OPEN,
                    ERR_THREE_TIER_PROHIBITION, ERR_TRANSFER_ALREADY_PENDING,
                    ERR_WHOLESALER_NOT_ELIGIBLE)
from validate import field, get_body, validate_body

bp = Blueprint("transfers", __name__)

PENDING_STATUSES = ("SUBMITTED", "QUALIFIED", "ROFR_OPEN", "ROFR_EXERCISED",
                    "ROFR_WAIVED", "ROFR_LAPSED", "APPROVED")
DECIDABLE_STATUSES = ("QUALIFIED", "ROFR_WAIVED", "ROFR_LAPSED", "ROFR_EXERCISED")
ROFR_WINDOW_DAYS = 30
CONSUMMATION_WINDOW_DAYS = 60


@bp.route("/transfer-applications", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def create_transfer(user_id, caller_role):
    body = get_body()
    # Ownership (tier 3): the caller must be the seller named on the agreement.
    # The governing agreement must resolve before that check can run.
    agreement_id = body.get("agreement_id")
    agreement = db.agreements.get(agreement_id) if isinstance(agreement_id, str) else None
    if agreement is not None and agreement["wholesaler_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER,
                       "Only the selling wholesaler may initiate a transfer", 403)
    data, _ = validate_body(body, {
        "agreement_id": field("string", required=True),
        "buyer_wholesaler_id": field("string", required=True),
        "purchase_price_cents": field("integer", required=True),
    })
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    buyer = db.wholesalers.get(data["buyer_wholesaler_id"])
    if buyer is None:
        raise ApiError(ERR_NOT_FOUND, "Buyer wholesaler not found", 404)
    if agreement["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE", 409)
    seller = db.wholesalers.get(agreement["wholesaler_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "A SUSPENDED wholesaler may not initiate a transfer", 409)
    if buyer["status"] != "APPLICANT":
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Buyer wholesaler must be an APPLICANT", 409)
    if buyer["holds_retail_interest"]:
        raise ApiError(ERR_THREE_TIER_PROHIBITION,
                       "Buyer holds a retail-tier ownership interest", 422)
    for other in db.transfers.values():
        if (other["agreement_id"] == agreement["id"]
                and other["status"] in PENDING_STATUSES):
            raise ApiError(ERR_TRANSFER_ALREADY_PENDING,
                           "Another transfer application is pending for this "
                           "agreement", 409)
    transfer = db.stamped()
    transfer.update({
        "agreement_id": agreement["id"],
        "seller_wholesaler_id": agreement["wholesaler_id"],
        "buyer_wholesaler_id": buyer["id"],
        "purchase_price_cents": data["purchase_price_cents"],
        "status": "SUBMITTED",
        "qualification_score": None,
        "rofr_deadline": None,
        "successor_wholesaler_id": None,
        "consummation_deadline": None,
        "decision_reason": None,
    })
    db.transfers[transfer["id"]] = transfer
    return created(transfer)


@bp.route("/transfer-applications/<tid>/qualification-review", methods=["POST"])
@require_roles(ROLE_BREWER_COMPLIANCE)
def qualification_review(tid, user_id, caller_role):
    transfer = db.transfers.get(tid)
    if transfer is None:
        raise ApiError(ERR_NOT_FOUND, "Transfer application not found", 404)
    if transfer["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Qualification review requires SUBMITTED status", 409)
    buyer = db.wholesalers.get(transfer["buyer_wholesaler_id"])
    if buyer is None:
        raise ApiError(ERR_NOT_FOUND, "Buyer wholesaler not found", 404)
    score = calc.qualification_score(buyer["financial_capacity_score"],
                                     buyer["warehouse_capacity_score"],
                                     buyer["market_coverage_score"])
    transfer["qualification_score"] = float(score)
    if score >= calc.QUALIFY_THRESHOLD:
        agreement = db.agreements.get(transfer["agreement_id"])
        if agreement is not None and agreement["rofr_holder_wholesaler_id"]:
            transfer["status"] = "ROFR_OPEN"
            transfer["rofr_deadline"] = clock.format_iso(
                clock.now() + timedelta(days=ROFR_WINDOW_DAYS))
        else:
            transfer["status"] = "QUALIFIED"
    else:
        transfer["status"] = "REJECTED"
    touch(transfer)
    return ok(transfer)


@bp.route("/transfer-applications/<tid>/rofr-response", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def rofr_response(tid, user_id, caller_role):
    transfer = db.transfers.get(tid)
    if transfer is None:
        raise ApiError(ERR_NOT_FOUND, "Transfer application not found", 404)
    agreement = db.agreements.get(transfer["agreement_id"])
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    if agreement["rofr_holder_wholesaler_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER,
                       "Only the ROFR holder may respond to the window", 403)
    data, _ = validate_body(get_body(), {
        "decision": field("enum", required=True, enum=("EXERCISE", "WAIVE")),
    })
    if transfer["status"] != "ROFR_OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "ROFR response requires ROFR_OPEN status", 409)
    if (transfer["rofr_deadline"] is not None
            and clock.now() > clock.parse_iso(transfer["rofr_deadline"])):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "The ROFR deadline has passed", 409)
    transfer["status"] = ("ROFR_EXERCISED" if data["decision"] == "EXERCISE"
                          else "ROFR_WAIVED")
    touch(transfer)
    return ok(transfer)


@bp.route("/transfer-applications/<tid>/decision", methods=["POST"])
@require_roles(ROLE_BREWER_COMPLIANCE)
def transfer_decision(tid, user_id, caller_role):
    transfer = db.transfers.get(tid)
    if transfer is None:
        raise ApiError(ERR_NOT_FOUND, "Transfer application not found", 404)
    data, _ = validate_body(get_body(), {
        "decision": field("enum", required=True, enum=("APPROVE", "REJECT")),
        "reason": field("string", nullable=True),
    })
    if transfer["status"] == "ROFR_OPEN":
        raise ApiError(ERR_ROFR_WINDOW_OPEN,
                       "The right-of-first-refusal window is still unresolved", 409)
    if transfer["status"] not in DECIDABLE_STATUSES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "No decision transition exists from this state", 409)
    if data["decision"] == "APPROVE":
        agreement = db.agreements.get(transfer["agreement_id"])
        if (transfer["status"] == "ROFR_EXERCISED" and agreement is not None):
            transfer["successor_wholesaler_id"] = agreement["rofr_holder_wholesaler_id"]
        else:
            transfer["successor_wholesaler_id"] = transfer["buyer_wholesaler_id"]
        transfer["consummation_deadline"] = clock.format_iso(
            clock.now() + timedelta(days=CONSUMMATION_WINDOW_DAYS))
        transfer["status"] = "APPROVED"
    else:
        transfer["status"] = "REJECTED"
        transfer["decision_reason"] = data["reason"]
    touch(transfer)
    return ok(transfer)


@bp.route("/transfer-applications/<tid>/consummate", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def consummate_transfer(tid, user_id, caller_role):
    transfer = db.transfers.get(tid)
    if transfer is None:
        raise ApiError(ERR_NOT_FOUND, "Transfer application not found", 404)
    if transfer["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Consummation requires APPROVED status", 409)
    if (transfer["consummation_deadline"] is not None
            and clock.now() > clock.parse_iso(transfer["consummation_deadline"])):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "The consummation window has passed", 409)
    successor = db.wholesalers.get(transfer["successor_wholesaler_id"])
    if successor is None:
        raise ApiError(ERR_NOT_FOUND, "Successor wholesaler not found", 404)
    if successor["status"] == "TERMINATED":
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Successor wholesaler is TERMINATED", 409)
    agreement = db.agreements.get(transfer["agreement_id"])
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    territory = db.territories.get(agreement["territory_id"])
    agreement["status"] = "TERMINATED"
    touch(agreement)
    if territory is not None:
        territory["incumbent_wholesaler_id"] = successor["id"]
        touch(territory)
    new_agreement = db.stamped()
    new_agreement.update({
        "territory_id": agreement["territory_id"],
        "wholesaler_id": successor["id"],
        "rofr_holder_wholesaler_id": None,
        "brand_scope": list(agreement["brand_scope"]),
        "weighting_profile": agreement["weighting_profile"],
        "distribution_target_pct": agreement["distribution_target_pct"],
        "freshness_target_index": agreement["freshness_target_index"],
        "share_target_pct": agreement["share_target_pct"],
        "declared_distribution_pct": agreement["declared_distribution_pct"],
        "declared_freshness_index": agreement["declared_freshness_index"],
        "declared_share_pct": agreement["declared_share_pct"],
        "term_years": agreement["term_years"],
        "status": "ACTIVE",
        "amendment_log": [],
    })
    db.agreements[new_agreement["id"]] = new_agreement
    if successor["status"] == "APPLICANT":
        successor["status"] = "APPOINTED"
        touch(successor)
    seller = db.wholesalers.get(transfer["seller_wholesaler_id"])
    if seller is not None and seller["status"] == "APPOINTED":
        remaining = [a for a in db.agreements.values()
                     if a["wholesaler_id"] == seller["id"]
                     and a["status"] == "ACTIVE"]
        if not remaining:
            seller["status"] = "TERMINATED"
            touch(seller)
            cascades.release_pending_assignments(seller["id"])
    transfer["status"] = "CONSUMMATED"
    touch(transfer)
    return ok(transfer)

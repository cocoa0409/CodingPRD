"""Discontinuation reviews (PRD 3.9): proposed by a ProductManager against a
LAUNCHED product (optional LAUNCH_READY refresh successor), decided by a
RetailPlanner under segregation of duties. Approval fires the four-deep
cascade: product -> DISCONTINUED, slots -> VACATED, facing reconciliation,
EXECUTED launch plan -> RECONCILED.
"""
from flask import Blueprint

from core.auth import authenticate, require_role
from core.constants import ROLE_PRODUCT_MANAGER, ROLE_RETAIL_PLANNER
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, opt_str, req_enum, req_str
from services import cascade

bp = Blueprint("discontinuation", __name__)

STATUSES = ("PROPOSED", "APPROVED", "REJECTED")
REASONS = ("TREND_DECAY", "REFRESH_CADENCE", "PERFORMANCE")


@bp.post("/discontinuation-reviews")
def create_review():
    user_id, role = authenticate()
    require_role(role, ROLE_PRODUCT_MANAGER)
    body = get_body()
    product_id = req_str(body, "product_id")
    reason = req_enum(body, "reason", REASONS)
    successor_id = opt_str(body, "successor_product_id")
    product = store.products.get(product_id)
    if product is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    successor = None
    if successor_id is not None:
        successor = store.products.get(successor_id)
        if successor is None:
            raise not_found("ERR_PRODUCT_NOT_FOUND", "successor product not found")
    # Cross-entity state precondition (priority 7): the retired product must
    # be LAUNCHED.
    if product["status"] != "LAUNCHED":
        raise err(
            "ERR_INVALID_STATE", "only a LAUNCHED product can be discontinued"
        )
    if successor is not None and (
        successor["status"] != "LAUNCH_READY" or successor["id"] == product["id"]
    ):
        raise err(
            "ERR_SUCCESSOR_INVALID",
            "the successor must be a LAUNCH_READY product different from the "
            "retired one",
        )
    rec = new_record(
        {
            "product_id": product_id,
            "successor_product_id": successor_id,
            "reason": reason,
            "status": "PROPOSED",
            "proposed_by_user_id": user_id,
        }
    )
    store.discontinuation_reviews[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/discontinuation-reviews")
def list_reviews():
    authenticate()
    return list_response(
        store.discontinuation_reviews.values(),
        {
            "product_id": "product_id",
            "successor_product_id": "successor_product_id",
            "status": "status",
        },
        pub,
    )


@bp.get("/discontinuation-reviews/<rid>")
def get_review(rid):
    authenticate()
    rec = store.discontinuation_reviews.get(rid)
    if rec is None:
        raise not_found(
            "ERR_DISCONTINUATION_REVIEW_NOT_FOUND", "discontinuation review not found"
        )
    return success_object(pub(rec))


@bp.patch("/discontinuation-reviews/<rid>")
def patch_review(rid):
    user_id, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.discontinuation_reviews.get(rid)
    if rec is None:
        raise not_found(
            "ERR_DISCONTINUATION_REVIEW_NOT_FOUND", "discontinuation review not found"
        )
    if target is None:
        return success_object(pub(rec))
    if rec["status"] != "PROPOSED" or target not in ("APPROVED", "REJECTED"):
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a discontinuation review from %s to %s"
            % (rec["status"], target),
        )
    # Segregation of duties is deliberately last among business rules so state
    # and safety errors surface first.
    if user_id == rec["proposed_by_user_id"]:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the decider's X-User-ID must differ from the proposer's",
        )
    if target == "APPROVED":
        rec["status"] = "APPROVED"
        touch(rec)
        product = store.products.get(rec["product_id"])
        if product is not None and product["status"] == "LAUNCHED":
            cascade.discontinue_product(product, rec["successor_product_id"])
    else:
        rec["status"] = "REJECTED"
        touch(rec)
    return success_object(pub(rec))

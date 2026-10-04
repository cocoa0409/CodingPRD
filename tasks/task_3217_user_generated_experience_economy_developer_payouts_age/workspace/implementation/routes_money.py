"""Routes: moderation, appeals, currency orders, marketplace, resale, purchases, DevEx."""
from math import floor

from flask import Blueprint

import services as svc
from db import DB
from errors import (
    err,
    ERR_CREATOR_AGE_INSUFFICIENT_FOR_RATING,
    ERR_DEVEX_MINIMUM_NOT_MET,
    ERR_DEVEX_NOT_ELIGIBLE,
    ERR_DUPLICATE_IDEMPOTENCY_KEY,
    ERR_INSUFFICIENT_ROBUX,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_ITEM_NOT_ON_SALE,
    ERR_LIMITED_SUPPLY_EXHAUSTED,
    ERR_LISTING_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PARENTAL_SPEND_LIMIT,
    ERR_AGE_BAND_INSUFFICIENT,
    ERR_EXPERIENCE_NOT_PUBLISHED,
    ERR_REFUND_EXCEEDS_BALANCE,
    ERR_RESALE_FLOOR_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_SUBMISSION_NOT_FOUND,
    ERR_SUBMISSION_NOT_REJECTED,
    ERR_APPEAL_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
    ERR_USER_NOT_FOUND,
)
from middleware import auth_context, require_role
from response import success
from util import (
    audit,
    body,
    iso_ms,
    list_view,
    new_id,
    now_iso,
    opt_enum,
    opt_int,
    opt_str,
    paginate,
    req_int,
    req_str,
    stamp_new,
    touch,
)

bp = Blueprint("money", __name__)

ITEM_KINDS = ("HAT", "SHIRT", "PANTS", "GEAR", "LIMITED_HAT", "LIMITED_GEAR")
LIMITED_KINDS = ("LIMITED_HAT", "LIMITED_GEAR")
DESCRIPTOR_SEVERITY = {
    "GAMBLING_SIMULATED": "SEVENTEEN_PLUS",
    "ALCOHOL_REFERENCE": "THIRTEEN_PLUS",
    "VIOLENCE_MILD": "NINE_PLUS",
}
RATING_ORDER = {"ALL": 0, "NINE_PLUS": 1, "THIRTEEN_PLUS": 2, "SEVENTEEN_PLUS": 3}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_item(item_id):
    it = DB.marketplace_items.get(item_id)
    if it is None:
        raise err(ERR_ITEM_NOT_FOUND, "itemId not found")
    return it


def get_listing(lid):
    l = DB.resale_listings.get(lid)
    if l is None:
        raise err(ERR_LISTING_NOT_FOUND, "listingId not found")
    return l


def get_submission(sid):
    s = DB.moderation_submissions.get(sid)
    if s is None:
        raise err(ERR_SUBMISSION_NOT_FOUND, "submissionId not found")
    return s


def get_appeal(aid):
    a = DB.moderation_appeals.get(aid)
    if a is None:
        raise err(ERR_APPEAL_NOT_FOUND, "appealId not found")
    return a


# --- Moderation submissions ---------------------------------------------------


def create_submission(subject_type, subject_id, submitted_by):
    sub = {
        "id": new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "submitted_by_user_id": submitted_by,
        "status": "QUEUED",
        "automated_score": None,
        "reviewer_user_id": None,
        "decision": None,
        "decided_at": None,
        "_escalated": False,
        "_first_reviewer": None,
    }
    stamp_new(sub)
    DB.moderation_submissions[sub["id"]] = sub
    return sub


@bp.post("/ugc/moderation-submissions")
def create_submission_route():
    actor, role = auth_context()
    require_role(role, "Creator", "SafetyAgent")
    data = body()
    subject_type = opt_enum(data, "subject_type", ("EXPERIENCE", "ASSET", "TEXT"))
    if subject_type is None:
        raise err(ERR_INVALID_REQUEST, "subject_type is required")
    subject_id = req_str(data, "subject_id")
    if subject_type == "EXPERIENCE":
        if DB.experiences.get(subject_id) is None:
            from errors import ERR_EXPERIENCE_NOT_FOUND

            raise err(ERR_EXPERIENCE_NOT_FOUND, "experienceId not found")
    elif subject_type == "ASSET":
        if DB.marketplace_items.get(subject_id) is None:
            raise err(ERR_ITEM_NOT_FOUND, "itemId not found")
    else:
        if DB.chat_messages.get(subject_id) is None:
            raise err(ERR_INVALID_REQUEST, "subject not found")
    sub = create_submission(subject_type, subject_id, actor)
    audit(actor, "moderation.submit", "ModerationSubmission", sub["id"], {})
    return success(_public(sub), 201)


@bp.get("/ugc/moderation-submissions/<sid>")
def get_submission_route(sid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "Moderator", "AppealsReviewer", "SafetyAgent")
    return success(_public(get_submission(sid)), 200)


@bp.get("/ugc/moderation-submissions")
def list_submissions():
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin", "Moderator", "AppealsReviewer", "SafetyAgent")
    page, meta = list_view(
        DB.moderation_submissions,
        [
            ("status", "status", None),
            ("subject_type", "subject_type", None),
            ("submitted_by_user_id", "submitted_by_user_id", None),
            ("reviewer_user_id", "reviewer_user_id", None),
        ],
    )
    return success([_public(s) for s in page], 200, meta)


def _auto_route(sub, score):
    sub["automated_score"] = score
    if score >= 0.85:
        sub["status"] = "REJECTED"
        sub["decision"] = "REJECT"
        sub["decided_at"] = now_iso()
        _cascade_reject(sub)
    elif score <= 0.10:
        sub["status"] = "APPROVED"
        sub["decision"] = "APPROVE"
        sub["decided_at"] = now_iso()
        _cascade_approve(sub, "AUTOMATED")
    else:
        sub["status"] = "HUMAN_REVIEW"
    touch(sub)


def _rating_from_descriptors(descriptors):
    best = "ALL"
    for d in descriptors or []:
        r = DESCRIPTOR_SEVERITY.get(d)
        if r and RATING_ORDER[r] > RATING_ORDER[best]:
            best = r
    return best


def _apply_rating(exp, sub, assigned_by):
    """Assign rating to experience from the submission's descriptor set."""
    descriptors = exp.get("content_descriptors") or []
    rating = _rating_from_descriptors(descriptors)
    creator = DB.users.get(exp["creator_user_id"])
    if rating == "SEVENTEEN_PLUS" and creator is not None:
        svc.recompute_user_temporal(creator)
        if creator.get("age_band") == "CHILD":
            raise err(
                ERR_CREATOR_AGE_INSUFFICIENT_FOR_RATING,
                "A CHILD creator cannot publish an experience rated SEVENTEEN_PLUS",
            )
    prior = [r for r in DB.age_ratings.values() if r["experience_id"] == exp["id"] and r.get("is_current")]
    row = {
        "id": new_id(),
        "experience_id": exp["id"],
        "rating": rating,
        "descriptors": list(descriptors),
        "assigned_by": assigned_by,
        "assigned_at": now_iso(),
        "supersedes_id": prior[0]["id"] if prior else None,
        "is_current": True,
    }
    stamp_new(row)
    DB.age_ratings[row["id"]] = row
    for p in prior:
        p["is_current"] = False
        touch(p)
    exp["age_rating"] = rating
    return row


def _cascade_approve(sub, assigned_by):
    if sub["subject_type"] == "EXPERIENCE":
        exp = DB.experiences.get(sub["subject_id"])
        if exp is not None and exp["status"] == "PENDING_REVIEW":
            _apply_rating(exp, sub, assigned_by)
            exp["status"] = "PUBLISHED"
            touch(exp)
    elif sub["subject_type"] == "ASSET":
        item = DB.marketplace_items.get(sub["subject_id"])
        if item is not None and item["status"] == "PENDING_MODERATION":
            item["status"] = "ON_SALE"
            touch(item)
    # TEXT: no further action


def _cascade_reject(sub):
    if sub["subject_type"] == "EXPERIENCE":
        exp = DB.experiences.get(sub["subject_id"])
        if exp is None:
            return
        if exp["status"] == "PENDING_REVIEW":
            exp["status"] = "DRAFT"
            touch(exp)
        elif exp["status"] == "PUBLISHED":
            exp["status"] = "SUSPENDED"
            touch(exp)
            from routes_core import _tombstone_experience_chats

            _tombstone_experience_chats(exp)
    elif sub["subject_type"] == "ASSET":
        item = DB.marketplace_items.get(sub["subject_id"])
        if item is not None and item["status"] == "PENDING_MODERATION":
            item["status"] = "MODERATION_REJECTED"
            touch(item)


@bp.post("/ugc/moderation-submissions/<sid>/decide")
def decide_submission(sid):
    actor, role = auth_context()
    require_role(role, "Moderator")
    sub = get_submission(sid)
    if sub["status"] != "HUMAN_REVIEW":
        raise err(ERR_INVALID_STATE, "Submission is not in HUMAN_REVIEW")
    data = body()
    decision = opt_enum(data, "decision", ("APPROVE", "REJECT", "ESCALATE"))
    if decision is None:
        raise err(ERR_INVALID_REQUEST, "decision is required")
    if actor == sub["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Reviewer cannot decide their own submission")
    if sub.get("_first_reviewer") is not None and actor == sub["_first_reviewer"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Escalated submission must be decided by a different moderator")
    sub["reviewer_user_id"] = actor
    sub["decision"] = decision
    if decision == "APPROVE":
        sub["status"] = "APPROVED"
        sub["decided_at"] = now_iso()
        touch(sub)
        _cascade_approve(sub, "HUMAN")
    elif decision == "REJECT":
        sub["status"] = "REJECTED"
        sub["decided_at"] = now_iso()
        touch(sub)
        _cascade_reject(sub)
    else:  # ESCALATE
        sub["status"] = "QUEUED"
        sub["_escalated"] = True
        sub["_first_reviewer"] = actor
        sub["decision"] = None
        touch(sub)
    audit(actor, "moderation.decide", "ModerationSubmission", sub["id"], {"decision": decision})
    return success(_public(sub), 200)


@bp.post("/ugc/_moderation/inject_score")
def inject_score():
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    data = body()
    sid = data.get("submission_id")
    if not isinstance(sid, str) or not sid:
        raise err(ERR_INVALID_REQUEST, "submission_id is required")
    sub = get_submission(sid)
    score = data.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise err(ERR_INVALID_REQUEST, "score must be a number")
    if score < 0.0 or score > 1.0:
        raise err(ERR_INVALID_REQUEST, "score must be between 0.0 and 1.0")
    if sub["status"] != "QUEUED":
        raise err(ERR_INVALID_STATE, "Submission is not QUEUED")
    _auto_route(sub, float(score))
    audit(actor, "moderation.inject_score", "ModerationSubmission", sub["id"], {"score": score})
    return success(_public(sub), 200)


# --- Appeals ------------------------------------------------------------------


@bp.post("/ugc/moderation-appeals")
def file_appeal():
    actor, role = auth_context()
    require_role(role, "Creator")
    data = body()
    sid = data.get("submission_id")
    if not isinstance(sid, str) or not sid:
        raise err(ERR_INVALID_REQUEST, "submission_id is required")
    sub = get_submission(sid)
    reason = req_str(data, "reason", min_len=10, max_len=2000)
    if sub["status"] != "REJECTED":
        raise err(ERR_SUBMISSION_NOT_REJECTED, "Appeal requires a REJECTED submission")
    appeal = {
        "id": new_id(),
        "submission_id": sub["id"],
        "appellant_user_id": actor,
        "status": "FILED",
        "reason": reason,
        "reviewer_user_id": None,
        "decided_at": None,
    }
    stamp_new(appeal)
    DB.moderation_appeals[appeal["id"]] = appeal
    audit(actor, "moderation_appeal.file", "ModerationAppeal", appeal["id"], {})
    return success(_public(appeal), 201)


@bp.get("/ugc/moderation-appeals/<aid>")
def get_appeal_route(aid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "AppealsReviewer")
    return success(_public(get_appeal(aid)), 200)


@bp.get("/ugc/moderation-appeals")
def list_appeals():
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin", "AppealsReviewer", "Moderator")
    page, meta = list_view(
        DB.moderation_appeals,
        [
            ("submission_id", "submission_id", None),
            ("appellant_user_id", "appellant_user_id", None),
            ("reviewer_user_id", "reviewer_user_id", None),
            ("status", "status", None),
        ],
    )
    return success([_public(a) for a in page], 200, meta)


@bp.post("/ugc/moderation-appeals/<aid>/start-review")
def start_appeal_review(aid):
    actor, role = auth_context()
    require_role(role, "AppealsReviewer")
    appeal = get_appeal(aid)
    if appeal["status"] != "FILED":
        raise err(ERR_INVALID_STATE, "Appeal is not FILED")
    sub = get_submission(appeal["submission_id"])
    if sub.get("reviewer_user_id") is not None and actor == sub["reviewer_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Appeals reviewer must differ from the original reviewer")
    appeal["status"] = "UNDER_REVIEW"
    appeal["reviewer_user_id"] = actor
    touch(appeal)
    audit(actor, "moderation_appeal.start_review", "ModerationAppeal", appeal["id"], {})
    return success(_public(appeal), 200)


@bp.post("/ugc/moderation-appeals/<aid>/decide")
def decide_appeal(aid):
    actor, role = auth_context()
    require_role(role, "AppealsReviewer")
    appeal = get_appeal(aid)
    if appeal["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Appeal is not UNDER_REVIEW")
    data = body()
    outcome = opt_enum(data, "outcome", ("UPHELD", "OVERTURNED"))
    if outcome is None:
        raise err(ERR_INVALID_REQUEST, "outcome must be UPHELD or OVERTURNED")
    sub = get_submission(appeal["submission_id"])
    appeal["status"] = outcome
    appeal["decided_at"] = now_iso()
    touch(appeal)
    if outcome == "OVERTURNED":
        sub["status"] = "APPROVED"
        sub["decision"] = "APPROVE"
        sub["decided_at"] = now_iso()
        touch(sub)
        if sub["subject_type"] == "EXPERIENCE":
            exp = DB.experiences.get(sub["subject_id"])
            if exp is not None:
                _apply_rating(exp, sub, "APPEAL_DECISION")
                if exp["status"] == "DRAFT":
                    exp["status"] = "PUBLISHED"
                    touch(exp)
        elif sub["subject_type"] == "ASSET":
            item = DB.marketplace_items.get(sub["subject_id"])
            if item is not None and item["status"] == "MODERATION_REJECTED":
                item["status"] = "ON_SALE"
                touch(item)
    audit(actor, "moderation_appeal.decide", "ModerationAppeal", appeal["id"], {"outcome": outcome})
    return success(_public(appeal), 200)


@bp.post("/ugc/moderation-appeals/<aid>/withdraw")
def withdraw_appeal(aid):
    actor, role = auth_context()
    require_role(role, "Creator")
    appeal = get_appeal(aid)
    if appeal["appellant_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the appellant may withdraw")
    if appeal["status"] != "FILED":
        raise err(ERR_INVALID_STATE, "Appeal is not FILED")
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    audit(actor, "moderation_appeal.withdraw", "ModerationAppeal", appeal["id"], {})
    return success(_public(appeal), 200)


# --- Currency purchase orders ---------------------------------------------------


def get_cpo(oid):
    o = DB.currency_purchase_orders.get(oid)
    if o is None:
        raise err(ERR_ORDER_NOT_FOUND, "orderId not found")
    return o


@bp.post("/ugc/currency-purchase-orders")
def create_cpo():
    actor, role = auth_context()
    require_role(role, "Creator")
    buyer = DB.users.get(actor)
    if buyer is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    fiat = req_int(data, "fiat_amount_cents", minimum=1)
    token = req_str(data, "payment_method_token")
    idem = req_str(data, "idempotency_key")
    existing_id = DB.cpo_idem.get(idem)
    if existing_id is not None:
        existing = DB.currency_purchase_orders[existing_id]
        if (
            existing["fiat_amount_cents"] != fiat
            or existing["payment_method_token"] != token
            or existing["buyer_user_id"] != buyer["id"]
        ):
            raise err(ERR_DUPLICATE_IDEMPOTENCY_KEY, "Idempotency key already used with a different payload")
        return success(_public(existing), 201)
    order = {
        "id": new_id(),
        "buyer_user_id": buyer["id"],
        "fiat_amount_cents": fiat,
        "status": "PENDING_PAYMENT",
        "credited_robux": None,
        "payment_method_token": token,
        "idempotency_key": idem,
        "completed_at": None,
    }
    stamp_new(order)
    DB.currency_purchase_orders[order["id"]] = order
    DB.cpo_idem[idem] = order["id"]
    audit(actor, "currency_purchase_order.create", "CurrencyPurchaseOrder", order["id"], {})
    return success(_public(order), 201)


@bp.get("/ugc/currency-purchase-orders/<oid>")
def get_cpo_route(oid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    return success(_public(get_cpo(oid)), 200)


@bp.get("/ugc/currency-purchase-orders")
def list_cpos():
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    page, meta = list_view(
        DB.currency_purchase_orders,
        [("buyer_user_id", "buyer_user_id", None), ("status", "status", None)],
    )
    return success([_public(o) for o in page], 200, meta)


@bp.post("/ugc/currency-purchase-orders/<oid>/confirm-payment")
def confirm_cpo(oid):
    actor, role = auth_context()
    require_role(role, "Creator")
    order = get_cpo(oid)
    if order["status"] != "PENDING_PAYMENT":
        raise err(ERR_INVALID_STATE, "Order is not PENDING_PAYMENT")
    if order["buyer_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the buyer may confirm payment")
    for other in DB.currency_purchase_orders.values():
        if (
            other["id"] != order["id"]
            and other["idempotency_key"] == order["idempotency_key"]
            and other["status"] == "COMPLETED"
        ):
            raise err(ERR_DUPLICATE_IDEMPOTENCY_KEY, "Idempotency key already completed")
    credited = svc.tiered_exchange_robux(order["fiat_amount_cents"])
    buyer = DB.users[order["buyer_user_id"]]
    order["credited_robux"] = credited
    order["status"] = "COMPLETED"
    order["completed_at"] = now_iso()
    touch(order)
    buyer["robux_balance"] = buyer.get("robux_balance", 0) + credited
    touch(buyer)
    audit(actor, "currency_purchase_order.confirm", "CurrencyPurchaseOrder", order["id"], {"credited_robux": credited})
    return success(_public(order), 200)


@bp.post("/ugc/currency-purchase-orders/<oid>/fail-payment")
def fail_cpo(oid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    order = get_cpo(oid)
    if order["status"] != "PENDING_PAYMENT":
        raise err(ERR_INVALID_STATE, "Order is not PENDING_PAYMENT")
    order["status"] = "FAILED"
    touch(order)
    audit(actor, "currency_purchase_order.fail", "CurrencyPurchaseOrder", order["id"], {})
    return success(_public(order), 200)


@bp.post("/ugc/currency-purchase-orders/<oid>/refund")
def refund_cpo(oid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    order = get_cpo(oid)
    if order["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Order is not COMPLETED")
    buyer = DB.users[order["buyer_user_id"]]
    if buyer.get("robux_balance", 0) < (order["credited_robux"] or 0):
        raise err(ERR_REFUND_EXCEEDS_BALANCE, "Refund would drive robux_balance negative")
    buyer["robux_balance"] -= order["credited_robux"]
    touch(buyer)
    order["status"] = "REFUNDED"
    touch(order)
    audit(actor, "currency_purchase_order.refund", "CurrencyPurchaseOrder", order["id"], {})
    return success(_public(order), 200)


# --- Marketplace items ---------------------------------------------------------


@bp.post("/ugc/marketplace-items")
def create_item():
    actor, role = auth_context()
    require_role(role, "Creator")
    creator = DB.users.get(actor)
    if creator is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    title = req_str(data, "title", min_len=3, max_len=60)
    kind = opt_enum(data, "item_kind", ITEM_KINDS)
    if kind is None:
        raise err(ERR_INVALID_REQUEST, "item_kind is required")
    price = req_int(data, "price_robux", minimum=0)
    is_limited = kind in LIMITED_KINDS
    total_supply = data.get("total_supply")
    royalty = data.get("royalty_pct")
    if is_limited:
        if total_supply is None or isinstance(total_supply, bool) or not isinstance(total_supply, int) or total_supply < 1:
            raise err(ERR_INVALID_REQUEST, "total_supply is required for limited items")
        if royalty is None:
            royalty = 0
        if isinstance(royalty, bool) or not isinstance(royalty, int) or royalty < 0 or royalty > 50:
            raise err(ERR_INVALID_REQUEST, "royalty_pct must be between 0 and 50")
    else:
        if total_supply is not None:
            raise err(ERR_INVALID_REQUEST, "total_supply must be null for non-limited items")
        if royalty not in (None, 0):
            raise err(ERR_INVALID_REQUEST, "royalty_pct must be 0 for non-limited items")
        royalty = 0
    item = {
        "id": new_id(),
        "creator_user_id": creator["id"],
        "title": title,
        "item_kind": kind,
        "price_robux": price,
        "status": "DRAFT",
        "total_supply": total_supply,
        "copies_sold": 0,
        "is_limited": is_limited,
        "royalty_pct": royalty,
        "moderation_submission_id": None,
        "_owners": [creator["id"]] if is_limited else [],
    }
    stamp_new(item)
    DB.marketplace_items[item["id"]] = item
    audit(actor, "marketplace_item.create", "MarketplaceItem", item["id"], {})
    return success(_public(item), 201)


@bp.get("/ugc/marketplace-items/<item_id>")
def get_item_route(item_id):
    auth_context()
    require_role(
        auth_context()[1],
        "Anonymous",
        "Creator",
        "PlatformAdmin",
        "Moderator",
        "SafetyAgent",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    return success(_public(get_item(item_id)), 200)


@bp.get("/ugc/marketplace-items")
def list_items():
    auth_context()
    require_role(
        auth_context()[1],
        "Anonymous",
        "Creator",
        "PlatformAdmin",
        "Moderator",
        "SafetyAgent",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    page, meta = list_view(
        DB.marketplace_items,
        [
            ("creator_user_id", "creator_user_id", None),
            ("status", "status", None),
            ("item_kind", "item_kind", None),
            ("moderation_submission_id", "moderation_submission_id", None),
        ],
    )
    return success([_public(i) for i in page], 200, meta)


@bp.post("/ugc/marketplace-items/<item_id>/submit")
def submit_item(item_id):
    actor, role = auth_context()
    require_role(role, "Creator")
    item = get_item(item_id)
    if item["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may submit")
    if item["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Item is not DRAFT")
    creator = DB.users.get(item["creator_user_id"])
    if creator is None or creator["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Creator is not ACTIVE")
    item["status"] = "PENDING_MODERATION"
    sub = create_submission("ASSET", item["id"], actor)
    item["moderation_submission_id"] = sub["id"]
    touch(item)
    audit(actor, "marketplace_item.submit", "MarketplaceItem", item["id"], {"submission_id": sub["id"]})
    return success(_public(item), 200)


@bp.post("/ugc/marketplace-items/<item_id>/take-off-sale")
def take_off_sale(item_id):
    actor, role = auth_context()
    require_role(role, "Creator")
    item = get_item(item_id)
    if item["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may take the item off sale")
    if item["status"] != "ON_SALE":
        raise err(ERR_INVALID_STATE, "Item is not ON_SALE")
    item["status"] = "OFF_SALE"
    touch(item)
    audit(actor, "marketplace_item.take_off_sale", "MarketplaceItem", item["id"], {})
    return success(_public(item), 200)


@bp.post("/ugc/marketplace-items/<item_id>/put-on-sale")
def put_on_sale(item_id):
    actor, role = auth_context()
    require_role(role, "Creator")
    item = get_item(item_id)
    if item["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may put the item on sale")
    if item["status"] != "OFF_SALE":
        raise err(ERR_INVALID_STATE, "Item is not OFF_SALE")
    item["status"] = "ON_SALE"
    touch(item)
    audit(actor, "marketplace_item.put_on_sale", "MarketplaceItem", item["id"], {})
    return success(_public(item), 200)


# --- Resale listings ------------------------------------------------------------


@bp.post("/ugc/resale-listings")
def create_listing():
    actor, role = auth_context()
    require_role(role, "Creator")
    seller = DB.users.get(actor)
    if seller is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    item_id = data.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise err(ERR_INVALID_REQUEST, "item_id is required")
    item = get_item(item_id)
    ask = req_int(data, "ask_price_robux", minimum=0)
    if "expected_item_version" not in data:
        raise err(ERR_INVALID_REQUEST, "expected_item_version is required")
    expected = data.get("expected_item_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_INVALID_REQUEST, "expected_item_version must be an integer")
    if not item.get("is_limited"):
        raise err(ERR_INVALID_REQUEST, "Only limited items can be listed for resale")
    svc.recompute_user_temporal(seller)
    if seller.get("account_age_days", 0) < 7:
        raise err(ERR_INVALID_STATE, "Seller account must be at least 7 days old for resale")
    if item["status"] != "ON_SALE":
        raise err(ERR_ITEM_NOT_ON_SALE, "Item is not ON_SALE; new listings are blocked")
    if actor not in item.get("_owners", []):
        raise err(ERR_UNAUTHORIZED_ROLE, "Seller does not own a copy of this limited item")
    floor_price = svc.resale_floor(item["price_robux"])
    if ask < floor_price:
        raise err(ERR_RESALE_FLOOR_VIOLATION, "ask_price_robux below the resale floor")
    if expected != item["version"]:
        raise err(ERR_STALE_VERSION, "expected_item_version does not match the item version")
    listing = {
        "id": new_id(),
        "item_id": item["id"],
        "seller_user_id": seller["id"],
        "status": "ACTIVE",
        "ask_price_robux": ask,
        "listed_at": iso_ms(DB.current_utc),
        "sold_at": None,
        "buyer_user_id": None,
        "expected_item_version": expected,
    }
    stamp_new(listing)
    DB.resale_listings[listing["id"]] = listing
    audit(actor, "resale_listing.create", "ResaleListing", listing["id"], {})
    return success(_public(listing), 201)


@bp.get("/ugc/resale-listings/<lid>")
def get_listing_route(lid):
    auth_context()
    require_role(auth_context()[1], "Anonymous", "Creator", "PlatformAdmin", "SafetyAgent")
    return success(_public(get_listing(lid)), 200)


@bp.get("/ugc/resale-listings")
def list_listings():
    auth_context()
    require_role(auth_context()[1], "Anonymous", "Creator", "PlatformAdmin", "SafetyAgent")
    page, meta = list_view(
        DB.resale_listings,
        [
            ("item_id", "item_id", None),
            ("seller_user_id", "seller_user_id", None),
            ("buyer_user_id", "buyer_user_id", None),
            ("status", "status", None),
        ],
    )
    return success([_public(l) for l in page], 200, meta)


@bp.post("/ugc/resale-listings/<lid>/cancel")
def cancel_listing(lid):
    actor, role = auth_context()
    require_role(role, "Creator")
    listing = get_listing(lid)
    if listing["seller_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the seller may cancel")
    if listing["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Listing is not ACTIVE")
    listing["status"] = "CANCELLED"
    touch(listing)
    audit(actor, "resale_listing.cancel", "ResaleListing", listing["id"], {})
    return success(_public(listing), 200)


# --- Purchase orders ------------------------------------------------------------


def get_po(oid):
    o = DB.purchase_orders.get(oid)
    if o is None:
        raise err(ERR_ORDER_NOT_FOUND, "orderId not found")
    return o


@bp.post("/ugc/purchase-orders")
def create_po():
    actor, role = auth_context()
    require_role(role, "Creator")
    buyer = DB.users.get(actor)
    if buyer is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    item_type = opt_enum(data, "item_type", ("MARKETPLACE_ITEM", "EXPERIENCE_GAMEPASS", "LIMITED_ITEM_RESALE"))
    if item_type is None:
        raise err(ERR_INVALID_REQUEST, "item_type is required")
    item_id = req_str(data, "item_id")
    price = req_int(data, "price_robux", minimum=0)
    idem = req_str(data, "idempotency_key")
    # existence of the polymorphic target
    if item_type == "MARKETPLACE_ITEM":
        get_item(item_id)
    elif item_type == "EXPERIENCE_GAMEPASS":
        from errors import ERR_EXPERIENCE_NOT_FOUND

        if item_id not in DB.experiences:
            raise err(ERR_EXPERIENCE_NOT_FOUND, "experienceId not found")
    else:
        get_listing(item_id)
    existing_id = DB.po_idem.get(idem)
    if existing_id is not None:
        existing = DB.purchase_orders[existing_id]
        if (
            existing["item_type"] != item_type
            or existing["item_id"] != item_id
            or existing["price_robux"] != price
            or existing["buyer_user_id"] != buyer["id"]
        ):
            raise err(ERR_DUPLICATE_IDEMPOTENCY_KEY, "Idempotency key already used with a different payload")
        return success(_public(existing), 201)
    order = {
        "id": new_id(),
        "buyer_user_id": buyer["id"],
        "item_type": item_type,
        "item_id": item_id,
        "status": "PENDING",
        "price_robux": price,
        "creator_credit_robux": None,
        "platform_fee_robux": None,
        "idempotency_key": idem,
        "completed_at": None,
    }
    stamp_new(order)
    DB.purchase_orders[order["id"]] = order
    DB.po_idem[idem] = order["id"]
    audit(actor, "purchase_order.create", "PurchaseOrder", order["id"], {})
    return success(_public(order), 201)


@bp.get("/ugc/purchase-orders/<oid>")
def get_po_route(oid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    return success(_public(get_po(oid)), 200)


@bp.get("/ugc/purchase-orders")
def list_pos():
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    page, meta = list_view(
        DB.purchase_orders,
        [
            ("buyer_user_id", "buyer_user_id", None),
            ("item_type", "item_type", None),
            ("item_id", "item_id", None),
            ("status", "status", None),
        ],
    )
    return success([_public(o) for o in page], 200, meta)


def _month_spent(buyer_id):
    cur = DB.current_utc
    month_start = cur.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0
    for o in DB.purchase_orders.values():
        if o["buyer_user_id"] != buyer_id or o["status"] != "COMPLETED":
            continue
        c = o.get("_completed_dt")
        if c is not None and month_start <= c <= cur:
            total += o["price_robux"]
    return total


@bp.post("/ugc/purchase-orders/<oid>/confirm")
def confirm_po(oid):
    actor, role = auth_context()
    require_role(role, "Creator")
    order = get_po(oid)
    if order["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Order is not PENDING")
    if order["buyer_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the buyer may confirm the purchase")
    buyer = DB.users[order["buyer_user_id"]]
    svc.recompute_user_temporal(buyer)

    # ---- priority 5: safety checks ----
    pc = svc.get_pc(buyer["id"])
    if pc is not None and pc.get("monthly_spend_limit_robux") is not None:
        if _month_spent(buyer["id"]) + order["price_robux"] >= pc["monthly_spend_limit_robux"]:
            raise err(ERR_PARENTAL_SPEND_LIMIT, "Purchase would reach or exceed the parental monthly spend limit")

    exp = None
    item = None
    listing = None
    if order["item_type"] == "EXPERIENCE_GAMEPASS":
        exp = DB.experiences[order["item_id"]]
        rating = exp.get("age_rating") or "ALL"
        if not svc.allowed_for_child(buyer, rating):
            raise err(ERR_AGE_BAND_INSUFFICIENT, "Buyer's age band does not satisfy the experience rating")
    elif order["item_type"] == "LIMITED_ITEM_RESALE":
        listing = DB.resale_listings[order["item_id"]]
        item = DB.marketplace_items[listing["item_id"]]
    else:
        item = DB.marketplace_items[order["item_id"]]

    # ---- priority 6: structural ----
    if order["item_type"] == "MARKETPLACE_ITEM" and item.get("is_limited"):
        ts = item.get("total_supply")
        if ts is not None and item.get("copies_sold", 0) + 1 > ts:
            raise err(ERR_LIMITED_SUPPLY_EXHAUSTED, "Limited supply exhausted")

    # ---- priority 7: cross-entity state gates ----
    if order["item_type"] == "EXPERIENCE_GAMEPASS":
        if exp["status"] != "PUBLISHED":
            raise err(ERR_EXPERIENCE_NOT_PUBLISHED, "Experience is not PUBLISHED")
    elif order["item_type"] == "MARKETPLACE_ITEM":
        if item["status"] != "ON_SALE":
            raise err(ERR_ITEM_NOT_ON_SALE, "Item is not ON_SALE")
    else:
        if listing["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Resale listing is not ACTIVE")

    # ---- priority 8: fiscal ----
    if buyer.get("robux_balance", 0) < order["price_robux"]:
        raise err(ERR_INSUFFICIENT_ROBUX, "Buyer's robux_balance is below the price")
    if order["item_type"] == "LIMITED_ITEM_RESALE":
        if listing["expected_item_version"] != item["version"]:
            raise err(ERR_STALE_VERSION, "The listing's pinned item version no longer matches")
        seller = DB.users[listing["seller_user_id"]]
        svc.recompute_user_temporal(seller)
        if seller.get("account_age_days", 0) < 7:
            raise err(ERR_INVALID_STATE, "Seller account no longer satisfies the resale age gate")

    # ---- settle ----
    buyer["robux_balance"] -= order["price_robux"]
    touch(buyer)
    if order["item_type"] == "LIMITED_ITEM_RESALE":
        fee, seller_credit, royalty = svc.split_resale(order["price_robux"], item.get("royalty_pct", 0))
        order["platform_fee_robux"] = fee
        order["creator_credit_robux"] = seller_credit
        seller["robux_balance"] = seller.get("robux_balance", 0) + seller_credit
        seller["earned_robux_lifetime"] = seller.get("earned_robux_lifetime", 0) + seller_credit
        touch(seller)
        original_creator = DB.users.get(item["creator_user_id"])
        if original_creator is not None and royalty:
            original_creator["earned_robux_lifetime"] = original_creator.get("earned_robux_lifetime", 0) + royalty
            touch(original_creator)
        order["_royalty_robux"] = royalty
        listing["status"] = "SOLD"
        listing["sold_at"] = now_iso()
        listing["buyer_user_id"] = buyer["id"]
        touch(listing)
        owners = item.setdefault("_owners", [])
        if seller["id"] in owners:
            owners.remove(seller["id"])
        owners.append(buyer["id"])
    else:
        fee, credit = svc.split_non_limited(order["price_robux"])
        order["platform_fee_robux"] = fee
        order["creator_credit_robux"] = credit
        if order["item_type"] == "MARKETPLACE_ITEM":
            seller = DB.users.get(item["creator_user_id"])
            item["copies_sold"] = item.get("copies_sold", 0) + 1
            if item.get("is_limited"):
                # Primary purchase of a limited item grants the buyer ownership of a
                # copy (PRD §3.6: resale listings require the seller to own the item).
                owners = item.setdefault("_owners", [])
                if buyer["id"] not in owners:
                    owners.append(buyer["id"])
            touch(item)
        else:
            seller = DB.users.get(exp["creator_user_id"])
        if seller is not None:
            seller["earned_robux_lifetime"] = seller.get("earned_robux_lifetime", 0) + credit
            touch(seller)
    order["status"] = "COMPLETED"
    order["completed_at"] = now_iso()
    order["_completed_dt"] = DB.current_utc
    touch(order)
    audit(actor, "purchase_order.confirm", "PurchaseOrder", order["id"], {"price_robux": order["price_robux"]})
    return success(_public(order), 200)


@bp.post("/ugc/purchase-orders/<oid>/refund")
def refund_po(oid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    order = get_po(oid)
    if order["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Order is not COMPLETED")
    buyer = DB.users[order["buyer_user_id"]]
    if order["item_type"] == "LIMITED_ITEM_RESALE":
        listing = DB.resale_listings[order["item_id"]]
        item = DB.marketplace_items[listing["item_id"]]
        if buyer["id"] not in item.get("_owners", []):
            raise err(ERR_INVALID_STATE, "Buyer no longer owns the item")
        seller = DB.users[listing["seller_user_id"]]
        royalty = order.get("_royalty_robux", 0)
        original_creator = DB.users.get(item["creator_user_id"])
        if original_creator is not None and royalty:
            original_creator["earned_robux_lifetime"] = original_creator.get("earned_robux_lifetime", 0) - royalty
            touch(original_creator)
        if seller is not None:
            seller["earned_robux_lifetime"] = seller.get("earned_robux_lifetime", 0) - (order["creator_credit_robux"] or 0)
            seller["robux_balance"] = seller.get("robux_balance", 0) - (order["creator_credit_robux"] or 0)
            touch(seller)
        owners = item.setdefault("_owners", [])
        if buyer["id"] in owners:
            owners.remove(buyer["id"])
        owners.append(listing["seller_user_id"])
    else:
        if order["item_type"] == "MARKETPLACE_ITEM":
            item = DB.marketplace_items[order["item_id"]]
            seller = DB.users.get(item["creator_user_id"])
            item["copies_sold"] = max(0, item.get("copies_sold", 0) - 1)
            touch(item)
        else:
            exp = DB.experiences[order["item_id"]]
            seller = DB.users.get(exp["creator_user_id"])
        if seller is not None:
            seller["earned_robux_lifetime"] = seller.get("earned_robux_lifetime", 0) - (order["creator_credit_robux"] or 0)
            touch(seller)
    buyer["robux_balance"] = buyer.get("robux_balance", 0) + order["price_robux"]
    touch(buyer)
    order["status"] = "REFUNDED"
    touch(order)
    audit(actor, "purchase_order.refund", "PurchaseOrder", order["id"], {})
    return success(_public(order), 200)


# --- DevEx ---------------------------------------------------------------------


def get_devex(rid):
    r = DB.devex_requests.get(rid)
    if r is None:
        raise err(ERR_ORDER_NOT_FOUND, "devex request not found")
    return r


def _locked_robux(user_id):
    return sum(
        r["locked_robux"]
        for r in DB.devex_requests.values()
        if r["user_id"] == user_id and r["status"] in ("SUBMITTED", "APPROVED")
    )


@bp.post("/ugc/devex-requests")
def create_devex():
    actor, role = auth_context()
    require_role(role, "Creator")
    user = DB.users.get(actor)
    if user is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    requested = data.get("requested_robux")
    if requested is None or isinstance(requested, bool) or not isinstance(requested, int):
        raise err(ERR_INVALID_REQUEST, "requested_robux must be an integer")
    if "expected_user_version" not in data:
        raise err(ERR_INVALID_REQUEST, "expected_user_version is required")
    expected = data.get("expected_user_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_INVALID_REQUEST, "expected_user_version must be an integer")
    # fiscal checks in PRD order: minimum, eligibility, over-earned, OCC
    if requested < 30000:
        raise err(ERR_DEVEX_MINIMUM_NOT_MET, "requested_robux below the 30000 minimum")
    if not svc.devex_eligible(user):
        raise err(ERR_DEVEX_NOT_ELIGIBLE, "User fails one or more DevEx eligibility clauses")
    if requested > user.get("earned_robux_lifetime", 0) - _locked_robux(user["id"]):
        raise err(ERR_DEVEX_NOT_ELIGIBLE, "requested_robux exceeds earned balance net of locked Robux")
    if expected != user["version"]:
        raise err(ERR_STALE_VERSION, "expected_user_version does not match the user version")
    req = {
        "id": new_id(),
        "user_id": user["id"],
        "status": "SUBMITTED",
        "requested_robux": requested,
        "locked_robux": requested,
        "usd_payout_cents": None,
        "withholding_tax_cents": None,
        "net_payout_cents": None,
        "submitted_at": iso_ms(DB.current_utc),
        "approved_at": None,
        "paid_at": None,
        "expected_user_version": expected,
        "_approved_by": None,
    }
    stamp_new(req)
    DB.devex_requests[req["id"]] = req
    audit(actor, "devex.submit", "DevExchangeRequest", req["id"], {"requested_robux": requested})
    return success(_public(req), 201)


@bp.get("/ugc/devex-requests/<rid>")
def get_devex_route(rid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    return success(_public(get_devex(rid)), 200)


@bp.get("/ugc/devex-requests")
def list_devex():
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin", "FinanceOfficer")
    page, meta = list_view(
        DB.devex_requests,
        [("user_id", "user_id", None), ("status", "status", None)],
    )
    return success([_public(r) for r in page], 200, meta)


@bp.post("/ugc/devex-requests/<rid>/approve")
def approve_devex(rid):
    actor, role = auth_context()
    require_role(role, "FinanceOfficer")
    req = get_devex(rid)
    if req["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "DevEx request is not SUBMITTED")
    user = DB.users.get(req["user_id"])
    if user is None:
        raise err(ERR_USER_NOT_FOUND, "user not found")
    if not svc.devex_eligible(user):
        raise err(ERR_DEVEX_NOT_ELIGIBLE, "User fails one or more DevEx eligibility clauses")
    if req["expected_user_version"] != user["version"]:
        raise err(ERR_STALE_VERSION, "expected_user_version does not match the user version")
    usd = svc.devex_ladder_cents(req["requested_robux"])
    td = svc.latest_td(user["id"])
    form_type = td["form_type"] if td is not None else "W9"
    withholding = svc.withholding_cents(usd, form_type)
    req["usd_payout_cents"] = usd
    req["withholding_tax_cents"] = withholding
    req["net_payout_cents"] = usd - withholding
    req["approved_at"] = now_iso()
    req["status"] = "APPROVED"
    req["_approved_by"] = actor
    touch(req)
    audit(actor, "devex.approve", "DevExchangeRequest", req["id"], {"usd_payout_cents": usd})
    return success(_public(req), 200)


@bp.post("/ugc/devex-requests/<rid>/reject")
def reject_devex(rid):
    actor, role = auth_context()
    require_role(role, "FinanceOfficer")
    req = get_devex(rid)
    if req["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "DevEx request is not SUBMITTED")
    body()  # reason optional in effect; lock released regardless
    req["status"] = "REJECTED"
    touch(req)
    audit(actor, "devex.reject", "DevExchangeRequest", req["id"], {})
    return success(_public(req), 200)


@bp.post("/ugc/devex-requests/<rid>/mark-paid")
def mark_paid_devex(rid):
    actor, role = auth_context()
    require_role(role, "FinanceOfficer")
    req = get_devex(rid)
    if req["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "DevEx request is not APPROVED")
    if req.get("_approved_by") == actor:
        raise err(ERR_SEGREGATION_OF_DUTIES, "The same officer cannot approve and pay")
    user = DB.users[req["user_id"]]
    user["robux_balance"] = user.get("robux_balance", 0) - req["requested_robux"]
    touch(user)
    req["status"] = "PAID"
    req["paid_at"] = now_iso()
    touch(req)
    audit(actor, "devex.mark_paid", "DevExchangeRequest", req["id"], {})
    return success(_public(req), 200)


@bp.post("/ugc/devex-requests/<rid>/cancel")
def cancel_devex(rid):
    actor, role = auth_context()
    require_role(role, "Creator")
    req = get_devex(rid)
    if req["user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may cancel")
    if req["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "DevEx request is not SUBMITTED")
    req["status"] = "CANCELLED"
    touch(req)
    audit(actor, "devex.cancel", "DevExchangeRequest", req["id"], {})
    return success(_public(req), 200)

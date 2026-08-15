"""Report submission and quality-control endpoints (PRD 3.6, 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INSUFFICIENT_COMPARABLES,
    ERR_INSUFFICIENT_PHOTOS,
    ERR_FEE_RECONCILE_MISMATCH,
    ERR_QC_CYCLE_ALREADY_OPEN,
    ERR_QC_CYCLE_STALE,
    ERR_REVISION_NOT_OPEN,
)
from middleware import allowed
from response import success_object, success_list
from serializers import ser_qc_review, ser_revision_request, ser_order
from services.scoring import recompute_composite_score
from routes.orders import get_order_or_404
from validation import body, req_str, req_enum, req_int, sort_and_page

bp = Blueprint("qc", __name__)

# PRD leaves the revision window length unspecified ("the revision window in
# hours"); 72 hours is the vendor-standard revision turnaround adopted here.
REVISION_WINDOW_HOURS = 72

VERDICTS = {"APPROVE", "REVISE", "REJECT"}

DRIVE_BY_PHOTO_KINDS = {"FRONT", "STREET"}
INTERIOR_PHOTO_KINDS = {"INTERIOR_LIVING", "INTERIOR_KITCHEN", "INTERIOR_BATH"}

COMPARABLE_FLOORS = {"DRIVE_BY": 3, "INTERIOR": 4}


def _get_qc_or_404(order_id: str, qc_id: str) -> dict:
    review = db.qc_reviews.get(qc_id)
    if review is None or review["order_id"] != order_id:
        raise ApiError(ERR_NOT_FOUND, f"QCReview {qc_id} not found on order {order_id}", 404)
    return review


def _get_revision_or_404(order_id: str, rev_id: str) -> dict:
    rev = db.revision_requests.get(rev_id)
    if rev is None or rev["order_id"] != order_id:
        raise ApiError(ERR_NOT_FOUND, f"QCRevisionRequest {rev_id} not found on order {order_id}", 404)
    return rev


def _latest_cycle_index(order_id: str) -> int:
    cycles = [r["cycle_index"] for r in db.qc_reviews.values() if r["order_id"] == order_id]
    return max(cycles) if cycles else 0


# ---------------------------------------------------------------------------
# Report submission
# ---------------------------------------------------------------------------

@bp.post("/bpo/valuation-orders/<order_id>/report")
@allowed("Broker")
def submit_report(user_id, role, order_id):
    order = get_order_or_404(order_id)
    # Priority 5: state legality
    if order["fulfillment_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected IN_PROGRESS", 409)

    # Priority 10: comparable-count floor
    selected = [c for c in db.comparables.values() if c["order_id"] == order_id and c["status"] == "SELECTED"]
    floor = COMPARABLE_FLOORS[order["inspection_level"]]
    if len(selected) < floor:
        raise ApiError(
            ERR_INSUFFICIENT_COMPARABLES,
            f"Order requires at least {floor} SELECTED comparables, has {len(selected)}",
            422,
        )

    # Priority 11: photo-evidence minimum
    photos = [p for p in db.photos.values() if p["order_id"] == order_id]
    if order["inspection_level"] == "DRIVE_BY":
        count = sum(1 for p in photos if p["photo_kind"] in DRIVE_BY_PHOTO_KINDS)
        if count < 2:
            raise ApiError(
                ERR_INSUFFICIENT_PHOTOS,
                "DRIVE_BY orders require at least 2 photos of kind FRONT or STREET",
                422,
            )
    else:
        kinds_present = {p["photo_kind"] for p in photos}
        if not INTERIOR_PHOTO_KINDS.issubset(kinds_present):
            raise ApiError(
                ERR_INSUFFICIENT_PHOTOS,
                "INTERIOR orders require one photo each of INTERIOR_LIVING, INTERIOR_KITCHEN and INTERIOR_BATH",
                422,
            )

    # Priority 12: fee reconciliation
    fee_sum = sum(
        f["amount_cents"]
        for f in db.fee_lines.values()
        if f["order_id"] == order_id and f["status"] != "CANCELLED"
    )
    if fee_sum != order["agreed_fee_cents"]:
        raise ApiError(
            ERR_FEE_RECONCILE_MISMATCH,
            f"Sum of non-cancelled fee lines ({fee_sum}) != agreed_fee_cents ({order['agreed_fee_cents']})",
            422,
        )

    # Priority 30: ownership
    if user_id != order["assigned_broker_id"]:
        raise ApiError(ERR_FORBIDDEN, "Only the assigned broker may submit the report", 403)

    # Side effect: recompute adjusted_value_cents for SELECTED comparables
    for comp in selected:
        comp["adjusted_value_cents"] = comp["sale_price_cents"] + comp["adjustment_cents"]

    order["fulfillment_status"] = "REPORT_SUBMITTED"
    db.touch(order)
    return success_object(ser_order(order))


# ---------------------------------------------------------------------------
# QC review cycles
# ---------------------------------------------------------------------------

@bp.post("/bpo/valuation-orders/<order_id>/qc/open")
@allowed("QCReviewer")
def open_qc_cycle(user_id, role, order_id):
    order = get_order_or_404(order_id)
    if order["fulfillment_status"] != "REPORT_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected REPORT_SUBMITTED", 409)
    # Priority 17: no other OPEN cycle on the order
    for review in db.qc_reviews.values():
        if review["order_id"] == order_id and review["reviewed_at"] is None:
            raise ApiError(ERR_QC_CYCLE_ALREADY_OPEN, "Another QC review cycle is currently OPEN", 409)

    record = db.stamp_new({
        "id": db.new_id(),
        "order_id": order_id,
        "reviewer_id": user_id,
        "cycle_index": _latest_cycle_index(order_id) + 1,
        "verdict": None,
        "defects_found": None,
        "notes": None,
        "reviewed_at": None,
        "is_segregation_violation": False,
    })
    db.qc_reviews[record["id"]] = record
    order["fulfillment_status"] = "QC_REVIEW"
    db.touch(order)
    return success_object(ser_qc_review(record), 201)


@bp.get("/bpo/valuation-orders/<order_id>/qc")
@allowed("QCReviewer", "OperationsManager", "PlatformAdmin", "Broker")
def list_qc_reviews(user_id, role, order_id):
    get_order_or_404(order_id)
    records = [r for r in db.qc_reviews.values() if r["order_id"] == order_id]
    items, limit, offset, total = sort_and_page(records, ser_qc_review)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/qc-reviews/<qc_id>")
@allowed("QCReviewer", "OperationsManager", "PlatformAdmin")
def get_qc_review(user_id, role, qc_id):
    review = db.qc_reviews.get(qc_id)
    if review is None:
        raise ApiError(ERR_NOT_FOUND, f"QCReview {qc_id} not found", 404)
    return success_object(ser_qc_review(review))


@bp.get("/bpo/qc-reviews/<qc_id>/revisions")
@allowed("QCReviewer", "OperationsManager", "PlatformAdmin", "Broker")
def list_qc_review_revisions(user_id, role, qc_id):
    review = db.qc_reviews.get(qc_id)
    if review is None:
        raise ApiError(ERR_NOT_FOUND, f"QCReview {qc_id} not found", 404)
    records = [r for r in db.revision_requests.values() if r["qc_review_id"] == qc_id]
    outcome = request.args.get("outcome")
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    items, limit, offset, total = sort_and_page(records, ser_revision_request)
    return success_list(items, limit, offset, total)


@bp.post("/bpo/valuation-orders/<order_id>/qc/<qc_id>/verdict")
@allowed("QCReviewer")
def record_verdict(user_id, role, order_id, qc_id):
    order = get_order_or_404(order_id)
    review = _get_qc_or_404(order_id, qc_id)

    # Priority 5: state legality
    if order["fulfillment_status"] != "QC_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected QC_REVIEW", 409)

    # Priority 6: segregation of duties (PRD 2.8) — the attempt is recorded on
    # the review's is_segregation_violation flag even though it is refused.
    broker = db.brokers.get(order["assigned_broker_id"]) if order["assigned_broker_id"] else None
    if broker is not None and user_id in (broker["id"], broker["broker_code"]):
        review["is_segregation_violation"] = True
        db.touch(review)
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "QCReviewer identity coincides with the assigned broker",
            403,
        )

    # Priority 18: verdict must target the latest cycle
    if review["cycle_index"] != _latest_cycle_index(order_id):
        raise ApiError(ERR_QC_CYCLE_STALE, "Verdict targets a QC cycle that is not the latest", 409)

    # Priority 29: body validation
    b = body()
    verdict = req_enum(b, "verdict", VERDICTS)
    defects_found = req_int(b, "defects_found", min_v=0)
    notes = req_str(b, "notes", allow_empty=True)
    if verdict == "APPROVE" and defects_found != 0:
        raise ApiError(ERR_INVALID_REQUEST, "APPROVE requires defects_found == 0", 400)
    if verdict == "REVISE" and defects_found < 1:
        raise ApiError(ERR_INVALID_REQUEST, "REVISE requires defects_found >= 1", 400)
    if verdict == "REJECT" and defects_found < 3:
        raise ApiError(ERR_INVALID_REQUEST, "REJECT requires defects_found >= 3", 400)

    now = db.logical_now()
    review["verdict"] = verdict
    review["defects_found"] = defects_found
    review["notes"] = notes
    review["reviewed_at"] = now
    db.touch(review)

    broker_id = order["assigned_broker_id"]

    if verdict == "APPROVE":
        order["fulfillment_status"] = "ACCEPTED"
    elif verdict == "REVISE":
        revision = db.stamp_new_append_only({
            "id": db.new_id(),
            "order_id": order_id,
            "qc_review_id": review["id"],
            "cycle_index": review["cycle_index"],
            "reason": notes,
            "due_at": now + timedelta(hours=REVISION_WINDOW_HOURS),
            "resolved_at": None,
            "outcome": "OPEN",
        })
        db.revision_requests[revision["id"]] = revision
        order["revision_count"] = order["revision_count"] + 1
        order["fulfillment_status"] = "REVISION_REQUESTED"
    else:  # REJECT
        order["fulfillment_status"] = "REJECTED"
        # Cancel DRAFT fee lines; CONFIRMED lines remain for audit
        for fee in db.fee_lines.values():
            if fee["order_id"] == order_id and fee["status"] == "DRAFT":
                fee["status"] = "CANCELLED"
                db.touch(fee)

    db.touch(order)
    if broker_id is not None:
        recompute_composite_score(broker_id)
    return success_object(ser_qc_review(review))


# ---------------------------------------------------------------------------
# Revision requests
# ---------------------------------------------------------------------------

@bp.get("/bpo/valuation-orders/<order_id>/revisions")
@allowed("QCReviewer", "OperationsManager", "Broker", "PlatformAdmin")
def list_order_revisions(user_id, role, order_id):
    get_order_or_404(order_id)
    records = [r for r in db.revision_requests.values() if r["order_id"] == order_id]
    outcome = request.args.get("outcome")
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    items, limit, offset, total = sort_and_page(records, ser_revision_request)
    return success_list(items, limit, offset, total)


@bp.post("/bpo/valuation-orders/<order_id>/revision/<rev_id>/resubmit")
@allowed("Broker")
def resubmit_revision(user_id, role, order_id, rev_id):
    order = get_order_or_404(order_id)
    rev = _get_revision_or_404(order_id, rev_id)

    # Priority 5: state legality
    if order["fulfillment_status"] != "REVISION_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']}, expected REVISION_REQUESTED", 409)
    # Priority 19: revision must be OPEN
    if rev["outcome"] != "OPEN":
        raise ApiError(ERR_REVISION_NOT_OPEN, f"Revision request is {rev['outcome']}, expected OPEN", 409)
    # Priority 30: ownership
    if user_id != order["assigned_broker_id"]:
        raise ApiError(ERR_FORBIDDEN, "Only the assigned broker may resubmit this revision", 403)

    now = db.logical_now()
    rev["resolved_at"] = now
    rev["outcome"] = "RESOLVED_ON_TIME" if now <= rev["due_at"] else "RESOLVED_LATE"
    order["fulfillment_status"] = "REPORT_SUBMITTED"
    db.touch(order)
    if rev["outcome"] == "RESOLVED_LATE" and order["assigned_broker_id"] is not None:
        recompute_composite_score(order["assigned_broker_id"])
    return success_object(ser_revision_request(rev))

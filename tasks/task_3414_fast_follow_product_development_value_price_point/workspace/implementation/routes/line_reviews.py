"""Line reviews (PRD 3.7): half-open submission windows [start, end),
non-overlapping per partner; the lifecycle SCHEDULED -> SUBMISSION_OPEN ->
REVIEWING -> DECIDED -> PLANOGRAM_LOCKED is clock-gated; CANCELLED withdraws
PROPOSED slots and releases COMMITTED ones.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, require_role
from core.constants import ROLE_RETAIL_PLANNER
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, req_dt, req_enum, req_str
from services import cascade

bp = Blueprint("line_reviews", __name__)

STATUSES = (
    "SCHEDULED",
    "SUBMISSION_OPEN",
    "REVIEWING",
    "DECIDED",
    "PLANOGRAM_LOCKED",
    "CANCELLED",
)


@bp.post("/line-reviews")
def create_line_review():
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    partner_id = req_str(body, "retail_partner_id")
    season = req_str(body, "season")
    window_start = req_dt(body, "submission_window_start")
    window_end = req_dt(body, "submission_window_end")
    review_date = req_dt(body, "review_date")
    if partner_id not in store.retail_partners:
        raise not_found("ERR_RETAIL_PARTNER_NOT_FOUND", "retail partner not found")
    if not (window_end > window_start) or not (review_date >= window_end):
        raise err(
            "ERR_INVALID_DATE_RANGE",
            "submission_window_end must be after submission_window_start and "
            "review_date must be on or after submission_window_end",
        )
    # Half-open window non-overlap across the partner's non-CANCELLED reviews;
    # adjacency (one window's start equal to another's end) is allowed.
    for other in store.line_reviews.values():
        if other["retail_partner_id"] != partner_id or other["status"] == "CANCELLED":
            continue
        if window_start < other["submission_window_end"] and other[
            "submission_window_start"
        ] < window_end:
            raise err(
                "ERR_WINDOW_OVERLAP",
                "the submission window overlaps another review of this partner",
            )
    rec = new_record(
        {
            "retail_partner_id": partner_id,
            "season": season,
            "submission_window_start": window_start,
            "submission_window_end": window_end,
            "review_date": review_date,
            "status": "SCHEDULED",
        }
    )
    store.line_reviews[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/line-reviews")
def list_line_reviews():
    authenticate()
    return list_response(
        store.line_reviews.values(),
        {"retail_partner_id": "retail_partner_id", "status": "status"},
        pub,
    )


@bp.get("/line-reviews/<rid>")
def get_line_review(rid):
    authenticate()
    rec = store.line_reviews.get(rid)
    if rec is None:
        raise not_found("ERR_LINE_REVIEW_NOT_FOUND", "line review not found")
    return success_object(pub(rec))


@bp.patch("/line-reviews/<rid>")
def patch_line_review(rid):
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.line_reviews.get(rid)
    if rec is None:
        raise not_found("ERR_LINE_REVIEW_NOT_FOUND", "line review not found")
    if target is None:
        return success_object(pub(rec))
    current = rec["status"]
    now = clock.now()
    if target == "SUBMISSION_OPEN" and current == "SCHEDULED":
        if not (rec["submission_window_start"] <= now < rec["submission_window_end"]):
            raise err(
                "ERR_SUBMISSION_WINDOW_CLOSED",
                "the logical clock is not inside the submission window",
            )
        rec["status"] = "SUBMISSION_OPEN"
    elif target == "REVIEWING" and current == "SUBMISSION_OPEN":
        if not (now >= rec["submission_window_end"]):
            raise err(
                "ERR_SUBMISSION_WINDOW_CLOSED",
                "the submission window has not ended yet",
            )
        rec["status"] = "REVIEWING"
    elif target == "DECIDED" and current == "REVIEWING":
        if not (now >= rec["review_date"]):
            raise err(
                "ERR_SUBMISSION_WINDOW_CLOSED", "the review date has not been reached"
            )
        rec["status"] = "DECIDED"
    elif target == "PLANOGRAM_LOCKED" and current == "DECIDED":
        if any(
            s["line_review_id"] == rec["id"] and s["status"] == "PROPOSED"
            for s in store.planogram_slots.values()
        ):
            raise err(
                "ERR_UNRESOLVED_SLOTS",
                "PROPOSED planogram slots remain on this review",
            )
        rec["status"] = "PLANOGRAM_LOCKED"
    elif target == "CANCELLED" and current in (
        "SCHEDULED",
        "SUBMISSION_OPEN",
        "REVIEWING",
        "DECIDED",
    ):
        rec["status"] = "CANCELLED"
        for slot in store.planogram_slots.values():
            if slot["line_review_id"] != rec["id"]:
                continue
            if slot["status"] == "PROPOSED":
                slot["status"] = "WITHDRAWN"
                touch(slot)
            elif slot["status"] == "COMMITTED":
                cascade.release_slot(slot)
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a line review from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))

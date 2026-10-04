"""Planogram slots (PRD 3.7): proposed inside an open submission window with
OCC on the line review; occupancy is a CLOSED interval with a 14-day reset
buffer per (partner, category, position_code); commit is capacity-checked.
"""
from datetime import timedelta

from flask import Blueprint

from core import clock
from core.auth import authenticate, require_role
from core.constants import RESET_GAP_DAYS, ROLE_RETAIL_PLANNER
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, req_dt, req_enum, req_int, req_str
from services import cascade

bp = Blueprint("slots", __name__)

STATUSES = ("PROPOSED", "COMMITTED", "ACTIVE", "VACATED", "RELEASED", "WITHDRAWN")
_OCCUPYING = ("PROPOSED", "COMMITTED", "ACTIVE")


def _occupancy_conflict(partner_id, category, position_code, start, end):
    """Closed intervals with a RESET_GAP_DAYS buffer: the new occupancy must
    start at least 14 days after the existing one ends, or end at least 14
    days before it starts; a gap of exactly 14 days is allowed."""
    gap = timedelta(days=RESET_GAP_DAYS)
    for other in cascade.partner_slots(partner_id):
        if other["category"] != category or other["position_code"] != position_code:
            continue
        if other["status"] not in _OCCUPYING:
            continue
        if start >= other["occupancy_end"] + gap:
            continue
        if end <= other["occupancy_start"] - gap:
            continue
        return True
    return False


@bp.post("/planogram-slots")
def create_slot():
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    line_review_id = req_str(body, "line_review_id")
    product_id = req_str(body, "product_id")
    category = req_str(body, "category")
    position_code = req_str(body, "position_code")
    facings = req_int(body, "facings", minimum=1)
    occupancy_start = req_dt(body, "occupancy_start")
    occupancy_end = req_dt(body, "occupancy_end")
    expected_version = req_int(body, "expected_line_review_version")

    review = store.line_reviews.get(line_review_id)
    if review is None:
        raise not_found("ERR_LINE_REVIEW_NOT_FOUND", "line review not found")
    product = store.products.get(product_id)
    if product is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    if expected_version != review["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_line_review_version does not match the review's current "
            "version",
        )
    if review["status"] != "SUBMISSION_OPEN":
        raise err(
            "ERR_INVALID_STATE",
            "the line review is not in SUBMISSION_OPEN status",
        )
    if product["status"] != "LAUNCH_READY":
        raise err(
            "ERR_PRODUCT_NOT_LAUNCH_READY", "the product is not LAUNCH_READY"
        )
    now = clock.now()
    if not (review["submission_window_start"] <= now < review["submission_window_end"]):
        raise err(
            "ERR_SUBMISSION_WINDOW_CLOSED",
            "the logical clock is not inside the submission window",
        )
    if occupancy_end < occupancy_start:
        raise err(
            "ERR_INVALID_DATE_RANGE",
            "occupancy_end must not precede occupancy_start",
        )
    partner = store.retail_partners.get(review["retail_partner_id"])
    if _occupancy_conflict(
        review["retail_partner_id"], category, position_code, occupancy_start, occupancy_end
    ):
        raise err(
            "ERR_OCCUPANCY_CONFLICT",
            "the occupancy collides with another slot on this shelf position",
        )
    if partner is None or category not in partner["category_capacities"]:
        raise err(
            "ERR_UNKNOWN_CATEGORY",
            "the category is not a key of the partner's category_capacities",
        )
    rec = new_record(
        {
            "line_review_id": line_review_id,
            "product_id": product_id,
            "category": category,
            "position_code": position_code,
            "facings": facings,
            "occupancy_start": occupancy_start,
            "occupancy_end": occupancy_end,
            "status": "PROPOSED",
            "committed_at": None,
        }
    )
    store.planogram_slots[rec["id"]] = rec
    # A successful creation advances the review's version (OCC).
    touch(review)
    return success_object(pub(rec), code=201)


@bp.get("/planogram-slots")
def list_slots():
    authenticate()
    return list_response(
        store.planogram_slots.values(),
        {
            "line_review_id": "line_review_id",
            "product_id": "product_id",
            "status": "status",
            "category": "category",
        },
        pub,
    )


@bp.get("/planogram-slots/<rid>")
def get_slot(rid):
    authenticate()
    rec = store.planogram_slots.get(rid)
    if rec is None:
        raise not_found("ERR_PLANOGRAM_SLOT_NOT_FOUND", "planogram slot not found")
    return success_object(pub(rec))


@bp.patch("/planogram-slots/<rid>")
def patch_slot(rid):
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.planogram_slots.get(rid)
    if rec is None:
        raise not_found("ERR_PLANOGRAM_SLOT_NOT_FOUND", "planogram slot not found")
    if target is None:
        return success_object(pub(rec))
    current = rec["status"]
    if target == "COMMITTED" and current == "PROPOSED":
        review = store.line_reviews.get(rec["line_review_id"])
        if review is None or review["status"] != "DECIDED":
            raise err(
                "ERR_INVALID_STATE", "the line review is not in DECIDED status"
            )
        partner = store.retail_partners.get(review["retail_partner_id"])
        capacity = partner["category_capacities"].get(rec["category"], 0)
        if (
            cascade.committed_facings(review["retail_partner_id"], rec["category"])
            + rec["facings"]
            > capacity
        ):
            raise err(
                "ERR_CAPACITY_EXCEEDED",
                "committing this slot would exceed the category's facing capacity",
            )
        rec["committed_at"] = clock.now()
        rec["status"] = "COMMITTED"
    elif target == "WITHDRAWN" and current == "PROPOSED":
        rec["status"] = "WITHDRAWN"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a planogram slot from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))

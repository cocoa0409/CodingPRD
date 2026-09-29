"""Trade promotions (PRD 3.4): closed-inclusive month windows."""
from flask import Blueprint

from auth import (ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                  ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  endpoint, find_or_404)
from envelope import respond_list, respond_object
from errors import ApiError, bad_request
from store import new_row, ordered, public, public_all, store, touch
from util import clock
from validators import (get_body, paginate, pagination, query_enum, query_str,
                        req_month, req_number, req_string)

bp = Blueprint("promotions", __name__)

READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]
PROMOTION_STATUSES = ("DRAFT", "APPROVED", "CANCELLED_RUNOUT")


@bp.post("/sop/promotions")
@endpoint([ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER])
def create_promotion():
    body = get_body()
    item_id = req_string(body, "item_id")
    customer_id = req_string(body, "customer_id")
    start_month = req_month(body, "start_month")
    end_month = req_month(body, "end_month")
    if end_month < start_month:
        raise bad_request("end_month may not precede start_month")
    lift_pct = req_number(body, "lift_pct", exclusive_min=0, maximum=300)
    cannibalization_pct = req_number(body, "cannibalization_pct", minimum=0,
                                     maximum=100)

    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")
    customer = find_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")

    row = new_row()
    row.update({
        "item_id": item["id"],
        "customer_id": customer["id"],
        "start_month": start_month,
        "end_month": end_month,
        "lift_pct": lift_pct,
        "cannibalization_pct": cannibalization_pct,
        "status": "DRAFT",
    })
    store.promotions[row["id"]] = row
    return respond_object(public(row), 201)


@bp.post("/sop/promotions/<promotion_id>/approve")
@endpoint([ROLE_DEMAND_REVIEW_LEAD])
def approve_promotion(promotion_id):
    promotion = find_or_404("promotions", promotion_id, "ERR_PROMOTION_NOT_FOUND")

    if promotion["status"] != "DRAFT":
        raise ApiError("ERR_PROMOTION_NOT_APPROVABLE",
                       "Only a DRAFT promotion may be approved")

    item = store.items.get(promotion["item_id"])
    if item is None or item["lifecycle_state"] not in ("RAMP", "MATURE"):
        raise ApiError("ERR_ITEM_NOT_PROMOTABLE",
                       "The promoted item is not sellable")

    for other in ordered(store.promotions.values()):
        if (other["id"] != promotion["id"]
                and other["status"] == "APPROVED"
                and other["item_id"] == promotion["item_id"]
                and other["customer_id"] == promotion["customer_id"]
                and other["start_month"] <= promotion["end_month"]
                and promotion["start_month"] <= other["end_month"]):
            raise ApiError("ERR_PROMOTION_WINDOW_OVERLAP",
                           "The month window overlaps an approved promotion")

    if promotion["start_month"] <= clock.now_month():
        raise ApiError("ERR_PROMOTION_HORIZON_FROZEN",
                       "start_month must be strictly later than the current month")

    promotion["status"] = "APPROVED"
    touch(promotion)
    return respond_object(public(promotion))


@bp.get("/sop/promotions/<promotion_id>")
@endpoint(READ_ROLES)
def get_promotion(promotion_id):
    row = find_or_404("promotions", promotion_id, "ERR_PROMOTION_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/promotions")
@endpoint(READ_ROLES)
def list_promotions():
    limit, offset = pagination()
    item_id = query_str("item_id")
    customer_id = query_str("customer_id")
    status = query_enum("status", PROMOTION_STATUSES)
    rows = ordered(store.promotions.values())
    if item_id is not None:
        rows = [r for r in rows if r["item_id"] == item_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)

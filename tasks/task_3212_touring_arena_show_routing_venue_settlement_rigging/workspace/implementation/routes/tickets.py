"""TicketScale and ticket-sale endpoints."""
from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import calc
import helpers as H
import ticks

bp = Blueprint("tickets", __name__)


@bp.route("/tours/<tourId>/engagements/<engagementId>/ticket-scales", methods=["POST"])
@require_roles("BoxOfficeManager")
def create_scale(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    data = H.body()
    H.require_fields(data, ["tier_label", "base_price_cents", "seats_allocated",
                            "tier_rank", "on_sale_at"])
    s = base_fields()
    s.update({
        "engagement_id": e["id"],
        "tier_label": H.req_str(data, "tier_label"),
        "base_price_cents": H.req_int(data, "base_price_cents"),
        "seats_allocated": H.req_int(data, "seats_allocated"),
        "seats_sold": 0,
        "tier_rank": H.req_int(data, "tier_rank"),
        "on_sale_at": H.req_dt(data, "on_sale_at"),
        "is_family_pack": H.opt_bool(data, "is_family_pack", False),
        "is_group_sales_only": H.opt_bool(data, "is_group_sales_only", False),
        "min_group_size": H.opt_int(data, "min_group_size", 1),
    })
    db.ticket_scales[s["id"]] = s
    return success(s, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/ticket-scales", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_scales(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    items = [s for s in db.ticket_scales.values() if s["engagement_id"] == engagementId]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>/ticket-scales/<scaleId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_scale(tourId, engagementId, scaleId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_ticket_scale(engagementId, scaleId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/ticket-sales", methods=["POST"])
@require_roles("BoxOfficeManager")
def create_sale(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    data = H.body()
    scale_id = data.get("ticket_scale_id")
    if scale_id is not None:
        H.get_ticket_scale(e["id"], scale_id)
    H.require_fields(data, ["ticket_scale_id", "quantity"])
    s = H.get_ticket_scale(e["id"], scale_id)
    qty = H.req_int(data, "quantity")
    if qty <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be positive")
    if now() < s["on_sale_at"]:
        raise err("ERR_NOT_ON_SALE_YET", "Tier is not on sale yet")
    if s["is_group_sales_only"] and qty < s["min_group_size"]:
        raise err("ERR_GROUP_MIN_NOT_MET",
                  "quantity %s < min_group_size %s" % (qty, s["min_group_size"]))
    remaining = s["seats_allocated"] - s["seats_sold"]
    if qty > remaining:
        raise err("ERR_INSUFFICIENT_SEATS",
                  "Only %s seats remain in tier" % remaining)
    if s["is_family_pack"]:
        total = calc.family_pack_total(s["base_price_cents"], qty)
    else:
        total = s["base_price_cents"] * qty
    s["seats_sold"] += qty
    touch(s)
    sale = base_fields()
    sale.update({
        "ticket_scale_id": s["id"],
        "engagement_id": e["id"],
        "quantity": qty,
        "total_cents": total,
    })
    db.ticket_sales[sale["id"]] = sale
    return success({
        "sale_id": sale["id"],
        "total_cents": total,
        "ticket_scale_id": s["id"],
        "quantity": qty,
    }, 201)

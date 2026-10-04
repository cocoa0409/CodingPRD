"""ConversionOrder endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    ERR_CONVERSION_ORDER_NOT_FOUND, ERR_FILM_NOT_FOUND, ERR_INVALID_STATE,
    ERR_FILM_NOT_ANNOUNCED, ERR_POST_SCHEDULE_OVERLAP, ERR_POST_NOT_ELAPSED,
    ERR_FILMMAKER_SIGNOFF_MISSING, ERR_MASTER_URL_REQUIRED, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_enum, opt_bool, opt_str, parse_pagination,
    paginate, success_object, success_list, stamp_new, touch, sort_by_created,
    parse_iso_datetime, iso_format,
)
from domain import serialize_conversion_order, cancel_conversion_order_cascade
from calc import conversion_post_cost_estimate

bp = Blueprint("conversion_orders", __name__)

VALID_FORMATS = {"PREMIUM_2D", "PREMIUM_3D", "PREMIUM_70MM"}


def get_order_or_404(order_id):
    o = db.conversion_orders.get(order_id)
    if o is None:
        raise not_found(ERR_CONVERSION_ORDER_NOT_FOUND, f"Conversion order {order_id} not found")
    return o


@bp.post("/v1/conversion-orders")
def create_order():
    require_role("StudioRelationshipManager")
    body = get_body()
    studio_film_id = req_str(body, "studio_film_id")
    target_format = req_enum(body, "target_format", VALID_FORMATS)
    start = parse_iso_datetime(body.get("scheduled_post_start_date"), "scheduled_post_start_date")
    end = parse_iso_datetime(body.get("scheduled_post_end_date"), "scheduled_post_end_date")
    filmmaker_approval_required = opt_bool(body, "filmmaker_approval_required", False)

    film = db.films.get(studio_film_id)
    if film is None:
        raise not_found(ERR_FILM_NOT_FOUND, f"Film {studio_film_id} not found")

    cost = conversion_post_cost_estimate(target_format, film["runtime_minutes"])

    order = {
        "studio_film_id": studio_film_id,
        "target_format": target_format,
        "scheduled_post_start_date": iso_format(start),
        "scheduled_post_end_date": iso_format(end),
        "_scheduled_post_start_dt": start,
        "_scheduled_post_end_dt": end,
        "filmmaker_approval_required": filmmaker_approval_required,
        "filmmaker_signoff": False,
        "delivered_master_url": None,
        "post_cost_estimate_cents": cost,
        "status": "SUBMITTED",
    }
    stamp_new(order)
    db.conversion_orders[order["id"]] = order
    return success_object(serialize_conversion_order(order), 201)


@bp.get("/v1/conversion-orders")
def list_orders():
    require_role("StudioRelationshipManager", "PostProductionScheduler", "QualityAssuranceReviewer")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.conversion_orders.values()))
    studio_film_id = request.args.get("studio_film_id")
    status = request.args.get("status")
    if studio_film_id:
        items = [o for o in items if o.get("studio_film_id") == studio_film_id]
    if status:
        items = [o for o in items if o.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_conversion_order(o) for o in page], total, limit, offset)


@bp.get("/v1/conversion-orders/<order_id>")
def get_order(order_id):
    require_role("StudioRelationshipManager", "PostProductionScheduler", "QualityAssuranceReviewer", "ReleaseScheduler")
    o = get_order_or_404(order_id)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/begin-post")
def begin_post(order_id):
    require_role("PostProductionScheduler")
    o = get_order_or_404(order_id)
    if o.get("status") not in ("SUBMITTED", "REWORK_REQUESTED"):
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot begin post")
    if o.get("status") == "SUBMITTED":
        # Preconditions only apply on SUBMITTED -> IN_POST
        film = db.films.get(o.get("studio_film_id"))
        if film is None or film.get("status") != "ANNOUNCED":
            raise conflict(ERR_FILM_NOT_ANNOUNCED,
                           "Parent film must be ANNOUNCED to begin post")
        # overlap check against other orders on films of the same studio
        studio_id = film.get("studio_id")
        this_start = o["_scheduled_post_start_dt"]
        this_end = o["_scheduled_post_end_dt"]
        for other in db.conversion_orders.values():
            if other["id"] == o["id"]:
                continue
            if other.get("status") not in ("IN_POST", "QC_REVIEW"):
                continue
            other_film = db.films.get(other.get("studio_film_id"))
            if other_film is None or other_film.get("studio_id") != studio_id:
                continue
            o_start = other["_scheduled_post_start_dt"]
            o_end = other["_scheduled_post_end_dt"]
            # Closed-closed with one-day handoff: conflict iff
            # other's end + 1 day > this.start AND this.end + 1 day > other's start
            if (o_end + timedelta(days=1) > this_start) and (this_end + timedelta(days=1) > o_start):
                raise conflict(ERR_POST_SCHEDULE_OVERLAP,
                               "Post window overlaps another conversion on the same studio")
    else:
        # REWORK_REQUESTED -> IN_POST: reset window
        new_end = db.logical_clock + timedelta(days=7)
        o["_scheduled_post_end_dt"] = new_end
        o["scheduled_post_end_date"] = iso_format(new_end)
        o["filmmaker_signoff"] = False
    o["status"] = "IN_POST"
    touch(o)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/submit-for-qc")
def submit_for_qc(order_id):
    require_role("PostProductionScheduler")
    o = get_order_or_404(order_id)
    if o.get("status") != "IN_POST":
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot submit for QC")
    if db.logical_clock < o["_scheduled_post_end_dt"]:
        raise conflict(ERR_POST_NOT_ELAPSED, "Post window has not elapsed")
    o["status"] = "QC_REVIEW"
    touch(o)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/approve-release")
def approve_release(order_id):
    require_role("QualityAssuranceReviewer")
    o = get_order_or_404(order_id)
    if o.get("status") != "QC_REVIEW":
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot be approved")
    body = get_body()
    signoff = body.get("filmmaker_signoff")
    if signoff is not None and not isinstance(signoff, bool):
        raise bad_request(ERR_INVALID_REQUEST, "filmmaker_signoff must be a boolean")
    if o.get("filmmaker_approval_required"):
        if signoff is not True:
            raise conflict(ERR_FILMMAKER_SIGNOFF_MISSING,
                           "filmmaker_signoff=true required when filmmaker_approval_required")
        o["filmmaker_signoff"] = True
    elif signoff is not None:
        o["filmmaker_signoff"] = signoff
    o["status"] = "APPROVED_FOR_RELEASE"
    touch(o)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/request-rework")
def request_rework(order_id):
    require_role("QualityAssuranceReviewer")
    o = get_order_or_404(order_id)
    if o.get("status") != "QC_REVIEW":
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot request rework")
    o["status"] = "REWORK_REQUESTED"
    touch(o)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/deliver")
def deliver(order_id):
    require_role("PostProductionScheduler")
    o = get_order_or_404(order_id)
    if o.get("status") != "APPROVED_FOR_RELEASE":
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot be delivered")
    body = get_body()
    url = body.get("delivered_master_url")
    if not isinstance(url, str) or url == "":
        raise bad_request(ERR_MASTER_URL_REQUIRED, "delivered_master_url is required")
    o["delivered_master_url"] = url
    o["status"] = "DELIVERED"
    touch(o)
    return success_object(serialize_conversion_order(o))


@bp.post("/v1/conversion-orders/<order_id>/cancel")
def cancel(order_id):
    require_role("StudioRelationshipManager")
    o = get_order_or_404(order_id)
    if o.get("status") in ("DELIVERED", "CANCELLED"):
        raise conflict(ERR_INVALID_STATE, f"Order in state {o.get('status')} cannot be cancelled")
    prior = o["status"]
    o["status"] = "CANCELLED"
    touch(o)
    if prior == "APPROVED_FOR_RELEASE":
        cancel_conversion_order_cascade(o)
    return success_object(serialize_conversion_order(o))

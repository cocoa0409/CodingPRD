"""Servicing orders across housing, transportation and volunteer workstreams
(PRD 3.9)."""

from flask import Blueprint

import aggregates
import domain
import resolve
import serialize
from auth import BUREAU_ADMIN, SALES_MANAGER, SERVICES_MANAGER, endpoint
from errors import ApiError, bad_request
from response import created, object_response
from store import db, touch
from validation import (body_json, req_enum, req_instant, req_int, req_ref,
                        strictly_before)

bp = Blueprint("servicing", __name__)


@bp.route("/servicing-orders", methods=["POST"])
@endpoint(SERVICES_MANAGER)
def create_order():
    body = body_json()
    opportunity_id = req_ref(body, "opportunity_id")
    category = req_enum(body, "category", domain.SERVICING_CATEGORIES)
    requested_units = req_int(body, "requested_units", minimum=1)
    window_start = req_instant(body, "window_start")
    window_end = req_instant(body, "window_end")
    strictly_before(window_start, window_end, "window_start", "window_end")
    opportunity = resolve.opportunity(opportunity_id)

    if opportunity["sales_stage"] != "DEFINITE":
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "A servicing order is opened only for a DEFINITE lead.")

    row = db.new_row()
    row.update({
        "opportunity_id": opportunity["id"],
        "category": category,
        "requested_units": requested_units,
        "assigned_units": 0,
        "delivered_units": 0,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
    })
    db.servicing_orders[row["id"]] = row
    return created(serialize.servicing_order(row))


@bp.route("/servicing-orders/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, SERVICES_MANAGER, SALES_MANAGER)
def get_order(row_id):
    return object_response(serialize.servicing_order(resolve.servicing_order(row_id)))


@bp.route("/servicing-orders/<row_id>/schedule", methods=["POST"])
@endpoint(SERVICES_MANAGER)
def schedule(row_id):
    order = resolve.servicing_order(row_id)
    body = body_json()
    assigned_units = req_int(body, "assigned_units", minimum=1)

    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_SERVICING_STATE",
                       "Only a REQUESTED order may be scheduled.")
    if assigned_units > order["requested_units"]:
        raise bad_request(
            "Field 'assigned_units' must be at most the requested units.")

    order["assigned_units"] = assigned_units
    order["status"] = "SCHEDULED"
    touch(order)
    return object_response(serialize.servicing_order(order))


@bp.route("/servicing-orders/<row_id>/deliver", methods=["POST"])
@endpoint(SERVICES_MANAGER)
def deliver(row_id):
    order = resolve.servicing_order(row_id)
    body = body_json()
    delivered_units = req_int(body, "delivered_units", minimum=0)

    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SERVICING_STATE",
                       "Only a SCHEDULED order may be delivered.")
    if delivered_units > order["assigned_units"]:
        raise bad_request(
            "Field 'delivered_units' must be at most the assigned units.")

    order["delivered_units"] = delivered_units
    order["status"] = "DELIVERED"
    touch(order)
    aggregates.bubble_up_serviced(db.opportunities.get(order["opportunity_id"]))
    return object_response(serialize.servicing_order(order))


@bp.route("/servicing-orders/<row_id>/cancel", methods=["POST"])
@endpoint(SERVICES_MANAGER)
def cancel(row_id):
    order = resolve.servicing_order(row_id)
    if order["status"] not in domain.OPEN_SERVICING_STATUSES:
        raise ApiError("ERR_INVALID_SERVICING_STATE",
                       "Only a REQUESTED or SCHEDULED order may be cancelled.")

    # a cancelled order leaves assigned_units and delivered_units as they stand
    order["status"] = "CANCELLED"
    touch(order)
    aggregates.bubble_up_serviced(db.opportunities.get(order["opportunity_id"]))
    return object_response(serialize.servicing_order(order))

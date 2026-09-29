"""Shopper enrollment, ratings, tier scoring and reinstatement (PRD 3.3)."""
from flask import Blueprint

import calc
import derive
import lookup
import serializers
from auth import require_owner, require_roles
from errors import fail
from response import created, ok
from store import base_row, db, touch
from validation import body_json, is_int, opt_int, query_str, req_int, req_str

bp = Blueprint("shoppers", __name__)


def _next_sequence_no(shopper_id):
    highest = 0
    for row in db.shopper_ratings.values():
        if row["shopper_id"] == shopper_id and row["sequence_no"] > highest:
            highest = row["sequence_no"]
    return highest + 1


@bp.post("/shoppers")
def create_shopper():
    require_roles("DispatchAdmin")
    body = body_json()
    display_name = req_str(body, "display_name")
    service_area_code = req_str(body, "service_area_code")
    capacity = req_int(body, "vehicle_capacity_units", minimum=1, maximum=200)
    row = base_row()
    row.update(
        {
            "display_name": display_name,
            "service_area_code": service_area_code,
            "vehicle_capacity_units": capacity,
            "committed_units": 0,
            "completed_batch_count": 0,
            "abandonment_count": 0,
            "status": "ACTIVE",
            "_injected_completed": 0,
            "_injected_abandonments": 0,
            "_delivered_events": 0,
            "_abandon_events": 0,
        }
    )
    db.shoppers[row["id"]] = row
    derive.refresh_shopper(row, bump=False)
    return created(serializers.shopper(row))


@bp.get("/shoppers/<sid>")
def get_shopper(sid):
    require_roles("Shopper", "DispatchAdmin", "CustomerSupport")
    row = lookup.shopper(sid)
    return ok(serializers.shopper(row))


@bp.post("/shoppers/<sid>/ratings")
def create_rating(sid):
    require_roles("Customer")
    shopper = lookup.shopper(sid)
    body = body_json()
    stars = req_int(body, "stars", minimum=1, maximum=5)
    order_id = req_str(body, "order_id")
    order = lookup.order(order_id)
    require_owner(order["customer_id"])
    if order["fulfillment_status"] != "DELIVERED":
        fail("ERR_ORDER_NOT_DELIVERED", "The rated order has not been delivered.")
    for existing in db.shopper_ratings.values():
        if existing["shopper_id"] == shopper["id"] and existing["order_id"] == order["id"]:
            fail("ERR_DUPLICATE_RATING", "This order has already rated this shopper.")
    row = base_row(with_version=False)
    row.update(
        {
            "shopper_id": shopper["id"],
            "order_id": order["id"],
            "stars": stars,
            "sequence_no": _next_sequence_no(shopper["id"]),
        }
    )
    db.shopper_ratings[row["id"]] = row
    derive.refresh_shopper(shopper)
    return created(serializers.shopper_rating(row))


@bp.get("/shopper-ratings/<rid>")
def get_rating(rid):
    require_roles("Shopper", "Customer", "DispatchAdmin", "CustomerSupport")
    row = lookup.rating(rid)
    return ok(serializers.shopper_rating(row))


@bp.get("/shopper-ratings")
def list_ratings():
    require_roles("Shopper", "Customer", "DispatchAdmin", "CustomerSupport")
    shopper_id = query_str("shopper_id")
    order_id = query_str("order_id")

    def keep(row):
        if shopper_id is not None and row["shopper_id"] != shopper_id:
            return False
        if order_id is not None and row["order_id"] != order_id:
            return False
        return True

    return lookup.paged(db.shopper_ratings, serializers.shopper_rating, keep)


@bp.post("/shoppers/<sid>/reinstate")
def reinstate(sid):
    require_roles("DispatchAdmin")
    shopper = lookup.shopper(sid)
    if shopper["status"] != "SUSPENDED_REVIEW":
        fail("ERR_SHOPPER_NOT_SUSPENDED", "The shopper is not under suspension review.")
    if shopper["lifetime_tier_score"] < calc.REINSTATEMENT_MIN_SCORE:
        fail("ERR_REINSTATE_SCORE_TOO_LOW", "The lifetime tier score has not recovered.")
    shopper["_injected_abandonments"] = 0
    shopper["_abandon_events"] = 0
    shopper["status"] = "ACTIVE"
    derive.refresh_shopper(shopper)
    return ok(serializers.shopper(shopper))


@bp.post("/_ratings/backfill")
def backfill_ratings():
    require_roles("DispatchAdmin")
    body = body_json()
    shopper_id = req_str(body, "shopper_id")
    if "stars_sequence" not in body or not isinstance(body["stars_sequence"], list):
        fail("ERR_INVALID_REQUEST", "stars_sequence must be an array of integers.")
    sequence = body["stars_sequence"]
    for value in sequence:
        if not is_int(value) or value < 1 or value > 5:
            fail("ERR_INVALID_REQUEST", "Every element of stars_sequence must be 1 through 5.")
    shopper = lookup.shopper(shopper_id)
    for stars in sequence:
        row = base_row(with_version=False)
        row.update(
            {
                "shopper_id": shopper["id"],
                "order_id": None,
                "stars": stars,
                "sequence_no": _next_sequence_no(shopper["id"]),
            }
        )
        db.shopper_ratings[row["id"]] = row
    derive.refresh_shopper(shopper)
    return ok(serializers.shopper(shopper))


@bp.post("/_shoppers/<sid>/history")
def set_history(sid):
    require_roles("DispatchAdmin")
    shopper = lookup.shopper(sid)
    body = body_json()
    completed = opt_int(body, "completed_batch_count", default=None, minimum=0)
    abandonments = opt_int(body, "abandonment_count", default=None, minimum=0)
    if completed is not None:
        shopper["_injected_completed"] = completed - int(shopper["_delivered_events"])
    if abandonments is not None:
        shopper["_injected_abandonments"] = abandonments - int(shopper["_abandon_events"])
    derive.refresh_shopper(shopper)
    return ok(serializers.shopper(shopper))

"""Donation pickups (PRD 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import authorize, ALL_ROLES, ROLE_DONATION_COORDINATOR

bp = Blueprint("donations", __name__)


def _reference_conventional_price(facility_id):
    """The facility's reference CONVENTIONAL dough type: lowest shelf_life_hours,
    ties broken by earliest DoughType.created_at."""
    candidates = [dt for dt in db.sorted_rows(db.dough_types)
                  if dt["category"] == "CONVENTIONAL"]
    # Dough types are global catalog rows in this deployment; order by the
    # documented tiebreak chain.
    if not candidates:
        raise ApiError("ERR_NOT_FOUND", "No conventional dough type exists.")
    candidates.sort(key=lambda d: (d["shelf_life_hours"], d["_seq"]))
    return Decimal(str(candidates[0]["flat_transfer_price"]))


@bp.route("/dough-ops/cafes/<cafe_id>/donation-pickups", methods=["POST"])
def create_donation_pickup(cafe_id):
    authorize(ROLE_DONATION_COORDINATOR)
    services.get_or_404(db.cafes, cafe_id, "Cafe")
    data = V.body_json(request)
    schedule_id = data.get("schedule_id")
    partner_name = V.req_string(data, "partner_name")
    unsold_conventional = V.req_int(data, "unsold_conventional", minimum=0)
    unsold_artisan = V.req_int(data, "unsold_artisan", minimum=0)
    if not isinstance(schedule_id, str) or schedule_id not in db.cafe_schedules:
        raise ApiError("ERR_NOT_FOUND", "Schedule not found.")
    if db.cafe_schedules[schedule_id]["cafe_id"] != cafe_id:
        raise ApiError("ERR_NOT_FOUND", "Schedule not found under this cafe.")

    row = db.common_fields()
    row.update({
        "cafe_id": cafe_id,
        "schedule_id": schedule_id,
        "partner_name": partner_name,
        "unsold_conventional": unsold_conventional,
        "unsold_artisan": unsold_artisan,
        "credit_amount": None,
        "status": "LOGGED",
    })
    db.donation_pickups[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/cafes/<cafe_id>/donation-pickups", methods=["GET"])
def list_donation_pickups(cafe_id):
    authorize(*ALL_ROLES)
    services.get_or_404(db.cafes, cafe_id, "Cafe")
    schedule_id = request.args.get("schedule_id")
    status = request.args.get("status")
    rows = [r for r in db.donation_pickups.values()
            if r["cafe_id"] == cafe_id
            and (schedule_id is None or r["schedule_id"] == schedule_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/donation-pickups", methods=["GET"])
def list_donation_pickups_flat():
    authorize(*ALL_ROLES)
    cafe_id = request.args.get("cafe_id")
    schedule_id = request.args.get("schedule_id")
    status = request.args.get("status")
    rows = [r for r in db.donation_pickups.values()
            if (cafe_id is None or r["cafe_id"] == cafe_id)
            and (schedule_id is None or r["schedule_id"] == schedule_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/donation-pickups/<pickup_id>", methods=["GET"])
def get_donation_pickup(pickup_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.donation_pickups, pickup_id, "Donation pickup")
    return resp.object_response(resp.serialize(row), 200)


def _get_pickup_under_cafe(cafe_id, pickup_id):
    services.get_or_404(db.cafes, cafe_id, "Cafe")
    pickup = services.get_or_404(db.donation_pickups, pickup_id, "Donation pickup")
    if pickup["cafe_id"] != cafe_id:
        raise ApiError("ERR_NOT_FOUND", "Donation pickup not found under this cafe.")
    return pickup


@bp.route("/dough-ops/cafes/<cafe_id>/donation-pickups/<pickup_id>/confirm", methods=["POST"])
def confirm_donation_pickup(cafe_id, pickup_id):
    authorize(ROLE_DONATION_COORDINATOR)
    cafe = db.cafes[cafe_id] if cafe_id in db.cafes else None
    pickup = _get_pickup_under_cafe(cafe_id, pickup_id)
    if pickup["status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", "Only a LOGGED pickup may be confirmed.")
    schedule = db.cafe_schedules[pickup["schedule_id"]]
    if schedule["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE",
                       "The referenced schedule must be CLOSED before confirmation.")

    units = pickup["unsold_conventional"] + pickup["unsold_artisan"]
    price = _reference_conventional_price(cafe["facility_id"])
    credit = (Decimal(units) * price * services.DONATION_CREDIT_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    pickup["credit_amount"] = float(credit)
    pickup["status"] = "CONFIRMED"
    db.touch(pickup)

    credit_cents = int(credit * 100)
    cafe["credit_balance_cents"] = max(0, cafe["credit_balance_cents"] - credit_cents)
    db.touch(cafe)
    return resp.object_response(resp.serialize(pickup), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/donation-pickups/<pickup_id>/void", methods=["POST"])
def void_donation_pickup(cafe_id, pickup_id):
    authorize(ROLE_DONATION_COORDINATOR)
    pickup = _get_pickup_under_cafe(cafe_id, pickup_id)
    if pickup["status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", "Only a LOGGED pickup may be voided.")
    pickup["status"] = "VOIDED"
    db.touch(pickup)
    return resp.object_response(resp.serialize(pickup), 200)

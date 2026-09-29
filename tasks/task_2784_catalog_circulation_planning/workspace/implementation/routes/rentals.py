"""Prospect list procurement and cooperative modeling."""

from flask import Blueprint

import validate as v
from db import db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, LIST_BROKER, auth
from response import entity_response, list_response
from services import calc, domain
from routes.config import find_season

bp = Blueprint("rentals", __name__)

RENTAL_STATUSES = (
    "REQUESTED",
    "MODELED",
    "ORDERED",
    "DELIVERED",
    "NETTED",
    "CANCELLED",
)
LIVE_RENTAL_STATUSES = ("REQUESTED", "MODELED", "ORDERED", "DELIVERED", "NETTED")


def find_rental(rental_id):
    rental = db.rentals.get(rental_id)
    if rental is None:
        raise ApiError("ERR_RENTAL_NOT_FOUND")
    return rental


@bp.post("/prospect-list-rentals")
def create_rental():
    auth(LIST_BROKER)
    body = v.json_body()

    season_id = body.get("season_id")
    if isinstance(season_id, str) and season_id.strip() != "":
        if season_id not in db.seasons:
            raise ApiError("ERR_SEASON_NOT_FOUND")

    season_id = v.get_id(body, "season_id")
    if season_id not in db.seasons:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    list_source_name = v.get_str(body, "list_source_name", min_len=1)
    requested_gross_names = v.get_int(body, "requested_gross_names", minimum=1)
    cost_per_thousand_cents = v.get_int(body, "cost_per_thousand_cents", minimum=0)
    housefile_overlap_bps = v.get_int(
        body, "housefile_overlap_bps", minimum=0, maximum=10000
    )
    inter_list_overlap_bps = v.get_int(
        body, "inter_list_overlap_bps", minimum=0, maximum=10000
    )

    row = new_row()
    row.update(
        {
            "season_id": season_id,
            "list_source_name": list_source_name,
            "requested_gross_names": requested_gross_names,
            "cost_per_thousand_cents": cost_per_thousand_cents,
            "housefile_overlap_bps": housefile_overlap_bps,
            "inter_list_overlap_bps": inter_list_overlap_bps,
            "coop_model_score": 0,
            "expected_response_rate_bps": 0,
            "gross_names": 0,
            "net_names_delivered": 0,
            "unit_cost_cents_per_name": 0,
            "status": "REQUESTED",
        }
    )
    db.rentals[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/prospect-list-rentals/<rental_id>")
def read_rental(rental_id):
    auth(*ALL_ROLES)
    return entity_response(find_rental(rental_id))


@bp.get("/seasons/<season_id>/prospect-list-rentals")
def list_season_rentals(season_id):
    auth(*ALL_ROLES)
    season = find_season(season_id)
    limit, offset = v.pagination()
    status = v.filter_enum("status", RENTAL_STATUSES)
    matching = [r for r in db.rentals.values() if r["season_id"] == season["id"]]
    if status is not None:
        matching = [r for r in matching if r["status"] == status]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/prospect-list-rentals/<rental_id>/model")
def model_rental(rental_id):
    auth(LIST_BROKER)
    rental = find_rental(rental_id)
    body = v.json_body()
    coop_model_score = v.get_int(body, "coop_model_score", minimum=0, maximum=1000)
    if rental["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_RENTAL_STATE")
    season = db.seasons[rental["season_id"]]
    rental["coop_model_score"] = coop_model_score
    rental["expected_response_rate_bps"] = calc.expected_response_rate_bps(
        season["prospect_base_response_bps"], coop_model_score
    )
    rental["status"] = "MODELED"
    touch(rental)
    return entity_response(rental)


@bp.post("/prospect-list-rentals/<rental_id>/order")
def order_rental(rental_id):
    auth(LIST_BROKER)
    rental = find_rental(rental_id)
    v.json_body()
    if rental["status"] != "MODELED":
        raise ApiError("ERR_INVALID_RENTAL_STATE")
    rental["unit_cost_cents_per_name"] = calc.unit_cost_cents_per_name(
        rental["cost_per_thousand_cents"]
    )
    rental["status"] = "ORDERED"
    touch(rental)
    return entity_response(rental)


@bp.post("/prospect-list-rentals/<rental_id>/deliver")
def deliver_rental(rental_id):
    auth(LIST_BROKER)
    rental = find_rental(rental_id)
    body = v.json_body()
    delivered = v.get_int(body, "delivered_gross_names", minimum=0)
    if rental["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_RENTAL_STATE")
    rental["gross_names"] = delivered
    rental["status"] = "DELIVERED"
    touch(rental)
    return entity_response(rental)


@bp.post("/prospect-list-rentals/<rental_id>/cancel")
def cancel_rental(rental_id):
    auth(LIST_BROKER)
    rental = find_rental(rental_id)
    body = v.json_body()
    v.get_optional_text(body, "reason")
    if rental["status"] not in LIVE_RENTAL_STATUSES:
        raise ApiError("ERR_INVALID_RENTAL_STATE")
    rental["status"] = "CANCELLED"
    domain.run_rental_cancel_cascade(rental)
    touch(rental)
    return entity_response(rental)

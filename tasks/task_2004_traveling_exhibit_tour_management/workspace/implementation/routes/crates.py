"""Crate endpoints (nested under a tour)."""

from flask import Blueprint

import db
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import crate_out
from validate import (json_body, req_str, req_int, get_tour, get_crate,
                      paginate, apply_filters, sorted_created)

bp = Blueprint("crates", __name__)


@bp.route("/tours/<tour_id>/crates", methods=["POST"])
def create_crate(tour_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    data = json_body()
    label = req_str(data, "crate_label")
    if any(c["tour_id"] == tour["id"] and c["crate_label"] == label
           for c in db.crates.values()):
        fail("ERR_INVALID_REQUEST",
             "crate_label must be unique within the tour")
    crate = db.stamp_new({
        "id": db.new_id(),
        "tour_id": tour["id"],
        "crate_label": label,
        "contents_value_cents": req_int(data, "contents_value_cents"),
        "location_status": "AT_ORIGIN",
        "current_stop_id": None,
        "condition_score": None,
    })
    db.crates[crate["id"]] = crate
    return ok_object(crate_out(crate), status=201)


@bp.route("/tours/<tour_id>/crates", methods=["GET"])
def list_crates(tour_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    items = [c for c in db.crates.values() if c["tour_id"] == tour["id"]]
    items = apply_filters(items, [("location_status", "location_status")])
    return paginate([crate_out(c) for c in sorted_created(items)])


@bp.route("/tours/<tour_id>/crates/<crate_id>", methods=["GET"])
def get_one_crate(tour_id, crate_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    return ok_object(crate_out(get_crate(tour, crate_id)))

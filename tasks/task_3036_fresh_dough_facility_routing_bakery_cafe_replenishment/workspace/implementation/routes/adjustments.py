"""Demand adjustments (PRD 3.3)."""

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import authorize, ALL_ROLES, ROLE_FACILITY_PLANNER

bp = Blueprint("adjustments", __name__)


@bp.route("/dough-ops/demand-adjustments", methods=["POST"])
def create_demand_adjustment():
    authorize(ROLE_FACILITY_PLANNER)
    data = V.body_json(request)
    cafe_id = data.get("cafe_id")
    production_date = V.req_date(data, "production_date")
    reason = V.req_enum(data, "reason", ("WEATHER", "EVENT"))
    delta = V.req_int(data, "demand_delta_pct", minimum=-80, maximum=100)
    if not isinstance(cafe_id, str) or cafe_id not in db.cafes:
        raise ApiError("ERR_NOT_FOUND", "Cafe not found.")

    # At most one ACTIVE adjustment per (cafe, production_date): the older one
    # flips to SUPERSEDED with superseded_by_id pointing at the newcomer.
    prior = services.active_adjustment(cafe_id, production_date)

    row = db.common_fields()
    row.update({
        "cafe_id": cafe_id,
        "production_date": production_date,
        "reason": reason,
        "demand_delta_pct": delta,
        "status": "ACTIVE",
        "superseded_by_id": None,
    })
    db.demand_adjustments[row["id"]] = row

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = row["id"]
        db.touch(prior)

    services.recompute_affected_orders(cafe_id, production_date)
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/demand-adjustments", methods=["GET"])
def list_demand_adjustments():
    authorize(*ALL_ROLES)
    cafe_id = request.args.get("cafe_id")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    superseded_by_id = request.args.get("superseded_by_id")
    rows = [r for r in db.demand_adjustments.values()
            if (cafe_id is None or r["cafe_id"] == cafe_id)
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)
            and (superseded_by_id is None or r["superseded_by_id"] == superseded_by_id)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/demand-adjustments/<adjustment_id>", methods=["GET"])
def get_demand_adjustment(adjustment_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.demand_adjustments, adjustment_id, "Demand adjustment")
    return resp.object_response(resp.serialize(row), 200)


@bp.route("/dough-ops/demand-adjustments/<adjustment_id>/rescind", methods=["POST"])
def rescind_demand_adjustment(adjustment_id):
    authorize(ROLE_FACILITY_PLANNER)
    row = services.get_or_404(db.demand_adjustments, adjustment_id, "Demand adjustment")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE adjustment may be rescinded.")
    row["status"] = "RESCINDED"
    db.touch(row)
    # Affected orders revert to adjusted_quantity == quantity.
    services.recompute_affected_orders(row["cafe_id"], row["production_date"])
    return resp.object_response(resp.serialize(row), 200)

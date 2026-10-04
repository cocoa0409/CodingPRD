"""Tank endpoints: create, get, list, commission."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import serializers
import store
from errors import (
    ApiError,
    ERR_COMMITMENT_NOT_SECURED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_TANK_ALREADY_EXISTS,
    ERR_TANK_UNDER_CONSTRUCTION,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_CAPACITY_PLANNER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_int,
    pagination_args,
)

bp = Blueprint("tanks", __name__)


@bp.route("/glass/tanks", methods=["POST"])
def create_tank():
    authenticate({ROLE_CAPACITY_PLANNER})
    body = get_body()
    commitment_id = as_str(req_field(body, "commitment_id"), "commitment_id")
    capacity = as_int(req_field(body, "capacity_units_per_day"), "capacity_units_per_day")
    if capacity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "capacity_units_per_day must be positive")
    commitment = store.commitments.get(commitment_id)
    if commitment is None:
        raise ApiError(ERR_NOT_FOUND, "Commitment not found")
    # Priority 20: capacity investment is gated on a SECURED commitment.
    if commitment["status"] != "SECURED":
        raise ApiError(ERR_COMMITMENT_NOT_SECURED, "Commitment is not SECURED")
    # Priority 21: a commitment funds at most one tank.
    for t in store.tanks.values():
        if t["commitment_id"] == commitment["id"]:
            raise ApiError(ERR_TANK_ALREADY_EXISTS, "Commitment already funds a tank")
    tank = store.base_fields()
    tank.update(
        {
            "commitment_id": commitment["id"],
            "capacity_units_per_day": capacity,
            "status": "CONSTRUCTING",
            "construction_ready_date": tank["created_at"]
            + timedelta(days=C.TANK_CONSTRUCTION_DAYS),
        }
    )
    store.tanks[tank["id"]] = tank
    return success_object(serializers.tank(tank), status=201)


@bp.route("/glass/tanks/<tankId>", methods=["GET"])
def get_tank(tankId):
    authenticate(ALL_ROLES)
    tank = store.tanks.get(tankId)
    if tank is None:
        raise ApiError(ERR_NOT_FOUND, "Tank not found")
    return success_object(serializers.tank(tank))


@bp.route("/glass/tanks", methods=["GET"])
def list_tanks():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_commitment = request.args.get("commitment_id")
    f_status = request.args.get("status")
    items = list(store.tanks.values())
    if f_commitment is not None:
        items = [t for t in items if t["commitment_id"] == f_commitment]
    if f_status is not None:
        items = [t for t in items if t["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.tank(t) for t in page], limit, offset, total)


@bp.route("/glass/tanks/<tankId>/commission", methods=["POST"])
def commission_tank(tankId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    tank = store.tanks.get(tankId)
    if tank is None:
        raise ApiError(ERR_NOT_FOUND, "Tank not found")
    if tank["status"] != "CONSTRUCTING":
        raise ApiError(ERR_INVALID_STATE, "commission requires CONSTRUCTING")
    if clock.now() < tank["construction_ready_date"]:
        raise ApiError(ERR_TANK_UNDER_CONSTRUCTION, "Tank is still under construction")
    tank["status"] = "COMMISSIONED"
    store.touch(tank)
    return success_object(serializers.tank(tank))

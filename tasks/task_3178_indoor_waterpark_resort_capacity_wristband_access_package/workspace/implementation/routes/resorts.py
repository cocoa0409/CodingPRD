"""Resort property endpoints."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common

bp = Blueprint("resorts", __name__)

DECLARED_CREATE = (
    "name",
    "park_capacity_occupancy_units",
    "day_pass_cap_units",
    "arcade_credit_rate_cents_per_unit",
)
DECLARED_UPDATE = (
    "expected_resort_version",
    "park_capacity_occupancy_units",
    "day_pass_cap_units",
    "arcade_credit_rate_cents_per_unit",
)
DECLARED_MANAGERS = ("async_role", "async_name")


def serialise_resort(resort):
    out = dict(resort)
    out["day_pass_reserved_units"] = common.day_pass_reserved_units(
        resort["id"], common.current_service_date(resort["id"])
    )
    return out


@bp.route("/resorts", methods=["POST"])
def create_resort():
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "platform_ops")

    name = v.required_str(payload, "name")
    capacity = v.required_int(payload, "park_capacity_occupancy_units")
    v.in_range(capacity, "park_capacity_occupancy_units", low=1)
    day_cap = v.required_int(payload, "day_pass_cap_units")
    v.in_range(day_cap, "day_pass_cap_units", low=0)
    if day_cap > capacity:
        raise errors.invalid_request(
            "day_pass_cap_units may not exceed park_capacity_occupancy_units."
        )
    rate = v.required_int(payload, "arcade_credit_rate_cents_per_unit")

    resort_id = _db.new_id()
    now = _db.now_iso()
    resort = {
        "id": resort_id,
        "name": name,
        "park_capacity_occupancy_units": capacity,
        "day_pass_cap_units": day_cap,
        "arcade_credit_rate_cents_per_unit": rate,
        "manager_override_used": False,
        "pool_posture": "OPEN",
        "ops_run_index": 0,
        "managers": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    _db.store().resorts[resort_id] = resort
    return jsonify(response.success(serialise_resort(resort))), 201


@bp.route("/resorts/<resort_id>", methods=["GET"])
def get_resort(resort_id):
    middleware.authenticate()
    resort = common.get_resort(resort_id)
    return jsonify(response.success(serialise_resort(resort))), 200


@bp.route("/resorts/<resort_id>", methods=["PUT"])
def update_resort(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_UPDATE)
    middleware.require(caller, "platform_ops")
    resort = common.get_resort(resort_id)

    expected = v.required_int(payload, "expected_resort_version")
    if expected != resort["version"]:
        raise errors.stale_resort_version()

    capacity = v.optional_int(payload, "park_capacity_occupancy_units")
    if capacity is not None:
        v.in_range(capacity, "park_capacity_occupancy_units", low=1)
    day_cap = v.optional_int(payload, "day_pass_cap_units")
    if day_cap is not None:
        v.in_range(day_cap, "day_pass_cap_units", low=0)
    rate = v.optional_int(payload, "arcade_credit_rate_cents_per_unit")

    effective_capacity = capacity if capacity is not None else resort["park_capacity_occupancy_units"]
    effective_day_cap = day_cap if day_cap is not None else resort["day_pass_cap_units"]
    if effective_day_cap > effective_capacity:
        raise errors.invalid_request(
            "day_pass_cap_units may not exceed park_capacity_occupancy_units."
        )

    if capacity is not None:
        resort["park_capacity_occupancy_units"] = capacity
    if day_cap is not None:
        resort["day_pass_cap_units"] = day_cap
    if rate is not None:
        resort["arcade_credit_rate_cents_per_unit"] = rate
    common.touch(resort)
    return jsonify(response.success(serialise_resort(resort))), 200


@bp.route("/resorts/<resort_id>/managers", methods=["POST"])
def add_manager(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_MANAGERS)
    middleware.require(caller, "platform_ops")
    resort = common.get_resort(resort_id)

    role = v.required_str(payload, "async_role")
    name = v.required_str(payload, "async_name")
    resort["managers"] = list(resort.get("managers") or []) + ["%s:%s" % (role, name)]
    common.touch(resort)
    return jsonify(response.success(serialise_resort(resort))), 201


@bp.route("/resorts/<resort_id>/capacity", methods=["GET"])
def capacity(resort_id):
    caller = middleware.authenticate()
    middleware.require(
        caller, "platform_ops", "FrontDesk", "AquaticsManager", "GateAttendant", "Group"
    )
    common.get_resort(resort_id)
    service_date = v.query_service_date()
    ledger = common.capacity_ledger(resort_id, service_date)
    return jsonify(response.success(ledger)), 200


@bp.route("/resorts/<resort_id>/attendance-capacity", methods=["GET"])
def attendance_capacity(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "AquaticsManager", "GateAttendant")
    common.get_resort(resort_id)
    service_date = v.query_service_date()
    ledger = common.capacity_ledger(resort_id, service_date)
    return jsonify(response.success({
        "service_date": ledger["service_date"],
        "occupancy_units": ledger["occupancy_units"],
        "capacity_remaining_units": ledger["capacity_remaining_units"],
    })), 200
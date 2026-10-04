"""Day pass endpoints: sale against the walk-in allocation, voiding."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("day_passes", __name__)

DECLARED_CREATE = ("service_date", "units_requested", "expected_resort_version")


def horizon_check(resort_id, service_date):
    from datetime import timedelta
    from db import date_from_service_date
    current = date_from_service_date(common.current_service_date(resort_id))
    requested = date_from_service_date(service_date)
    if requested > current + timedelta(days=common.SERVICE_DATE_HORIZON_DAYS):
        raise errors.service_date_out_of_range()


@bp.route("/resorts/<resort_id>/day-passes", methods=["POST"])
def create_day_pass(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "platform_ops", "FrontDesk")
    resort = common.get_resort(resort_id)

    service_date = v.required_service_date(payload, "service_date")
    units = v.required_int(payload, "units_requested")
    v.in_range(units, "units_requested", low=1)
    expected = v.required_int(payload, "expected_resort_version")

    horizon_check(resort_id, service_date)

    if expected != resort["version"]:
        raise errors.stale_resort_version()

    already = common.day_pass_reserved_units(resort_id, service_date)
    if already + units > resort["day_pass_cap_units"]:
        raise errors.day_pass_cap_exceeded()

    day_pass = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "service_date": service_date,
        "units_requested": units,
        "day_pass_status": "RESERVED",
        "price_total_cents": engine.day_pass_price(units),
    }
    _db.store().day_passes[day_pass["id"]] = day_pass
    common.touch(resort)
    return jsonify(response.success(common.serialise("day_pass", day_pass))), 201


@bp.route("/resorts/<resort_id>/day-passes", methods=["GET"])
def list_day_passes(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        d for d in _db.store().day_passes.values() if d.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("day_pass", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/day-passes/<day_pass_id>", methods=["GET"])
def get_day_pass(resort_id, day_pass_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Anonymous")
    common.get_resort(resort_id)
    day_pass = common.fetch("day_pass", day_pass_id, resort_id)
    return jsonify(response.success(common.serialise("day_pass", day_pass))), 200


@bp.route("/resorts/<resort_id>/day-passes/<day_pass_id>/void", methods=["POST"])
def void_day_pass(resort_id, day_pass_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk")
    common.get_resort(resort_id)
    day_pass = common.fetch("day_pass", day_pass_id, resort_id)

    if day_pass["day_pass_status"] != "RESERVED":
        raise errors.invalid_state()

    for band in _db.store().wristbands.values():
        if band.get("holder_type") != "DAY_PASS_GUEST":
            continue
        if band.get("day_pass_id") != day_pass_id:
            continue
        if band.get("wristband_status") in ("ISSUED", "ACTIVE"):
            raise errors.invalid_state("A day pass with live wristbands cannot be voided.")

    day_pass["day_pass_status"] = "VOID"
    common.touch(day_pass)
    return jsonify(response.success(common.serialise("day_pass", day_pass))), 200


@bp.route("/resorts/<resort_id>/day-passes/<day_pass_id>/wristbands", methods=["GET"])
def list_day_pass_wristbands(resort_id, day_pass_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Anonymous")
    common.get_resort(resort_id)
    common.fetch("day_pass", day_pass_id, resort_id)
    rows = [
        b for b in _db.store().wristbands.values()
        if b.get("day_pass_id") == day_pass_id and b.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    data = common.serialise_many("wristband", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200
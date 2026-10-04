"""Test-driving capabilities: the logical clock and the deposit gateway."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("testing", __name__)

DECLARED_CLOCK = ("to_iso8601",)
DECLARED_PAYMENT = ("group_booking_id", "outcome")

OUTCOMES = ("ACCEPTED", "DECLINED")


@bp.route("/resorts/<resort_id>/_clock/set_current_utc", methods=["POST"])
def set_current_utc(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CLOCK)
    middleware.require(caller, "platform_ops")
    resort = common.get_resort(resort_id)

    to_iso8601 = v.required_instant(payload, "to_iso8601")
    common.set_clock(resort_id, to_iso8601)

    engine.expire_reservations_for_clock(resort_id)
    engine.expire_wristbands_for_clock(resort_id)
    engine.expire_day_passes_for_clock(resort_id)
    engine.expire_cabana_holds_for_clock(resort_id)
    common.recompute_pool_posture(resort_id)

    common.touch(resort)
    return jsonify(response.success({
        "current_utc": common.clock(resort_id),
        "service_date": common.current_service_date(resort_id),
    })), 200


@bp.route("/resorts/<resort_id>/_payments/simulate", methods=["POST"])
def simulate_payment(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_PAYMENT)
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)

    group_booking_id = v.required_str(payload, "group_booking_id")
    common.fetch("group_booking", group_booking_id, resort_id)
    outcome = v.in_enum(v.required_str(payload, "outcome"), "outcome", OUTCOMES)

    _db.store().gateway_outcomes[group_booking_id] = outcome
    return jsonify(response.success({
        "group_booking_id": group_booking_id,
        "outcome": outcome,
        "accepted": outcome == "ACCEPTED",
    })), 200
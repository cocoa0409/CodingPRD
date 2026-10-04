"""Platform control: logical clock and the operations sweep."""

from flask import request

from constants import parse_instant
from db import set_clock, clock_now
from middleware import roles_required
from response import object_response
from routers import body
from services.scheduling import operations_sweep


def register(app):
    @app.route("/v1/_clock/set_current_utc", methods=["POST"])
    @roles_required("PlatformAdmin")
    def set_current_utc():
        payload = body()
        instant = parse_instant(payload.get("current_utc"), "current_utc")
        set_clock(instant)
        return object_response({"current_utc": clock_now()})

    @app.route("/v1/_ops/sweep", methods=["POST"])
    @roles_required("PlatformAdmin")
    def sweep():
        from db import fmt
        result = operations_sweep()
        return object_response({
            "swept_appointment_ids": result["swept_appointment_ids"],
            "uncovered_load_ids": result["uncovered_load_ids"],
            "suspended_carrier_ids": result["suspended_carrier_ids"],
            "processed_at": fmt(result["processed_at"]),
        })
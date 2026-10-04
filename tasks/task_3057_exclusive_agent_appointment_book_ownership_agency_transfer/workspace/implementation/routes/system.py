"""Administrative and diagnostic endpoints: logical clock, raw-agent seeding,
envelope echo, and the trailing-commission settlement helper."""

from flask import request

import clock
import middleware
import serializers
from errors import ApiError
from money import dec, round_cents
from response import array_response, object_response
from routes import _common as c
from services import calculations as calc
from services import factories, ops
from services import recompute


def register(app):

    @app.route("/agency-network/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        middleware.authorize(request, ("PlatformAdmin",))
        data = c.body()
        to_iso8601 = data.get("to_iso8601")
        if to_iso8601 is None or str(to_iso8601).strip() == "":
            raise ApiError("ERR_INVALID_TIMESTAMP",
                           "to_iso8601 must be an ISO 8601 instant.", 400)
        clock.set_current(to_iso8601)
        ops.on_clock_advanced()
        return object_response({}, 200)

    @app.route("/agency-network/_inject/agent", methods=["POST"])
    def inject_agent():
        middleware.authorize(request, ("PlatformAdmin",))
        data = c.body()
        record = factories.create_agent({
            "full_name": data.get("full_name"),
            "state_code": data.get("state_code"),
            "license_status": data.get("license_status"),
            "is_new_agent": data.get("is_new_agent"),
            "status": data.get("status"),
            "market_need_score": data.get("market_need_score"),
            "license_expiry_date": data.get("license_expiry_date"),
        })
        return object_response(serializers.view_agent(record), 201)

    @app.route("/agency-network/_envelopes/echo", methods=["GET"])
    def envelope_echo():
        middleware.authorize(request, ("PlatformAdmin",))
        return object_response({}, 200)

    @app.route("/agency-network/agencies/<agency_id>/book-settlement", methods=["POST"])
    def book_settlement(agency_id):
        middleware.authorize(request, ("PlatformAdmin",))
        agency = c.agency_or_404(agency_id)
        data = c.body()
        value = data.get("annualized_commission_cents")
        if value is not None:
            agency["annualized_commission_cents"] = round_cents(dec(value))
        agency["rolling_base_cents"] = agency.get("rolling_base_cents") or 0
        recompute.recompute_agency_soft(agency_id)
        recompute.touch(agency)
        return object_response(serializers.view_agency(agency), 200)
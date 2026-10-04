"""Logical clock and the compliance-posture maintenance action."""

from flask import request

import db
import core
import middleware
import response
import serializers
from decorators import requires


def register(app):
    @app.post("/_clock/set_current_utc")
    @requires("PlatformAdmin")
    def set_clock():
        payload = middleware.body()
        raw = middleware.require_field(payload, "current_utc")
        db.set_clock(middleware.as_instant(raw, "current_utc"))
        return response.ok({"current_utc": db.iso(db.now())})

    @app.post("/_maintenance/recompute-compliance-posture")
    @requires("PlatformAdmin", "ComplianceOfficer", "DirectorOfSales", "LicensingCoordinator",
              "Coach", "CarrierIntegration", "LicensedAgent", "Any")
    def recompute_posture():
        payload = middleware.body()
        agency = middleware.resolve_agency(middleware.require_field(payload, "agency_id"))
        core.recompute_posture(agency)
        return response.ok(serializers.serialize("Agency", agency))
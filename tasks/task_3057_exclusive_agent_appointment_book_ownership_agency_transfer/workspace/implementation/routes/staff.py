"""Team-member endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import staff


READ_ROLES = ("AgencyPrincipal", "FieldManager", "PlatformAdmin")


def register(app):

    @app.route("/agency-network/staff", methods=["POST"])
    def nominate_staff():
        middleware.authorize(request, ("AgencyPrincipal",))
        record = staff.nominate(c.body())
        return object_response(serializers.view_staff(record), 201)

    @app.route("/agency-network/staff", methods=["GET"])
    def list_staff():
        role, uid = middleware.authorize(request, READ_ROLES)
        return c.paged(request, staff.list_staff(request, role, uid),
                       serializers.view_staff)

    @app.route("/agency-network/staff/<staff_id>", methods=["GET"])
    def read_staff(staff_id):
        role, uid = middleware.authorize(request, READ_ROLES + ("StaffMember",))
        # A StaffMember may only read its own record (PRD §3.5).
        middleware.require_self(role, uid, staff_id)
        member = c.staff_or_404(staff_id)
        if role == "AgencyPrincipal":
            c.principal_owns(role, uid, member["agency_id"])
        return object_response(serializers.view_staff(member))

    @app.route("/agency-network/staff/<staff_id>/appoint", methods=["POST"])
    def appoint_staff(staff_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        member = c.staff_or_404(staff_id)
        c.principal_owns(role, uid, member["agency_id"])
        record = staff.appoint(member)
        return object_response(serializers.view_staff(record), 200)
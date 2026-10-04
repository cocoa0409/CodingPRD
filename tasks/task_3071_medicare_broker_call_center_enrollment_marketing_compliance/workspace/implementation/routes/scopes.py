"""Scope of appointment — the precondition for every plan conversation
(PRD 2.5, 2.12, 3.3)."""

import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

CHANNELS = ("TELEPHONIC_RECORDED", "WRITTEN", "ELECTRONIC")
PLAN_TYPES = ("MA", "MAPD", "PDP", "SNP")
READ_ROLES = ("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")


def register(app):
    @app.post("/scope-of-appointments")
    @requires("LicensedAgent")
    def capture_scope():
        payload = middleware.body()
        member = middleware.resolve("Member", middleware.require_field(payload, "member_id"))
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        agency = db.agencies.get(member["agency_id"])
        middleware.gate_posture(agency)
        middleware.owner_check("LicensedAgent", middleware.current_user_id(), agent["id"])

        expected = middleware.as_int(
            middleware.require_field(payload, "expected_member_version"), "expected_member_version")
        if expected != member["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_member_version does not match the member's version.")

        channel = middleware.require_field(payload, "capture_channel", str)
        if channel not in CHANNELS:
            raise ApiError("ERR_INVALID_REQUEST",
                           "capture_channel must be TELEPHONIC_RECORDED, WRITTEN or ELECTRONIC.")
        plan_types = middleware.require_field(payload, "plan_types_authorized", list)
        for plan_type in plan_types:
            if plan_type not in PLAN_TYPES:
                raise ApiError("ERR_INVALID_REQUEST",
                               "plan_types_authorized must be drawn from MA, MAPD, PDP and SNP.")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "member_id": member["id"],
            "agency_id": member["agency_id"],
            "agent_id": agent["id"],
            "capture_channel": channel,
            "plan_types_authorized": list(plan_types),
            "captured_on": middleware.as_instant(
                middleware.require_field(payload, "captured_on"), "captured_on"),
            "consumed_by_enrollment_id": None,
            "status": "CAPTURED",
        }
        db.scopes[row["id"]] = row
        core.touch(member)
        return response.ok(serializers.serialize("ScopeOfAppointment", row), status=201)

    @app.get("/scope-of-appointments")
    @requires(*READ_ROLES)
    def list_scopes():
        rows = list(db.scopes.values())
        for arg, field in (("member_id", "member_id"), ("agent_id", "agent_id"), ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("ScopeOfAppointment", page), limit, offset, total)

    @app.get("/scope-of-appointments/<scope_id>")
    @requires(*READ_ROLES)
    def get_scope(scope_id):
        scope = middleware.resolve("ScopeOfAppointment", scope_id)
        return response.ok(serializers.serialize("ScopeOfAppointment", scope))

    @app.post("/scope-of-appointments/<scope_id>/void")
    @requires("ComplianceOfficer")
    def void_scope(scope_id):
        scope = middleware.resolve("ScopeOfAppointment", scope_id)
        payload = middleware.body()
        if payload.get("reason") is None:
            raise ApiError("ERR_INVALID_REQUEST", "A reason is required to void a scope.")
        scope["status"] = "VOIDED"
        core.touch(scope)
        return response.ok(serializers.serialize("ScopeOfAppointment", scope))
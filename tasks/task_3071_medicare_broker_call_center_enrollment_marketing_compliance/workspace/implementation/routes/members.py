"""Member resource (PRD 3.3)."""

import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError


def register(app):
    @app.post("/members")
    @requires("PlatformAdmin", "LicensedAgent")
    def create_member():
        payload = middleware.body()
        agency = middleware.resolve_agency(middleware.require_field(payload, "agency_id"))
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agency_id": agency["id"],
            "full_name": middleware.require_field(payload, "full_name", str),
            "medicare_beneficiary_id": middleware.require_field(
                payload, "medicare_beneficiary_id", str),
            "date_of_birth": middleware.as_instant(
                middleware.require_field(payload, "date_of_birth"), "date_of_birth"),
            "state_code": middleware.require_field(payload, "state_code", str),
            "county_code": middleware.require_field(payload, "county_code", str),
            "drug_list": middleware.optional(payload, "drug_list", []),
            "provider_npis": middleware.optional(payload, "provider_npis", []),
            "enrollment_count": 0,
        }
        db.members[row["id"]] = row
        return response.ok(serializers.serialize("Member", row), status=201)

    @app.get("/members")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def list_members():
        rows = list(db.members.values())
        agency_id = middleware.text_arg("agency_id")
        if agency_id is not None:
            rows = [row for row in rows if row["agency_id"] == agency_id]
        state_code = middleware.text_arg("state_code")
        if state_code is not None:
            rows = [row for row in rows if row["state_code"] == state_code]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Member", page), limit, offset, total)

    @app.get("/members/<member_id>")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def get_member(member_id):
        member = middleware.resolve("Member", member_id)
        return response.ok(serializers.serialize("Member", member))

    @app.put("/members/<member_id>")
    @requires("PlatformAdmin", "LicensedAgent")
    def update_member(member_id):
        member = middleware.resolve("Member", member_id)
        payload = middleware.body()
        expected = middleware.as_int(
            middleware.require_field(payload, "expected_member_version"), "expected_member_version")
        if expected != member["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_member_version does not match the member's version.")
        if payload.get("drug_list") is not None:
            member["drug_list"] = payload["drug_list"]
        if payload.get("provider_npis") is not None:
            member["provider_npis"] = payload["provider_npis"]
        core.touch(member)
        return response.ok(serializers.serialize("Member", member))

    @app.get("/members/<member_id>/scope-of-appointments")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "Any")
    def list_member_scopes(member_id):
        member = middleware.resolve("Member", member_id)
        rows = [row for row in db.scopes.values() if row["member_id"] == member["id"]]
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("ScopeOfAppointment", page), limit, offset, total)

    @app.get("/members/<member_id>/enrollments")
    @requires("PlatformAdmin", "LicensedAgent", "ComplianceOfficer", "CarrierIntegration", "Any")
    def list_member_enrollments(member_id):
        member = middleware.resolve("Member", member_id)
        rows = [row for row in db.enrollments.values() if row["member_id"] == member["id"]]
        for arg, field in (("submission_status", "submission_status"),
                           ("disenrollment_status", "disenrollment_status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Enrollment", page), limit, offset, total)
"""Agency resource, posture governance and book-of-business (PRD 2.7, 3.1, 3.11)."""

from datetime import timedelta

import calculations as calc
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "Coach", "CarrierIntegration", "LicensedAgent", "Any")

DEFAULTS = {
    "recording_retention_days": 2555,
    "soa_retention_days": 3650,
    "soa_max_age_days": 30,
    "rapid_disenrollment_day_limit": 90,
    "max_live_calls_per_agent": 1,
    "max_open_coaching_per_agent": 2,
}


def register(app):
    @app.post("/agencies")
    @requires("PlatformAdmin")
    def create_agency():
        payload = middleware.body()
        name = middleware.require_field(payload, "name", str)
        service_center_code = middleware.require_field(payload, "service_center_code", str)
        aep_start_date = middleware.as_instant(
            middleware.require_field(payload, "aep_start_date"), "aep_start_date")
        aep_end_date = middleware.as_instant(
            middleware.require_field(payload, "aep_end_date"), "aep_end_date")
        capacity = middleware.as_int(
            middleware.require_field(payload, "aep_daily_submission_capacity"),
            "aep_daily_submission_capacity")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "name": name,
            "service_center_code": service_center_code,
            "aep_start_date": aep_start_date,
            "aep_end_date": aep_end_date,
            "aep_daily_submission_capacity": capacity,
            "compliance_posture": "OPEN",
            "posture_since": db.now(),
            "substantiated_complaint_rate": calc.r6(0),
            "loss_ratio": calc.r6(0),
            "open_complaint_count": 0,
            "commission_balance_cents": calc.r2(0),
        }
        for field, default in DEFAULTS.items():
            row[field] = middleware.as_int(middleware.optional(payload, field, default), field)
        db.agencies[row["id"]] = row
        return response.ok(serializers.serialize("Agency", row), status=201)

    @app.get("/agencies")
    @requires(*READ_ROLES)
    def list_agencies():
        rows = list(db.agencies.values())
        name = middleware.text_arg("name")
        if name is not None:
            rows = [row for row in rows if row["name"] == name]
        posture = middleware.text_arg("compliance_posture")
        if posture is not None:
            rows = [row for row in rows if row["compliance_posture"] == posture]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Agency", page), limit, offset, total)

    @app.get("/agencies/<agency_id>")
    @requires(*READ_ROLES)
    def get_agency(agency_id):
        agency = middleware.resolve_agency(agency_id)
        return response.ok(serializers.serialize("Agency", agency))

    @app.put("/agencies/<agency_id>")
    @requires("PlatformAdmin")
    def update_agency(agency_id):
        agency = middleware.resolve_agency(agency_id)
        payload = middleware.body()
        expected = middleware.as_int(
            middleware.require_field(payload, "expected_agency_version"), "expected_agency_version")
        if expected != agency["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_agency_version does not match the agency's version.")

        for field in ("name", "service_center_code"):
            if payload.get(field) is not None:
                agency[field] = payload[field]
        for field in ("aep_start_date", "aep_end_date"):
            if payload.get(field) is not None:
                agency[field] = middleware.as_instant(payload[field], field)
        for field in ("aep_daily_submission_capacity", "recording_retention_days",
                      "soa_retention_days", "soa_max_age_days",
                      "rapid_disenrollment_day_limit", "max_live_calls_per_agent",
                      "max_open_coaching_per_agent"):
            if payload.get(field) is not None:
                agency[field] = middleware.as_int(payload[field], field)
        core.touch(agency)
        return response.ok(serializers.serialize("Agency", agency))

    @app.post("/agencies/<agency_id>/posture-reset")
    @requires("ComplianceOfficer")
    def posture_reset(agency_id):
        agency = middleware.resolve_agency(agency_id)
        payload = middleware.body()
        target = middleware.require_field(payload, "target_posture", str)

        if target == "RESTRICTED":
            if agency["compliance_posture"] != "FROZEN":
                raise ApiError("ERR_AGENCY_NOT_FROZEN",
                               "A reset toward RESTRICTED requires the agency to be FROZEN.")
            if agency["open_complaint_count"] != 0:
                raise ApiError("ERR_SUBSTANTIATED_COMPLAINT_OPEN",
                               "Open complaints block a reset toward RESTRICTED.")
            if _has_open_coaching(agency):
                raise ApiError("ERR_COACHING_OVERDUE_BLOCKS_RESET",
                               "Open coaching assignments block a posture reset.")
            agency["compliance_posture"] = "RESTRICTED"
            agency["posture_since"] = db.now()
            core.touch(agency)
            return response.ok(serializers.serialize("Agency", agency))

        if target == "OPEN":
            if agency["compliance_posture"] != "RESTRICTED":
                raise ApiError("ERR_AGENCY_NOT_RESTRICTED",
                               "A reset toward OPEN requires the agency to be RESTRICTED.")
            if calc.dec(agency["substantiated_complaint_rate"]) >= calc.POSTURE_RESTRICT_THRESHOLD:
                raise ApiError("ERR_SUBSTANTIATED_COMPLAINT_OPEN",
                               "The substantiated complaint rate is still at or above 0.05.")
            if _has_open_coaching(agency):
                raise ApiError("ERR_COACHING_OVERDUE_BLOCKS_RESET",
                               "Open coaching assignments block a posture reset.")
            agency["compliance_posture"] = "OPEN"
            agency["posture_since"] = db.now()
            core.touch(agency)
            for agent in core.agency_agents(agency["id"]):
                if agent["status"] == "SUSPENDED" and not _agent_open_coaching(agent["id"]):
                    agent["status"] = "ACTIVE"
                    core.touch(agent)
            return response.ok(serializers.serialize("Agency", agency))

        raise ApiError("ERR_INVALID_REQUEST",
                       "target_posture must be RESTRICTED or OPEN.")

    @app.get("/agencies/<agency_id>/book-of-business")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer")
    def book_of_business(agency_id):
        agency = middleware.resolve_agency(agency_id)
        window_days = middleware.number_arg("window_days")
        window_days = calc.FORWARD_WINDOW_DAYS if window_days is None else int(window_days)
        total, count, window_start, window_end = core.provisional_book_commission(
            agency["id"], window_days)
        return response.ok({
            "agency_id": agency["id"],
            "window_start": db.iso(window_start),
            "window_end": db.iso(window_end),
            "provisional_book_commission_cents": calc.num(total),
            "qualifying_enrollment_count": count,
        })

    @app.get("/agencies/<agency_id>/agents")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "Coach", "Any")
    def list_agency_agents(agency_id):
        agency = middleware.resolve_agency(agency_id)
        rows = core.agency_agents(agency["id"])
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Agent", page), limit, offset, total)

    @app.get("/agencies/<agency_id>/members")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "LicensedAgent", "Any")
    def list_agency_members(agency_id):
        agency = middleware.resolve_agency(agency_id)
        rows = [row for row in db.members.values() if row["agency_id"] == agency["id"]]
        state_code = middleware.text_arg("state_code")
        if state_code is not None:
            rows = [row for row in rows if row["state_code"] == state_code]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Member", page), limit, offset, total)


def _has_open_coaching(agency):
    for row in core.agency_coaching(agency["id"]):
        if row["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE"):
            return True
    return False


def _agent_open_coaching(agent_id):
    for row in core.agent_coaching(agent_id):
        if row["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE"):
            return True
    return False
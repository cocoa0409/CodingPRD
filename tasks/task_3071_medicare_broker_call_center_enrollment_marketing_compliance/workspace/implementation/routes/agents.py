"""Agent resource and the four-gate staffing pipeline (PRD 2.4, 3.2)."""

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
              "LicensingCoordinator", "Coach", "LicensedAgent", "Any")
LIST_ROLES = ("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "Coach", "Any")


def register(app):
    @app.post("/agents")
    @requires("PlatformAdmin", "DirectorOfSales")
    def create_agent():
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
            "national_producer_number": middleware.require_field(
                payload, "national_producer_number", str),
            "hire_date": middleware.as_instant(middleware.require_field(payload, "hire_date"), "hire_date"),
            "status": "PROVISIONING",
            "licensed_state_count": 0,
            "certified_carrier_count": 0,
            "appointed_carrier_count": 0,
            "live_call_count": 0,
            "active_enrollment_count": 0,
            "chargeback_tier": 0,
            "substantiated_complaint_count": 0,
            "compliance_risk_score": calc.r2(0),
            "coaching_flag": False,
            "open_coaching_count": 0,
            "_terminated_at": None,
        }
        db.agents[row["id"]] = row
        return response.ok(serializers.serialize("Agent", row), status=201)

    @app.get("/agents")
    @requires(*LIST_ROLES)
    def list_agents():
        rows = list(db.agents.values())
        agency_id = middleware.text_arg("agency_id")
        if agency_id is not None:
            rows = [row for row in rows if row["agency_id"] == agency_id]
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        coaching_flag = middleware.bool_arg("coaching_flag")
        if coaching_flag is not None:
            rows = [row for row in rows if bool(row["coaching_flag"]) == coaching_flag]
        min_score = middleware.number_arg("min_compliance_risk_score")
        if min_score is not None:
            rows = [row for row in rows if calc.dec(row["compliance_risk_score"]) >= calc.dec(min_score)]
        carrier_id = middleware.text_arg("carrier_id")
        if carrier_id is not None:
            holders = {row["agent_id"] for row in db.appointments.values()
                       if row["carrier_id"] == carrier_id and row["status"] != "TERMINATED"}
            rows = [row for row in rows if row["id"] in holders]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Agent", page), limit, offset, total)

    @app.get("/agents/<agent_id>")
    @requires(*READ_ROLES)
    def get_agent(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        # An assignment's overdue figure is derived on every read and on every
        # mutation of its agent, and reaching 1 moves it to OVERDUE — so the
        # read refreshes the derived counters before they are reported.
        core.sweep_overdue({agent["id"]})
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Agent", agent))

    # -- Gate 1: licensure ---------------------------------------------------
    @app.post("/agents/<agent_id>/licenses")
    @requires("LicensingCoordinator")
    def add_license(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        payload = middleware.body()
        agency = middleware.agency_of_agent(agent)
        middleware.gate_posture(agency)

        state_code = middleware.require_field(payload, "state_code", str)
        license_number = middleware.require_field(payload, "license_number", str)
        issued_on = middleware.as_instant(middleware.require_field(payload, "issued_on"), "issued_on")
        expires_on = middleware.as_instant(middleware.require_field(payload, "expires_on"), "expires_on")

        if issued_on > expires_on:
            raise ApiError("ERR_INVALID_LICENSE_DATES",
                           "issued_on must not be later than expires_on.")
        for existing in core.agent_licenses(agent["id"]):
            if existing["state_code"] == state_code and existing["expires_on"] > db.now():
                raise ApiError("ERR_DUPLICATE_STATE_LICENSE",
                               "The agent already holds an unexpired license for this state.")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agent_id": agent["id"],
            "state_code": state_code,
            "license_number": license_number,
            "issued_on": issued_on,
            "expires_on": expires_on,
        }
        db.state_licenses[row["id"]] = row
        if agent["status"] == "PROVISIONING":
            agent["status"] = "LICENSED"
            core.touch(agent)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("AgentStateLicense", row), status=201)

    @app.get("/agents/<agent_id>/licenses")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "Any")
    def list_licenses(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_licenses(agent["id"])
        state_code = middleware.text_arg("state_code")
        if state_code is not None:
            rows = [row for row in rows if row["state_code"] == state_code]
        license_status = middleware.text_arg("license_status")
        if license_status is not None:
            rows = [row for row in rows if core.license_status(row) == license_status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("AgentStateLicense", page), limit, offset, total)

    # -- Gate 2: certification ----------------------------------------------
    @app.post("/agents/<agent_id>/certifications")
    @requires("LicensingCoordinator")
    def add_certification(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        payload = middleware.body()
        carrier = middleware.resolve("Carrier", middleware.require_field(payload, "carrier_id"))
        agency = middleware.agency_of_agent(agent)
        middleware.gate_posture(agency)

        if agent["status"] != "LICENSED":
            raise ApiError("ERR_AGENT_NOT_LICENSED",
                           "A carrier certification requires the agent to be LICENSED.")
        product_type = middleware.require_field(payload, "product_type", str)
        if product_type not in calc.PLAN_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "product_type must be MA, MAPD, PDP or SNP.")
        if carrier["status"] != "ACTIVE":
            raise ApiError("ERR_CARRIER_NOT_FOUND", "The carrier is not in status ACTIVE.")
        if carrier["contract_type"] != "CONTRACTED":
            raise ApiError("ERR_CARRIER_NOT_CONTRACTED",
                           "The carrier is MARKETING_ONLY; it cannot be appointed through.")
        for existing in core.agent_certifications(agent["id"]):
            if existing["carrier_id"] == carrier["id"] and existing["product_type"] == product_type \
                    and existing["status"] == "CERTIFIED":
                raise ApiError("ERR_DUPLICATE_CERTIFICATION",
                               "A CERTIFIED certification already exists for this product type.")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agent_id": agent["id"],
            "carrier_id": carrier["id"],
            "product_type": product_type,
            "certified_on": db.now(),
            "expires_on": middleware.as_instant(middleware.require_field(payload, "expires_on"), "expires_on"),
            "status": "CERTIFIED",
        }
        db.certifications[row["id"]] = row
        agent["status"] = "CERTIFIED"
        core.touch(agent)
        _certification_hop(agency, agent, carrier)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("CarrierCertification", row), status=201)

    @app.get("/agents/<agent_id>/certifications")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "CarrierIntegration", "Any")
    def list_certifications(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_certifications(agent["id"])
        for arg, field in (("carrier_id", "carrier_id"), ("product_type", "product_type"),
                           ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CarrierCertification", page), limit, offset, total)

    # -- Gate 3: appointment -------------------------------------------------
    @app.post("/agents/<agent_id>/appointments")
    @requires("LicensingCoordinator")
    def add_appointment(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        payload = middleware.body()
        carrier = middleware.resolve("Carrier", middleware.require_field(payload, "carrier_id"))
        agency = middleware.agency_of_agent(agent)
        middleware.gate_posture(agency)

        if agent["status"] != "CERTIFIED":
            raise ApiError("ERR_AGENT_NOT_CERTIFIED",
                           "A carrier appointment requires the agent to be CERTIFIED.")
        has_certification = any(
            row["status"] == "CERTIFIED" and row["carrier_id"] == carrier["id"]
            for row in core.agent_certifications(agent["id"])
        )
        if not has_certification:
            raise ApiError("ERR_CERTIFICATION_NOT_FOUND",
                           "No CERTIFIED certification exists for this carrier.")
        state_code = middleware.require_field(payload, "state_code", str)
        has_license = any(
            row["state_code"] == state_code and core.license_status(row) == "VALID"
            for row in core.agent_licenses(agent["id"])
        )
        if not has_license:
            raise ApiError("ERR_INVALID_STATE_LICENSE",
                           "No VALID state license covers the requested state_code.")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agent_id": agent["id"],
            "carrier_id": carrier["id"],
            "state_code": state_code,
            "requested_on": middleware.as_instant(
                middleware.require_field(payload, "requested_on"), "requested_on"),
            "appointed_on": db.now(),
            "terminated_on": None,
            "status": "APPOINTED",
        }
        db.appointments[row["id"]] = row
        agent["status"] = "ACTIVE"
        core.touch(agent)
        core.recompute_agent_counts(agent)
        for other in core.agency_agents(agency["id"]):
            if other["id"] != agent["id"]:
                core.recompute_agent_counts(other)
        return response.ok(serializers.serialize("CarrierAppointment", row), status=201)

    @app.get("/agents/<agent_id>/appointments")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "LicensingCoordinator", "CarrierIntegration", "Any")
    def list_agent_appointments(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_appointments(agent["id"])
        for arg, field in (("carrier_id", "carrier_id"), ("state_code", "state_code"),
                           ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CarrierAppointment", page), limit, offset, total)

    # -- Lifecycle -----------------------------------------------------------
    @app.post("/agents/<agent_id>/reinstate")
    @requires("ComplianceOfficer")
    def reinstate_agent(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        agency = middleware.agency_of_agent(agent)
        core.sweep_overdue({agent["id"]})

        if agent["status"] != "SUSPENDED":
            raise ApiError("ERR_AGENT_NOT_SUSPENDED", "The agent is not SUSPENDED.")
        if agency["compliance_posture"] == "FROZEN":
            raise ApiError("ERR_AGENCY_FROZEN", "The agency is FROZEN.")
        if agency["compliance_posture"] != "OPEN":
            raise ApiError("ERR_AGENCY_NOT_OPEN", "Reinstatement requires an OPEN agency posture.")
        open_coaching = [row for row in core.agent_coaching(agent["id"])
                         if row["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE")]
        if open_coaching:
            raise ApiError("ERR_COACHING_OPEN",
                           "An open coaching assignment blocks reinstatement.")
        if not any(row["status"] == "APPOINTED" for row in core.agent_appointments(agent["id"])):
            raise ApiError("ERR_APPOINTMENT_MISSING",
                           "Reinstatement requires an APPOINTED carrier appointment.")
        if not any(row["status"] == "CERTIFIED" for row in core.agent_certifications(agent["id"])):
            raise ApiError("ERR_CERTIFICATION_NOT_FOUND",
                           "Reinstatement requires a CERTIFIED carrier certification.")
        if not any(core.license_status(row) == "VALID" for row in core.agent_licenses(agent["id"])):
            raise ApiError("ERR_INVALID_STATE_LICENSE",
                           "Reinstatement requires a VALID state license.")

        agent["status"] = "ACTIVE"
        core.touch(agent)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Agent", agent))

    @app.post("/agents/<agent_id>/terminate")
    @requires("DirectorOfSales")
    def terminate_agent(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        payload = middleware.body()
        if agent["status"] == "TERMINATED":
            raise ApiError("ERR_AGENT_ALREADY_TERMINATED", "The agent is already TERMINATED.")
        effective_on = db.now()
        if payload.get("effective_on") is not None:
            effective_on = middleware.as_instant(payload["effective_on"], "effective_on")

        agent["status"] = "TERMINATED"
        agent["_terminated_at"] = effective_on
        core.touch(agent)
        for row in core.agent_appointments(agent["id"]):
            if row["status"] == "APPOINTED":
                row["status"] = "TERMINATED"
                row["terminated_on"] = effective_on
                core.touch(row)
        for row in core.agent_certifications(agent["id"]):
            if row["status"] == "CERTIFIED":
                row["status"] = "EXPIRED"
                core.touch(row)
        for session in core.agent_sessions(agent["id"]):
            if session["status"] in ("RINGING", "IN_PROGRESS"):
                session["status"] = "DROPPED"
                session["actual_end_at"] = db.now()
                core.touch(session)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Agent", agent))

    @app.post("/agents/<agent_id>/rehire")
    @requires("DirectorOfSales")
    def rehire_agent(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        payload = middleware.body()
        agency = middleware.agency_of_agent(agent)

        if agent["status"] != "TERMINATED":
            raise ApiError("ERR_AGENT_NOT_TERMINATED", "Rehire requires a TERMINATED agent.")
        middleware.gate_posture(agency)
        hire_date = middleware.as_instant(middleware.require_field(payload, "hire_date"), "hire_date")
        terminated_at = agent.get("_terminated_at")
        if terminated_at is not None and hire_date <= terminated_at:
            raise ApiError("ERR_REHIRE_BEFORE_TERMINATION",
                           "hire_date must be strictly after the most recent termination.")
        for row in core.agent_certifications(agent["id"]):
            if row["expires_on"] >= hire_date:
                raise ApiError("ERR_RECERTIFICATION_REQUIRED",
                               "A certification still covers the rehire instant.")

        agent["status"] = "PROVISIONING"
        agent["hire_date"] = hire_date
        agent["chargeback_tier"] = 0
        agent["coaching_flag"] = False
        agent["open_coaching_count"] = 0
        core.touch(agent)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Agent", agent))

    # -- Agent-scoped collections -------------------------------------------
    @app.get("/agents/<agent_id>/members")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "LicensedAgent", "Any")
    def list_agent_members(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        member_ids = {row["member_id"] for row in db.scopes.values() if row["agent_id"] == agent["id"]}
        member_ids |= {row["member_id"] for row in db.enrollments.values()
                       if row["agent_id"] == agent["id"]}
        rows = [row for row in db.members.values() if row["id"] in member_ids]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Member", page), limit, offset, total)

    @app.get("/agents/<agent_id>/complaints")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "Coach", "Any")
    def list_agent_complaints(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_complaints(agent["id"])
        for arg, field in (("status", "status"), ("severity", "severity"), ("source", "source")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Complaint", page), limit, offset, total)

    @app.get("/agents/<agent_id>/coaching-assignments")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "Coach", "Any")
    def list_agent_coaching(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        core.sweep_overdue({agent["id"]})
        rows = core.agent_coaching(agent["id"])
        for arg, field in (("status", "status"), ("coaching_type", "coaching_type")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CoachingAssignment", page), limit, offset, total)

    @app.get("/agents/<agent_id>/call-sessions")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "Coach", "LicensedAgent", "Any")
    def list_agent_sessions(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_sessions(agent["id"])
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CallSession", page), limit, offset, total)

    @app.get("/agents/<agent_id>/enrollments")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "CarrierIntegration", "LicensedAgent", "Any")
    def list_agent_enrollments(agent_id):
        agent = middleware.resolve("Agent", agent_id)
        rows = core.agent_enrollments(agent["id"])
        rows = _filter_enrollments(rows)
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Enrollment", page), limit, offset, total)


def _filter_enrollments(rows):
    for arg, field in (("submission_status", "submission_status"),
                       ("disenrollment_status", "disenrollment_status")):
        value = middleware.text_arg(arg)
        if value is not None:
            rows = [row for row in rows if row[field] == value]
    return rows


def _certification_hop(agency, certified_agent, carrier):
    """PRD 3.2: agents of the same agency sharing an appointment on this carrier
    and currently CERTIFIED advance to ACTIVE."""
    if agency is None:
        return
    for other in core.agency_agents(agency["id"]):
        if other["id"] == certified_agent["id"] or other["status"] != "CERTIFIED":
            continue
        shares = any(
            row["carrier_id"] == carrier["id"] and row["status"] == "APPOINTED"
            for row in core.agent_appointments(other["id"])
        )
        if not shares:
            continue
        for row in core.agent_certifications(other["id"]):
            if row["carrier_id"] == carrier["id"] and row["status"] != "CERTIFIED":
                row["status"] = "CERTIFIED"
                row["certified_on"] = db.now()
                core.touch(row)
        core.recompute_agent_counts(other)
        if other["appointed_carrier_count"] > 0:
            other["status"] = "ACTIVE"
            core.touch(other)
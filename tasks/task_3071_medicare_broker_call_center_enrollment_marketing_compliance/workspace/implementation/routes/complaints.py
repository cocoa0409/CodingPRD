"""Complaints, secret shoppers and coaching (PRD 3.9)."""

from datetime import timedelta
from decimal import Decimal

import calculations as calc
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

COMPLAINT_TYPES = (
    "MISREPRESENTATION", "SOA_MISSING", "DISCLAIMER_MISSING", "RECORDING_MISSING",
    "UNAPPROVED_MARKETING", "PLAN_MISREPRESENTATION", "DISENROLLMENT_DELAY",
)
SOURCES = ("BENEFICIARY", "CMS", "CARRIER", "SECRET_SHOPPER")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
COACHING_TYPES = (
    "SOA_RETRAINING", "DISCLAIMER_RETRAINING", "MARKETING_RULES",
    "PLAN_DETAIL_ACCURACY", "RECORDING_RETENTION",
)
APPEAL_WINDOW_DAYS = 30
READ_ROLES = ("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "Coach", "Any")


def register(app):
    @app.post("/complaints")
    @requires("ComplianceOfficer", "CarrierIntegration")
    def file_complaint():
        payload = middleware.body()
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        complaint_type = middleware.require_field(payload, "complaint_type", str)
        if complaint_type not in COMPLAINT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "complaint_type is not a recognized value.")
        source = middleware.require_field(payload, "source", str)
        if source not in SOURCES:
            raise ApiError("ERR_INVALID_REQUEST", "source is not a recognized value.")
        severity = middleware.require_field(payload, "severity", str)
        if severity not in SEVERITIES:
            raise ApiError("ERR_INVALID_REQUEST", "severity is not a recognized value.")
        filed_on = middleware.as_instant(middleware.require_field(payload, "filed_on"), "filed_on")

        shopper_score = payload.get("shopper_score")
        if source == "SECRET_SHOPPER":
            if shopper_score is None:
                raise ApiError("ERR_INVALID_REQUEST",
                               "shopper_score is required for a secret-shopper complaint.")
            shopper_score = middleware.as_int(shopper_score, "shopper_score")
            if shopper_score < 0 or shopper_score > 100:
                raise ApiError("ERR_INVALID_REQUEST", "shopper_score must be between 0 and 100.")
        elif shopper_score is not None:
            shopper_score = middleware.as_int(shopper_score, "shopper_score")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agent_id": agent["id"],
            "agency_id": agent["agency_id"],
            "complaint_type": complaint_type,
            "source": source,
            "severity": severity,
            "filed_on": filed_on,
            "shopper_score": shopper_score,
            "soa_requested_correctly": payload.get("soa_requested_correctly"),
            "disclaimer_played": payload.get("disclaimer_played"),
            "approved_marketing_used": payload.get("approved_marketing_used"),
            "status": "OPEN",
            "finding_code": None,
            "substantiated_on": None,
            "_dismissed_on": None,
        }
        db.complaints[row["id"]] = row
        agency = db.agencies.get(agent["agency_id"])
        core.recompute_open_complaint_count(agency)
        return response.ok(serializers.serialize("Complaint", row), status=201)

    @app.get("/complaints")
    @requires(*READ_ROLES)
    def list_complaints():
        rows = list(db.complaints.values())
        for arg, field in (("agent_id", "agent_id"), ("status", "status"),
                           ("source", "source"), ("severity", "severity")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Complaint", page), limit, offset, total)

    @app.get("/complaints/<complaint_id>")
    @requires(*READ_ROLES)
    def get_complaint(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        return response.ok(serializers.serialize("Complaint", row))

    @app.post("/complaints/<complaint_id>/begin-review")
    @requires("ComplianceOfficer")
    def begin_review(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        if row["status"] != "OPEN":
            raise ApiError("ERR_COMPLAINT_NOT_OPEN", "The complaint is not OPEN.")
        row["status"] = "UNDER_REVIEW"
        core.touch(row)
        core.recompute_open_complaint_count(db.agencies.get(row["agency_id"]))
        return response.ok(serializers.serialize("Complaint", row))

    @app.post("/complaints/<complaint_id>/substantiate")
    @requires("ComplianceOfficer")
    def substantiate(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        if row["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_COMPLAINT_NOT_UNDER_REVIEW", "The complaint is not UNDER_REVIEW.")
        if row["filed_on"] > db.now():
            raise ApiError("ERR_COMPLAINT_FILED_IN_FUTURE",
                           "A complaint filed in the future cannot be substantiated.")

        row["status"] = "SUBSTANTIATED"
        row["finding_code"] = calc.finding_code(row)
        row["substantiated_on"] = db.now()
        core.touch(row)

        agent = db.agents.get(row["agent_id"])
        agency = db.agencies.get(row["agency_id"])
        agent["substantiated_complaint_count"] += 1
        core.touch(agent)
        core.recompute_substantiated_rate(agency)
        core.recompute_open_complaint_count(agency)
        core.recompute_risk_score(agent)
        _create_coaching(agent, complaint_id=row["id"], coaching_type=_coaching_type_for(row))
        core.recompute_agent_counts(agent)
        # Coaching-assignment creation is itself a recomputation trigger (PRD 3.10).
        core.recompute_risk_score(agent)
        core.recompute_posture(agency)
        return response.ok(serializers.serialize("Complaint", row))

    @app.post("/complaints/<complaint_id>/dismiss")
    @requires("ComplianceOfficer")
    def dismiss(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        agent = db.agents.get(row["agent_id"])
        agency = db.agencies.get(row["agency_id"])

        if row["status"] == "UNDER_REVIEW":
            row["status"] = "DISMISSED"
            row["_dismissed_on"] = db.now()
            core.touch(row)
            core.recompute_open_complaint_count(agency)
            core.recompute_posture(agency)
            return response.ok(serializers.serialize("Complaint", row))

        if row["status"] == "APPEALED":
            if agent["substantiated_complaint_count"] < 1:
                raise ApiError("ERR_NO_SUBSTANTIATION_TO_REVERSE",
                               "There is no standing substantiation to reverse.")
            row["status"] = "DISMISSED"
            row["_dismissed_on"] = db.now()
            core.touch(row)
            agent["substantiated_complaint_count"] -= 1
            core.touch(agent)
            core.recompute_substantiated_rate(agency)
            core.recompute_risk_score(agent)
            core.recompute_posture(agency)
            return response.ok(serializers.serialize("Complaint", row))

        raise ApiError("ERR_COMPLAINT_NOT_UNDER_REVIEW",
                       "The complaint cannot be dismissed from its current status.")

    @app.post("/complaints/<complaint_id>/appeal")
    @requires("CarrierIntegration")
    def appeal(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        status = row["status"]
        if status == "SUBSTANTIATED":
            reference = row.get("substantiated_on")
        elif status == "DISMISSED":
            reference = row.get("_dismissed_on")
        else:
            raise ApiError("ERR_COMPLAINT_NOT_SUBSTANTIATED",
                           "Only a SUBSTANTIATED or DISMISSED complaint may be appealed.")
        if reference is None or db.now() > reference + timedelta(days=APPEAL_WINDOW_DAYS):
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", "The appeal window has expired.")

        row["status"] = "APPEALED"
        core.touch(row)
        core.recompute_risk_score(db.agents.get(row["agent_id"]))
        return response.ok(serializers.serialize("Complaint", row))

    @app.post("/complaints/<complaint_id>/remand")
    @requires("ComplianceOfficer")
    def remand(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        if row["status"] != "APPEALED":
            raise ApiError("ERR_COMPLAINT_NOT_APPEALED", "The complaint is not APPEALED.")
        row["status"] = "UNDER_REVIEW"
        core.touch(row)
        core.recompute_open_complaint_count(db.agencies.get(row["agency_id"]))
        return response.ok(serializers.serialize("Complaint", row))

    @app.post("/complaints/<complaint_id>/close")
    @requires("ComplianceOfficer")
    def close(complaint_id):
        row = middleware.resolve("Complaint", complaint_id)
        if row["status"] not in ("APPEALED", "DISMISSED", "SUBSTANTIATED"):
            raise ApiError("ERR_COMPLAINT_NOT_CLOSABLE",
                           "The complaint cannot be closed from its current status.")
        row["status"] = "CLOSED"
        core.touch(row)
        agent = db.agents.get(row["agent_id"])
        agency = db.agencies.get(row["agency_id"])
        core.recompute_open_complaint_count(agency)
        for assignment in core.agent_coaching(agent["id"]):
            if assignment.get("complaint_id") == row["id"] \
                    and assignment["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE"):
                assignment["status"] = "COMPLETED"
                assignment["completed_on"] = db.now()
                core.touch(assignment)
        core.recompute_agent_counts(agent)
        core.recompute_risk_score(agent)
        core.recompute_posture(agency)
        return response.ok(serializers.serialize("Complaint", row))

    # -- Coaching ------------------------------------------------------------
    @app.post("/coaching-assignments")
    @requires("Coach", "ComplianceOfficer")
    def create_coaching():
        payload = middleware.body()
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        coaching_type = middleware.require_field(payload, "coaching_type", str)
        if coaching_type not in COACHING_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "coaching_type is not a recognized value.")
        complaint_id = payload.get("complaint_id")
        if complaint_id is not None:
            middleware.resolve("Complaint", complaint_id)
        row = _create_coaching(agent, complaint_id=complaint_id, coaching_type=coaching_type)
        core.recompute_agent_counts(agent)
        core.recompute_risk_score(agent)
        return response.ok(serializers.serialize("CoachingAssignment", row), status=201)

    @app.get("/coaching-assignments")
    @requires(*READ_ROLES)
    def list_coaching():
        core.sweep_overdue()
        rows = list(db.coaching.values())
        for arg, field in (("agent_id", "agent_id"), ("complaint_id", "complaint_id"),
                           ("status", "status"), ("coaching_type", "coaching_type")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CoachingAssignment", page), limit, offset, total)

    @app.get("/coaching-assignments/<assignment_id>")
    @requires(*READ_ROLES)
    def get_coaching(assignment_id):
        row = middleware.resolve("CoachingAssignment", assignment_id)
        core.sweep_overdue({row["agent_id"]})
        return response.ok(serializers.serialize("CoachingAssignment", row))

    @app.post("/coaching-assignments/<assignment_id>/start")
    @requires("Coach")
    def start_coaching(assignment_id):
        row = middleware.resolve("CoachingAssignment", assignment_id)
        # The overdue derivation is refreshed on every mutation of the agent, so
        # an assignment whose due_on has already passed is moved to OVERDUE
        # before the start edge is evaluated (PRD §3.9).
        core.sweep_overdue({row["agent_id"]})
        if row["status"] != "ASSIGNED":
            raise ApiError("ERR_COACHING_NOT_ASSIGNED", "The assignment is not ASSIGNED.")
        row["status"] = "IN_PROGRESS"
        core.touch(row)
        return response.ok(serializers.serialize("CoachingAssignment", row))

    @app.post("/coaching-assignments/<assignment_id>/complete")
    @requires("Coach")
    def complete_coaching(assignment_id):
        row = middleware.resolve("CoachingAssignment", assignment_id)
        core.sweep_overdue({row["agent_id"]})
        if row["status"] not in ("IN_PROGRESS", "OVERDUE"):
            raise ApiError("ERR_COACHING_NOT_IN_PROGRESS",
                           "The assignment is not IN_PROGRESS or OVERDUE.")
        row["status"] = "COMPLETED"
        row["completed_on"] = db.now()
        core.touch(row)
        agent = db.agents.get(row["agent_id"])
        core.recompute_agent_counts(agent)
        core.recompute_risk_score(agent)
        core.recompute_posture(db.agencies.get(agent["agency_id"]))
        return response.ok(serializers.serialize("CoachingAssignment", row))


def _coaching_type_for(complaint):
    mapping = {
        "SOA_MISSING": "SOA_RETRAINING",
        "DISENROLLMENT_DELAY": "SOA_RETRAINING",
        "DISCLAIMER_MISSING": "DISCLAIMER_RETRAINING",
        "UNAPPROVED_MARKETING": "MARKETING_RULES",
        "MISREPRESENTATION": "MARKETING_RULES",
        "PLAN_MISREPRESENTATION": "PLAN_DETAIL_ACCURACY",
        "RECORDING_MISSING": "RECORDING_RETENTION",
    }
    return mapping.get(complaint["complaint_type"], "PLAN_DETAIL_ACCURACY")


def _create_coaching(agent, complaint_id=None, coaching_type="PLAN_DETAIL_ACCURACY"):
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "agent_id": agent["id"],
        "complaint_id": complaint_id,
        "coaching_type": coaching_type,
        "triggered_by": "COMPLAINT" if complaint_id else "MANUAL",
        "assigned_on": db.now(),
        "due_on": db.now() + timedelta(days=calc.COACHING_DUE_DAYS),
        "completed_on": None,
        "status": "ASSIGNED",
    }
    db.coaching[row["id"]] = row
    agent["coaching_flag"] = True
    agent["open_coaching_count"] = len([
        r for r in core.agent_coaching(agent["id"])
        if r["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE")
    ])
    return row
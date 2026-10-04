"""Entity assertions and small domain helpers.

Each assert_* checks the standard system-managed fields (id, created_at,
updated_at, version) plus the domain fields the PRD names for the resource,
and confines value checks to enum membership so tests stay PRD-faithful.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (accepts trailing Z or +00:00)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_common_fields(data: dict, label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_volunteer(data: dict):
    assert_common_fields(data, "Volunteer")
    for field in ("full_name", "email", "home_region"):
        assert isinstance(data.get(field), str) and len(data[field]) > 0, f"Volunteer.{field} required"
    assert isinstance(data.get("skills"), list)
    assert isinstance(data.get("availability_windows"), list)
    assert isinstance(data.get("instructor_certified"), bool)
    assert data.get("readiness_status") in [
        "REGISTERED", "VETTED", "DEPLOYABLE", "SUSPENDED", "INACTIVE",
    ]
    for field in ("operational_readiness_score", "readiness_score", "fatigue_hours"):
        assert isinstance(data.get(field), int), f"Volunteer.{field} must be an integer"
    assert data["readiness_score"] >= 0, "readiness_score is floored at 0"


def assert_certification(data: dict):
    assert_common_fields(data, "Certification")
    assert isinstance(data.get("volunteer_id"), str)
    assert data.get("kind") in ["CHAINSAW", "HEAVY_EQUIPMENT", "STRUCTURAL", "MEDICAL"]
    assert data.get("status") in [
        "PENDING_VERIFICATION", "VERIFIED", "EXPIRED", "REVOKED", "REJECTED",
    ]
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert isinstance(data.get("renewal_count"), int)
    assert "verified_by_user_id" in data


def assert_incident(data: dict):
    assert_common_fields(data, "Incident")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("region"), str) and len(data["region"]) > 0
    assert data.get("status") in [
        "REPORTED", "ASSESSED", "TYPED", "STANDING_DOWN", "CLOSED", "CANCELLED",
    ]
    for field in ("severity", "affected_households", "incident_type"):
        assert field in data, f"Incident.{field} must be present (null until its transition)"
    assert is_iso8601_timestamp(data.get("reported_at", ""))


def assert_operation(data: dict):
    assert_common_fields(data, "Operation")
    assert isinstance(data.get("incident_id"), str)
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("hazard_focus") in [
        "TREE_REMOVAL", "MUCK_OUT", "TARPING", "DEBRIS", "STRUCTURAL",
    ]
    assert isinstance(data.get("team_size_required"), int)
    assert isinstance(data.get("duration_days"), int)
    assert isinstance(data.get("required_capabilities"), list)
    assert isinstance(data.get("start_date"), str)
    assert data.get("status") in [
        "DRAFT", "OPEN", "MUSTERED", "ACTIVE", "DEMOBILIZING", "COMPLETE", "CANCELLED",
    ]
    assert data.get("aar_status") in ["NONE", "SUBMITTED", "ADOPTED"]
    assert "aar_notes" in data
    assert "aar_submitted_by_role" in data
    assert isinstance(data.get("rostered_count"), int)
    assert isinstance(data.get("capability_gap"), dict)


def assert_deployment(data: dict):
    assert_common_fields(data, "Deployment")
    assert isinstance(data.get("operation_id"), str)
    assert isinstance(data.get("volunteer_id"), str)
    assert data.get("status") in [
        "OFFERED", "ACCEPTED", "ON_SITE", "SAFETY_HOLD",
        "DEMOBED", "DECLINED", "EXPIRED", "NO_SHOW",
    ]
    assert data.get("duty_status") in ["RESTING", "ON_DUTY"]
    assert data.get("travel_mode") in ["SELF", "TEAM_TRANSPORT"]
    assert isinstance(data.get("needs_lodging"), bool)
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    for field in ("fob_site_id", "checked_in_at", "demobed_at", "stipend_final_cents"):
        assert field in data, f"Deployment.{field} must be present (null until its transition)"
    assert "stipend_provisional_cents" in data


def assert_fob_site(data: dict):
    assert_common_fields(data, "FobSite")
    assert isinstance(data.get("operation_id"), str)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("bunks_total"), int) and data["bunks_total"] >= 1
    assert isinstance(data.get("nightly_rate_cents"), int) and data["nightly_rate_cents"] >= 0
    assert isinstance(data.get("bunks_occupied"), int) and data["bunks_occupied"] >= 0
    assert isinstance(data.get("lodging_cost_cents"), int) and data["lodging_cost_cents"] >= 0


def assert_duty_shift(data: dict):
    assert_common_fields(data, "DutyShift")
    assert isinstance(data.get("operation_id"), str)
    assert isinstance(data.get("deployment_id"), str)
    assert data.get("kind") in ["OPERATIONS", "SAFETY_WATCH", "LOGISTICS"]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data.get("status") in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert isinstance(data.get("incident_id"), str)
    assert "operation_id" in data
    assert "source_partner_id" in data
    assert isinstance(data.get("requester_name"), str) and len(data["requester_name"]) > 0
    assert data.get("hazard_kind") in [
        "TREE_REMOVAL", "MUCK_OUT", "TARPING", "DEBRIS", "STRUCTURAL",
    ]
    assert isinstance(data.get("vulnerable_resident"), bool)
    assert isinstance(data.get("municipality_sourced"), bool)
    assert data.get("status") in [
        "INTAKE", "TRIAGED", "SCHEDULED", "IN_PROGRESS", "BLOCKED",
        "DONE_PENDING_VERIFICATION", "VERIFIED_DONE", "CANCELLED",
    ]
    for field in ("priority_score", "priority_tier", "blocked_reason"):
        assert field in data, f"WorkOrder.{field} must be present (null until its transition)"


def assert_partner_agency(data: dict):
    assert_common_fields(data, "PartnerAgency")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("kind") in ["EMERGENCY_MANAGEMENT", "NONPROFIT", "LTRG"]
    assert isinstance(data.get("contact_email"), str) and len(data["contact_email"]) > 0


def assert_training_course(data: dict):
    assert_common_fields(data, "TrainingCourse")
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("grants_cert_kind") in ["CHAINSAW", "HEAVY_EQUIPMENT", "STRUCTURAL", "MEDICAL"]
    assert isinstance(data.get("capacity"), int) and data["capacity"] >= 1
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert isinstance(data.get("lead_instructor_volunteer_id"), str)
    assert isinstance(data.get("seats_taken"), int) and data["seats_taken"] >= 0


def assert_training_enrollment(data: dict):
    assert_common_fields(data, "TrainingEnrollment")
    assert isinstance(data.get("course_id"), str)
    assert isinstance(data.get("volunteer_id"), str)
    assert data.get("status") in ["ENROLLED", "WAITLISTED", "COMPLETED", "FAILED", "DROPPED"]
    assert "waitlist_position" in data


def assert_wellness_check(data: dict):
    assert_common_fields(data, "WellnessCheck")
    assert isinstance(data.get("deployment_id"), str)
    assert data.get("reason") in ["FATIGUE_THRESHOLD", "LONG_DEPLOYMENT"]
    assert data.get("status") in ["OPEN", "RESOLVED"]
    assert "resolved_notes" in data

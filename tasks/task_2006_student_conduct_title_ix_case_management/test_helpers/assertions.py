"""Entity assertions and domain invariant checkers.

Timestamp equality helpers parse ISO-8601 instants before comparing so the
assertion targets the instant (a PRD rule), not the serialization format.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 timestamp with optional fractional seconds and Z suffix."""
    assert isinstance(value, str), f"expected ISO-8601 string, got {type(value)}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO-8601 timestamps denote the same instant."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def stats_live_counts(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the live statistics computation from a statistics read.

    The PRD fixes the computation's member names (reports_received, dismissed,
    per_category, avg_resolution_days, ...); the live view is returned either
    nested under `counts` or flattened onto the read payload.
    """
    counts = data.get("counts")
    if isinstance(counts, dict):
        return counts
    return data


def assert_party_profile(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["university_id"], str) and data["university_id"]
    assert data["role_type"] in ["STUDENT", "EMPLOYEE", "FACULTY", "STAFF", "EXTERNAL"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["advisor_eligible"], bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("complainant_id", "")), "complainant_id must be a UUID"
    assert is_valid_uuid(data.get("respondent_id", "")), "respondent_id must be a UUID"
    assert is_valid_uuid(data.get("coordinator_id", "")), "coordinator_id must be a UUID"
    assert isinstance(data["categories"], list) and len(data["categories"]) > 0
    assert data["status"] in [
        "RECEIVED", "JURISDICTION_REVIEW", "AWAITING_FORMAL_COMPLAINT",
        "INVESTIGATION", "EVIDENCE_REVIEW", "HEARING_PREPARATION",
        "HEARING_IN_PROGRESS", "DELIBERATION", "DETERMINATION_ISSUED",
        "APPEAL_REVIEW", "REMANDED", "INFORMAL_RESOLUTION_IN_PROGRESS",
        "RESOLVED_INFORMAL", "DISMISSED", "REFERRED_TO_CONDUCT", "CLOSED",
    ]
    assert isinstance(data["formal_complaint_signed"], bool)
    assert data["standard_of_evidence"] in ["PREPONDERANCE", "CLEAR_AND_CONVINCING"]
    assert isinstance(data["active_supportive_measure_count"], int)
    assert isinstance(data["interim_suspension_eligible"], bool)
    assert isinstance(data["exposure_score"], int)
    assert isinstance(data["version"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_supportive_measure(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["measure_type"] in [
        "COUNSELING", "COURSE_ADJUSTMENT", "HOUSING_CHANGE", "SCHEDULE_CHANGE",
        "EXTENSION", "ESCORT", "SAFETY_PLAN", "OTHER",
    ]
    assert data["party_side"] in ["COMPLAINANT", "RESPONDENT", "BOTH"]
    assert data["status"] in ["ACTIVE", "TERMINATED", "EXPIRED"]
    assert data.get("is_confidential") is True
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_no_contact_directive(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["party_side"] in ["COMPLAINANT", "RESPONDENT", "MUTUAL"]
    assert isinstance(data["restrictions"], list) and len(data["restrictions"]) > 0
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "LIFTED", "EXPIRED"]
    assert isinstance(data["substantiated_violation_count"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_directive_violation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("directive_id", ""))
    assert data["reported_by_side"] in ["COMPLAINANT", "RESPONDENT", "STAFF"]
    assert data["status"] in ["PENDING", "SUBSTANTIATED", "UNSUBSTANTIATED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_investigator_assignment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("investigator_id", ""))
    assert data["status"] in ["PROPOSED", "ACTIVE", "DECLINED", "RECUSED", "COMPLETED"]


def assert_evidence_item(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["submitted_by_side"] in ["COMPLAINANT", "RESPONDENT", "INVESTIGATOR"]
    assert data["evidence_type"] in [
        "DOCUMENT", "PHOTO", "VIDEO", "MESSAGE_RECORD", "TESTIMONY_SUMMARY", "OTHER",
    ]
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "EXCLUDED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_evidence_packet(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["packet_sequence"], int) and data["packet_sequence"] >= 1
    assert data["status"] in [
        "DRAFT", "RELEASED_FOR_REVIEW", "REVIEW_CLOSED", "FINALIZED",
        "WITHDRAWN", "SUPERSEDED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_notice(data: dict):
    """Notice is an immutable record: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["notice_type"] in [
        "ALLEGATIONS", "INTERVIEW", "EVIDENCE_RELEASE", "HEARING", "DETERMINATION",
        "DISMISSAL", "APPEAL_FILED", "APPEAL_OUTCOME", "INFORMAL_PROPOSAL",
    ]
    assert data["recipient_side"] in ["COMPLAINANT", "RESPONDENT", "BOTH"]
    assert "version" not in data, "Notice must not carry version"
    assert "updated_at" not in data, "Notice must not carry updated_at"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("sent_at", ""))


def assert_advisor_appointment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("advisor_id", ""))
    assert data["party_side"] in ["COMPLAINANT", "RESPONDENT"]
    assert data["source"] in ["PARTY_SELECTED", "UNIVERSITY_APPOINTED"]
    assert data["status"] in ["ACTIVE", "WITHDRAWN", "REPLACED"]


def assert_hearing(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("decision_maker_id", ""))
    assert isinstance(data["estimated_duration_minutes"], int) and data["estimated_duration_minutes"] > 0
    assert data["modality"] in ["IN_PERSON", "VIRTUAL"]
    assert data["status"] in [
        "SCHEDULED", "IN_SESSION", "ADJOURNED", "DELIBERATION", "COMPLETED", "CANCELLED",
    ]


def assert_cross_exam_question(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("hearing_id", ""))
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["target_side"] in ["COMPLAINANT", "RESPONDENT"]
    assert data["ruling"] in ["PENDING", "ALLOWED", "DISALLOWED"]


def assert_determination(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["responsibility_finding"] in ["RESPONSIBLE", "NOT_RESPONSIBLE", "INSUFFICIENT_EVIDENCE"]
    assert data["standard_of_evidence"] in ["PREPONDERANCE", "CLEAR_AND_CONVINCING"]
    assert data["status"] in ["DRAFT", "ISSUED", "FINAL", "REVERSED", "SUPERSEDED"]
    assert isinstance(data["provisional_severity_score"], int)


def assert_sanction(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("determination_id", ""))
    assert data["sanction_type"] in [
        "WARNING", "PROBATION", "SUSPENSION", "EXPULSION",
        "EDUCATIONAL_PROGRAM", "NO_CONTACT_CONTINUATION", "RESTITUTION",
    ]
    assert data["status"] in ["ACTIVE", "COMPLETED", "STAYED", "LIFTED_ON_APPEAL"]
    assert isinstance(data["applied_restitution_cents"], int)


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["filed_by_side"] in ["COMPLAINANT", "RESPONDENT"]
    assert data["appeal_target"] in ["DETERMINATION", "DISMISSAL"]
    assert isinstance(data["grounds"], list) and len(data["grounds"]) > 0
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "AFFIRMED", "REVERSED", "REMANDED",
        "SANCTION_MODIFIED", "REINSTATED",
    ]


def assert_informal_resolution(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("facilitator_id", ""))
    assert data["status"] in ["PROPOSED", "IN_PROGRESS", "RESOLVED", "WITHDRAWN", "TERMINATED"]


def assert_case_event(data: dict):
    """CaseEvent is an immutable record: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert "version" not in data, "CaseEvent must not carry version"
    assert "updated_at" not in data, "CaseEvent must not carry updated_at"
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_case_exposure_invariants(case_data: dict):
    """Exposure score invariants from the PRD scoring rule."""
    assert case_data["exposure_score"] >= 0
    assert case_data["interim_suspension_eligible"] == (case_data["exposure_score"] >= 70)

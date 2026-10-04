"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Every resource carries id/created_at/updated_at/version without exception
(PRD §2.5), so each assert_{entity} checks the common fields plus the
entity's own declared fields and enum ranges.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    CandidateStatus, MembershipTier, SyllabusStatus, ExamStatus, WindowStatus,
    LogisticsStatus, GradingStatus, ExamResult, CancelReason, PassMarkStatus,
    VeeTopic, VeeStatus, TrackCode, EnrollmentStatus, AttemptStatus,
    ProjectStatus, ProjectResult, SessionStatus, AttendanceStatus, SourceBody,
    AgreementClass, TransferStatus, CpdStatus, CaseStatus, Resolution,
    Credential, ApplicationStatus, DeficiencyCode,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _in(value, enum_cls, field):
    assert value in {e.value for e in enum_cls}, f"{field} must be one of {[e.value for e in enum_cls]}, got {value!r}"


def assert_candidate(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"], "email required"
    assert isinstance(data["full_name"], str) and data["full_name"], "full_name required"
    _in(data["status"], CandidateStatus, "status")
    _in(data["membership_tier"], MembershipTier, "membership_tier")
    for f in ("suspended_until", "associate_admitted_at", "fellow_admitted_at", "last_evaluated_at"):
        assert data.get(f) is None or is_iso8601_timestamp(data[f]), f"{f} must be ISO 8601 or null"
    for f in ("earned_exam_credit_hours", "transfer_credit_hours", "total_credit_hours"):
        assert isinstance(data.get(f), int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_candidate_credit_totals(data: dict):
    """PRD §3.1: total_credit_hours == earned + transfer, recomputed on read."""
    assert data["total_credit_hours"] == data["earned_exam_credit_hours"] + data["transfer_credit_hours"], (
        f"total {data['total_credit_hours']} != earned {data['earned_exam_credit_hours']} "
        f"+ transfer {data['transfer_credit_hours']}"
    )


def assert_syllabus_version(data: dict):
    _assert_common(data)
    assert isinstance(data["version_code"], str) and data["version_code"], "version_code required"
    _in(data["status"], SyllabusStatus, "status")
    assert isinstance(data.get("credit_map"), dict), "credit_map must be an object"
    assert data.get("activated_at") is None or is_iso8601_timestamp(data["activated_at"])


def assert_exam(data: dict):
    _assert_common(data)
    assert isinstance(data["exam_code"], str) and data["exam_code"], "exam_code required"
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] >= 1, "credit_hours >= 1"
    assert isinstance(data.get("is_prelim"), bool), "is_prelim must be boolean"
    assert data.get("prerequisite_exam_id") is None or is_valid_uuid(data["prerequisite_exam_id"])
    assert is_valid_uuid(data.get("syllabus_version_id", "")), "syllabus_version_id must be a UUID"
    _in(data["status"], ExamStatus, "status")


def assert_exam_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("exam_id", "")), "exam_id must be a UUID"
    assert isinstance(data["window_code"], str) and data["window_code"], "window_code required"
    for f in ("registration_opens_at", "registration_deadline", "testing_starts_at", "testing_ends_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"{f} must be ISO 8601"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1, "capacity >= 1"
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["late_surcharge_cents"], int) and data["late_surcharge_cents"] >= 0
    _in(data["status"], WindowStatus, "status")
    assert_window_seat_invariants(data)


def assert_window_seat_invariants(data: dict):
    """PRD §3.3: seats_held is the count of REGISTERED rows; waitlist_count the
    count of WAITLISTED rows; both non-negative and seats_held <= capacity."""
    assert isinstance(data.get("seats_held"), int) and data["seats_held"] >= 0
    assert isinstance(data.get("waitlist_count"), int) and data["waitlist_count"] >= 0
    assert data["seats_held"] <= data["capacity"], (
        f"seats_held {data['seats_held']} exceeds capacity {data['capacity']}"
    )


def assert_exam_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    assert is_valid_uuid(data.get("exam_window_id", "")), "exam_window_id must be a UUID"
    _in(data["logistics_status"], LogisticsStatus, "logistics_status")
    _in(data["grading_status"], GradingStatus, "grading_status")
    if data.get("raw_score") is not None:
        assert isinstance(data["raw_score"], int) and 0 <= data["raw_score"] <= 60, "raw_score 0..60"
    if data.get("scaled_score") is not None:
        assert isinstance(data["scaled_score"], (int, float)), "scaled_score numeric"
    if data.get("result") is not None:
        _in(data["result"], ExamResult, "result")
    if data.get("projected_result") is not None:
        _in(data["projected_result"], ExamResult, "projected_result")
    if data.get("fee_charged_cents") is not None:
        assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
    if data.get("refund_cents") is not None:
        assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    if data.get("cancel_reason") is not None:
        _in(data["cancel_reason"], CancelReason, "cancel_reason")
    assert data.get("sat_at") is None or is_iso8601_timestamp(data["sat_at"])


def assert_pass_mark_setting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("exam_window_id", "")), "exam_window_id must be a UUID"
    assert isinstance(data["proposed_mark"], (int, float)) and 0 <= data["proposed_mark"] <= 10
    if data.get("ratified_mark") is not None:
        assert isinstance(data["ratified_mark"], (int, float)) and 0 <= data["ratified_mark"] <= 10
    _in(data["status"], PassMarkStatus, "status")


def assert_vee_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    _in(data["topic"], VeeTopic, "topic")
    assert isinstance(data["university"], str) and data["university"]
    assert isinstance(data["course_title"], str) and data["course_title"]
    assert isinstance(data["grade_points"], (int, float)) and 0.0 <= data["grade_points"] <= 4.0
    _in(data["status"], VeeStatus, "status")
    assert data.get("reviewed_at") is None or is_iso8601_timestamp(data["reviewed_at"])


def assert_track_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    _in(data["track_code"], TrackCode, "track_code")
    _in(data["status"], EnrollmentStatus, "status")
    assert isinstance(data.get("modules_passed_count"), int) and data["modules_passed_count"] >= 0
    assert isinstance(data.get("completion_pct"), (int, float)), "completion_pct numeric"
    assert 0 <= data["completion_pct"] <= 100, "completion_pct within 0..100"


def assert_module(data: dict):
    _assert_common(data)
    assert isinstance(data["module_code"], str) and data["module_code"]
    _in(data["track_code"], TrackCode, "track_code")
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data.get("is_capstone"), bool), "is_capstone must be boolean"
    assert isinstance(data["passing_score"], int) and 1 <= data["passing_score"] <= 100
    assert isinstance(data["cooldown_days"], int) and data["cooldown_days"] >= 0


def assert_module_attempt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("track_enrollment_id", "")), "track_enrollment_id must be a UUID"
    assert is_valid_uuid(data.get("module_id", "")), "module_id must be a UUID"
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    _in(data["status"], AttemptStatus, "status")
    if data.get("score") is not None:
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])


def assert_project_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    assert is_valid_uuid(data.get("track_enrollment_id", "")), "track_enrollment_id must be a UUID"
    _in(data["status"], ProjectStatus, "status")
    assert isinstance(data.get("grader_ids"), list), "grader_ids list"
    assert isinstance(data.get("scores"), list), "scores list"
    assert len(data["grader_ids"]) == len(data["scores"]), "grader_ids and scores stay parallel"
    if data.get("final_score") is not None:
        assert isinstance(data["final_score"], int) and 0 <= data["final_score"] <= 100
    if data.get("result") is not None:
        _in(data["result"], ProjectResult, "result")


def assert_course_session(data: dict):
    _assert_common(data)
    assert isinstance(data["session_code"], str) and data["session_code"]
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at ISO 8601"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    _in(data["status"], SessionStatus, "status")
    assert isinstance(data.get("attendance_booked"), int) and 0 <= data["attendance_booked"] <= data["capacity"]


def assert_course_attendance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("course_session_id", "")), "course_session_id must be a UUID"
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    _in(data["status"], AttendanceStatus, "status")
    assert data.get("verified_at") is None or is_iso8601_timestamp(data["verified_at"])


def assert_transfer_credit_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    _in(data["source_body"], SourceBody, "source_body")
    assert isinstance(data["claimed_hours"], int) and data["claimed_hours"] >= 1
    _in(data["agreement_class"], AgreementClass, "agreement_class")
    assert isinstance(data["granted_hours"], int) and data["granted_hours"] >= 0
    _in(data["status"], TransferStatus, "status")


def assert_cpd_attestation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["attested_hours"], (int, float)) and data["attested_hours"] >= 0
    assert isinstance(data["carryover_hours"], int) and data["carryover_hours"] >= 0
    assert isinstance(data["required_hours"], int) and data["required_hours"] >= 0
    if data.get("verified_hours") is not None:
        assert isinstance(data["verified_hours"], (int, float)) and data["verified_hours"] >= 0
    _in(data["status"], CpdStatus, "status")
    assert data.get("verified_at") is None or is_iso8601_timestamp(data["verified_at"])


def assert_discipline_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    assert isinstance(data["charge"], str) and data["charge"]
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 10
    _in(data["status"], CaseStatus, "status")
    if data.get("resolution") is not None:
        _in(data["resolution"], Resolution, "resolution")
    assert data.get("resolved_at") is None or is_iso8601_timestamp(data["resolved_at"])
    assert data.get("suspended_until") is None or is_iso8601_timestamp(data["suspended_until"])


def assert_credential_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    _in(data["credential"], Credential, "credential")
    _in(data["status"], ApplicationStatus, "status")
    assert isinstance(data.get("deficiency_codes"), list), "deficiency_codes list"
    valid = {e.value for e in DeficiencyCode}
    for code in data["deficiency_codes"]:
        assert code in valid, f"unknown deficiency code {code!r}"
    assert is_iso8601_timestamp(data.get("evaluated_at", "")), "evaluated_at ISO 8601"

"""Entity assertions and domain invariant checkers.

`assert_<entity>(data)` validates the structural contract of a returned
resource: id/timestamp formats, required field presence and types, and status
enum membership. Value-level claims (exact fees, exact credited hours) belong
in the tests themselves.

Configuration resources (LevelDefinition, StateAdoptionPolicy) carry only
`id` and `created_at` (PRD §2.4); operational resources additionally carry
`updated_at` and `version`.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AccreditationStatus,
    AdministeredBy,
    AdoptionMode,
    AuditReason,
    CandidateStatus,
    CECreditEntryStatus,
    CEComponent,
    CertificationStatus,
    CognitiveExamAttemptStatus,
    CompletionRecordStatus,
    DeliveryMethod,
    DisciplinaryCaseStatus,
    ExamApplicationStatus,
    AuthorizationToTestStatus,
    ExamOutcome,
    InterimAction,
    LevelCode,
    LicenseApplicationStatus,
    LicensePath,
    PsychomotorStatus,
    RecertApplicationStatus,
    RecertModel,
    ReentryApplicationStatus,
    ReentryTier,
    SanctionType,
    StateExamRecordStatus,
    ViolationType,
)

_ENUM_VALUES = lambda e: [m.value for m in e]


def _assert_common_config(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} is a config resource: updated_at must be absent"
    assert "version" not in data, f"{label} is a config resource: version must be absent"


def _assert_common_operational(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_optional_ts(data: dict, field: str, label: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), f"{label}.{field} must be ISO 8601 when set"


# ---------------------------------------------------------------------------
# Configuration resources
# ---------------------------------------------------------------------------
def assert_level_definition(data: dict):
    _assert_common_config(data, "LevelDefinition")
    assert data["code"] in _ENUM_VALUES(LevelCode)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["scope_summary"], str)
    for f in ("cognitive_cut_score", "ce_total_hours", "ce_national_min_hours",
              "ce_local_min_hours", "ce_individual_min_hours", "hourly_model_total_hours",
              "remedial_hours_required", "refresher_hours_required"):
        assert isinstance(data[f], (int, float)), f"LevelDefinition.{f} must be numeric"
    assert 0 <= data["cognitive_cut_score"] <= 1, "cut score is a 0..1 theta threshold"
    for f in ("initial_application_fee_cents", "recert_application_fee_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"LevelDefinition.{f} must be integer cents"


def assert_state_adoption_policy(data: dict):
    _assert_common_config(data, "StateAdoptionPolicy")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["adoption_mode"] in _ENUM_VALUES(AdoptionMode)
    assert isinstance(data["base_license_fee_cents"], int) and data["base_license_fee_cents"] >= 0
    assert isinstance(data["registry_share_bps"], int) and data["registry_share_bps"] >= 0
    assert isinstance(data["jurisprudence_exam_required"], bool)


# ---------------------------------------------------------------------------
# Operational resources
# ---------------------------------------------------------------------------
def assert_candidate(data: dict):
    _assert_common_operational(data, "Candidate")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in _ENUM_VALUES(CandidateStatus)
    assert isinstance(data["disciplinary_hold"], bool)


def assert_education_program(data: dict):
    _assert_common_operational(data, "EducationProgram")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data["level_id"])
    assert isinstance(data["director_user_id"], str) and data["director_user_id"]
    assert data["accreditation_status"] in _ENUM_VALUES(AccreditationStatus)
    history = data["accreditation_history"]
    assert isinstance(history, list) and len(history) >= 1, "history seeds entry 0 at creation"
    for entry in history:
        assert entry["to_status"] in _ENUM_VALUES(AccreditationStatus)
        assert is_iso8601_timestamp(entry["effective_date"])
        assert is_iso8601_timestamp(entry["recorded_at"])


def assert_program_completion_record(data: dict):
    _assert_common_operational(data, "ProgramCompletionRecord")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["completion_date"], str) and data["completion_date"]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in _ENUM_VALUES(CompletionRecordStatus)
    _assert_optional_ts(data, "verified_at", "ProgramCompletionRecord")
    assert isinstance(data["within_validity_window"], bool)
    assert isinstance(data["attempts_consumed"], int) and data["attempts_consumed"] >= 0
    assert isinstance(data["attempts_remaining"], int)
    assert data.get("invalidated_by_case_id") is None or is_valid_uuid(data["invalidated_by_case_id"])


def assert_attempt_budget_invariant(record: dict):
    """attempts_consumed + attempts_remaining == 6; NO_SHOW/VOIDED never count."""
    assert record["attempts_consumed"] + record["attempts_remaining"] == 6, (
        f"budget invariant broken: {record['attempts_consumed']} + "
        f"{record['attempts_remaining']} != 6"
    )


def assert_exam_application(data: dict):
    _assert_common_operational(data, "ExamApplication")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["level_id"])
    assert is_valid_uuid(data["completion_record_id"])
    assert isinstance(data["application_fee_cents"], int) and data["application_fee_cents"] >= 0
    assert data["status"] in _ENUM_VALUES(ExamApplicationStatus)
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)
    _assert_optional_ts(data, "decided_at", "ExamApplication")
    assert data.get("att_id") is None or is_valid_uuid(data["att_id"])
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0


def assert_authorization_to_test(data: dict):
    _assert_common_operational(data, "AuthorizationToTest")
    assert is_valid_uuid(data["exam_application_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_iso8601_timestamp(data["issued_on"])
    assert is_iso8601_timestamp(data["expires_on"])
    assert data.get("attempt_id") is None or is_valid_uuid(data["attempt_id"])
    assert data["status"] in _ENUM_VALUES(AuthorizationToTestStatus)


def assert_cognitive_exam_attempt(data: dict):
    _assert_common_operational(data, "CognitiveExamAttempt")
    assert is_valid_uuid(data["att_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["level_id"])
    assert is_valid_uuid(data["basis_completion_record_id"])
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["scheduled_end"] > data["scheduled_start"], "window end strictly after start"
    _assert_optional_ts(data, "delivered_at", "CognitiveExamAttempt")
    if data.get("provisional_outcome") is not None:
        assert data["provisional_outcome"] in _ENUM_VALUES(ExamOutcome)
    if data.get("final_outcome") is not None:
        assert data["final_outcome"] in _ENUM_VALUES(ExamOutcome)
    if data.get("items_delivered_count") is not None:
        assert isinstance(data["items_delivered_count"], int) and data["items_delivered_count"] >= 1
    if data.get("theta_final") is not None:
        assert isinstance(data["theta_final"], (int, float))
        assert 0 <= data["theta_final"] <= 1
    assert data["status"] in _ENUM_VALUES(CognitiveExamAttemptStatus)
    assert data.get("voided_by_case_id") is None or is_valid_uuid(data["voided_by_case_id"])


def assert_remedial_education_record(data: dict):
    _assert_common_operational(data, "RemedialEducationRecord")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["level_id"])
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert isinstance(data["completed_date"], str) and data["completed_date"]
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["attested_by_user_id"], str) and data["attested_by_user_id"]


def assert_psychomotor_verification(data: dict):
    _assert_common_operational(data, "PsychomotorVerification")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["level_id"])
    assert data["administered_by"] in _ENUM_VALUES(AdministeredBy)
    if data["administered_by"] == AdministeredBy.PROGRAM.value:
        assert data.get("program_id") is not None and is_valid_uuid(data["program_id"])
    else:
        assert data.get("program_id") is None, "STATE-administered records carry no program_id"
    assert isinstance(data["evaluator_user_id"], str) and data["evaluator_user_id"]
    assert is_valid_uuid(data["completion_record_id"])
    assert isinstance(data["exam_date"], str) and data["exam_date"]
    stations = data["stations"]
    assert isinstance(stations, list) and len(stations) >= 1, "stations must be non-empty"
    for s in stations:
        assert isinstance(s["station_code"], str) and s["station_code"]
        assert isinstance(s["passed"], bool)
    assert isinstance(data["documentation_attached"], bool)
    assert data["status"] in _ENUM_VALUES(PsychomotorStatus)
    _assert_optional_ts(data, "verified_at", "PsychomotorVerification")


def assert_certification(data: dict):
    _assert_common_operational(data, "Certification")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["level_id"])
    assert is_valid_uuid(data["basis_completion_record_id"])
    assert is_valid_uuid(data["basis_attempt_id"])
    assert is_valid_uuid(data["basis_psychomotor_id"])
    assert is_iso8601_timestamp(data["issued_on"])
    assert is_iso8601_timestamp(data["expires_on"])
    assert is_iso8601_timestamp(data["lapse_deadline"])
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0
    assert data["status"] in _ENUM_VALUES(CertificationStatus)
    _assert_optional_ts(data, "suspension_ends", "Certification")
    assert data.get("pre_sanction_status") is None or (
        data["pre_sanction_status"] in _ENUM_VALUES(CertificationStatus)
    )
    assert data.get("revoked_by_case_id") is None or is_valid_uuid(data["revoked_by_case_id"])


def assert_recert_application(data: dict):
    _assert_common_operational(data, "RecertApplication")
    assert is_valid_uuid(data["certification_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert data["model"] in _ENUM_VALUES(RecertModel)
    assert is_iso8601_timestamp(data["cycle_window_start"])
    assert is_iso8601_timestamp(data["cert_expires_on_at_creation"])
    assert data["status"] in _ENUM_VALUES(RecertApplicationStatus)
    _assert_optional_ts(data, "submitted_at", "RecertApplication")
    _assert_optional_ts(data, "decided_at", "RecertApplication")
    if data.get("recert_seq") is not None:
        assert isinstance(data["recert_seq"], int) and data["recert_seq"] >= 1
    if data.get("audit_selected") is not None:
        assert isinstance(data["audit_selected"], bool)
    if data.get("audit_reasons") is not None:
        for reason in data["audit_reasons"]:
            assert reason in _ENUM_VALUES(AuditReason)
    for f in ("national_credited_hours", "local_credited_hours",
              "individual_credited_hours", "total_credited_hours"):
        if data.get(f) is not None:
            assert isinstance(data[f], (int, float)) and data[f] >= 0, f"{f} must be non-negative"


def assert_ce_credit_entry(data: dict):
    _assert_common_operational(data, "CECreditEntry")
    assert is_valid_uuid(data["recert_application_id"])
    assert data["component"] in _ENUM_VALUES(CEComponent)
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert data["delivery_method"] in _ENUM_VALUES(DeliveryMethod)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["course_date"], str) and data["course_date"]
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["status"] in _ENUM_VALUES(CECreditEntryStatus)
    assert data.get("reject_reason") is None or isinstance(data["reject_reason"], str)


def assert_reentry_application(data: dict):
    _assert_common_operational(data, "ReentryApplication")
    assert is_valid_uuid(data["certification_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["lapse_months_at_submission"], (int, float))
    assert data["lapse_months_at_submission"] >= 0
    assert data["tier"] in _ENUM_VALUES(ReentryTier)
    if data.get("ce_makeup_hours_claimed") is not None:
        assert isinstance(data["ce_makeup_hours_claimed"], (int, float))
    if data.get("refresher_hours_claimed") is not None:
        assert isinstance(data["refresher_hours_claimed"], (int, float))
    assert data["status"] in _ENUM_VALUES(ReentryApplicationStatus)
    _assert_optional_ts(data, "decided_at", "ReentryApplication")


def assert_license_application(data: dict):
    _assert_common_operational(data, "LicenseApplication")
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_valid_uuid(data["level_id"])
    assert is_valid_uuid(data["policy_id"])
    assert data["adoption_mode_snapshot"] in _ENUM_VALUES(AdoptionMode)
    assert isinstance(data["registry_share_bps_snapshot"], int)
    assert isinstance(data["fee_lines_snapshot"], list)
    assert data["path"] in _ENUM_VALUES(LicensePath)
    assert data.get("certification_id") is None or is_valid_uuid(data["certification_id"])
    if data.get("certification_version_at_submission") is not None:
        assert isinstance(data["certification_version_at_submission"], int)
    assert data.get("state_exam_record_id") is None or is_valid_uuid(data["state_exam_record_id"])
    assert isinstance(data["jurisprudence_completed"], bool)
    for f in ("assessed_fee_cents", "registry_share_cents"):
        if data.get(f) is not None:
            assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be integer cents"
    assert data["status"] in _ENUM_VALUES(LicenseApplicationStatus)
    assert data.get("decision_reason") is None or isinstance(data["decision_reason"], str)
    assert data.get("more_info_note") is None or isinstance(data["more_info_note"], str)
    _assert_optional_ts(data, "granted_on", "LicenseApplication")


def assert_state_exam_record(data: dict):
    _assert_common_operational(data, "StateExamRecord")
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_valid_uuid(data["level_id"])
    assert isinstance(data["exam_date"], str) and data["exam_date"]
    assert isinstance(data["score"], (int, float))
    assert isinstance(data["passing_score"], (int, float))
    assert isinstance(data["passed"], bool)
    assert data["status"] in _ENUM_VALUES(StateExamRecordStatus)
    assert data.get("voided_by_case_id") is None or is_valid_uuid(data["voided_by_case_id"])


def assert_state_exam_passed_computed(data: dict):
    """passed == (score >= passing_score) — the record's only computed flag."""
    assert data["passed"] == bool(data["score"] >= data["passing_score"]), (
        f"passed flag {data['passed']} contradicts score {data['score']} "
        f"vs passing_score {data['passing_score']}"
    )


def assert_disciplinary_case(data: dict):
    _assert_common_operational(data, "DisciplinaryCase")
    assert is_valid_uuid(data["subject_candidate_id"])
    assert data["violation_type"] in _ENUM_VALUES(ViolationType)
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["interim_action"] in _ENUM_VALUES(InterimAction)
    for f in ("implicated_attempt_ids", "implicated_completion_record_ids"):
        if data.get(f) is not None:
            assert isinstance(data[f], list)
    assert data.get("hearing_officer_user_id") is None or isinstance(data["hearing_officer_user_id"], str)
    if data.get("sanction_type") is not None:
        assert data["sanction_type"] in _ENUM_VALUES(SanctionType)
    assert data.get("findings") is None or isinstance(data["findings"], str)
    _assert_optional_ts(data, "response_deadline", "DisciplinaryCase")
    _assert_optional_ts(data, "appeal_deadline", "DisciplinaryCase")
    _assert_optional_ts(data, "decided_at", "DisciplinaryCase")
    _assert_optional_ts(data, "finalized_at", "DisciplinaryCase")
    assert isinstance(data["rehearing_count"], int) and data["rehearing_count"] >= 0
    assert data["status"] in _ENUM_VALUES(DisciplinaryCaseStatus)


def assert_clock_response(data: dict):
    """Clock sweep response: current_utc plus the seven per-step counters."""
    assert is_iso8601_timestamp(data["current_utc"])
    for f in ("att_expired_count", "attempts_no_show_count", "certifications_lapsed_count",
              "certifications_expired_count", "suspensions_lifted_count",
              "cases_advanced_count", "cases_finalized_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"clock response {f} must be a non-negative int"

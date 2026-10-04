"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AcceptingState,
    AppliesTo,
    AssessmentState,
    ConfidenceBand,
    ConsentEnforcement,
    ConsentStatus,
    DepositScope,
    DepositState,
    GradeState,
    InstructorInterpretation,
    IntegrationStatus,
    MatchCategory,
    PipelineState,
    PolicyState,
    ReportState,
    ReportVisibility,
    RepositoryOption,
    RepositoryParticipation,
    ResidencyRegion,
    SourceStatus,
    SourceType,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be int >= 1"


def assert_institution(data: dict):
    _assert_common(data, "Institution")
    assert isinstance(data["name"], str) and data["name"]
    assert data["residency_region"] in [r.value for r in ResidencyRegion]
    assert data["repository_participation"] in [r.value for r in RepositoryParticipation]
    assert isinstance(data["cross_institution_comparison_enabled"], bool)
    assert isinstance(data["ai_detection_enabled"], bool)
    assert isinstance(data["data_residency_locked"], bool)
    assert isinstance(data["comparable_submission_count"], int)
    assert data["comparable_submission_count"] >= 0


def assert_lms_integration(data: dict):
    _assert_common(data, "LmsIntegration")
    assert data["provider"] in ["CANVAS", "BLACKBOARD", "MOODLE", "CUSTOM_API"]
    assert isinstance(data["external_key"], str)
    assert data["status"] in [s.value for s in IntegrationStatus]
    assert data["consent_enforcement"] in [c.value for c in ConsentEnforcement]


def assert_instructor(data: dict):
    _assert_common(data, "Instructor")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_student(data: dict):
    _assert_common(data, "Student")
    assert isinstance(data["external_lms_id"], str)
    assert isinstance(data["email"], str)
    assert data["home_region"] in [r.value for r in ResidencyRegion]
    assert data["consent_status"] in [c.value for c in ConsentStatus]


def assert_assignment(data: dict):
    _assert_common(data, "Assignment")
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["due_at"])
    assert data["accepting_state"] in [s.value for s in AcceptingState]
    assert data["report_visibility"] in [s.value for s in ReportVisibility]
    assert data["repository_option"] in [s.value for s in RepositoryOption]
    assert isinstance(data["exclude_quotes"], bool)
    assert isinstance(data["exclude_bibliography"], bool)
    assert isinstance(data["exclude_small_matches"], bool)
    assert isinstance(data["small_match_threshold_words"], int)
    assert 1 <= data["small_match_threshold_words"] <= 32
    assert isinstance(data["max_submissions_per_student"], int)
    assert 1 <= data["max_submissions_per_student"] <= 10
    assert isinstance(data["submission_count"], int)
    assert data["submission_count"] >= 0


def assert_submission(data: dict):
    _assert_common(data, "Submission")
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["content_text"], str)
    assert isinstance(data["word_count"], int) and data["word_count"] >= 1
    assert data["pipeline_state"] in [s.value for s in PipelineState]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_source_document(data: dict):
    _assert_common(data, "SourceDocument")
    assert data["source_type"] in [s.value for s in SourceType]
    assert isinstance(data["uri"], str) and data["uri"]
    assert data["region"] in [r.value for r in ResidencyRegion]
    assert data["status"] in [s.value for s in SourceStatus]


def assert_match_fragment(data: dict):
    """MatchFragment carries only id + created_at (PRD §2.4): updated_at and
    version are absent from it entirely."""
    assert is_valid_uuid(data.get("id", "")), "MatchFragment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MatchFragment.created_at must be ISO 8601"
    assert "version" not in data, "MatchFragment must not carry a version field"
    assert "updated_at" not in data, "MatchFragment must not carry an updated_at field"
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["source_document_id"])
    assert isinstance(data["matched_word_count"], int) and data["matched_word_count"] >= 1
    assert data["match_category"] in [c.value for c in MatchCategory]
    assert isinstance(data["offset_start"], int) and data["offset_start"] >= 0
    assert isinstance(data["weighted_words"], int) and data["weighted_words"] >= 0
    assert isinstance(data["excluded"], bool)


def assert_similarity_report(data: dict):
    _assert_common(data, "SimilarityReport")
    assert is_valid_uuid(data["submission_id"])
    assert isinstance(data["raw_score_bps"], int) and 0 <= data["raw_score_bps"] <= 10000
    assert isinstance(data["filtered_score_bps"], int) and 0 <= data["filtered_score_bps"] <= 10000
    assert isinstance(data["exclusion_snapshot"], dict)
    assert data["report_state"] in [s.value for s in ReportState]


def assert_ai_assessment(data: dict):
    _assert_common(data, "AiWritingAssessment")
    assert is_valid_uuid(data["submission_id"])
    assert data["assessment_state"] in [s.value for s in AssessmentState]
    if data["assessment_state"] == "COMPLETE":
        assert isinstance(data["ai_score_bps"], int) and 0 <= data["ai_score_bps"] <= 10000
        assert data["confidence_band"] in [b.value for b in ConfidenceBand]
        assert isinstance(data["conservative_score_bps"], int) and 0 <= data["conservative_score_bps"] <= 10000


def assert_repository_deposit(data: dict):
    _assert_common(data, "RepositoryDeposit")
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["institution_id"])
    assert data["scope"] in [s.value for s in DepositScope]
    assert data["deposit_state"] in [s.value for s in DepositState]
    assert is_iso8601_timestamp(data["stored_at"])


def assert_retention_policy(data: dict):
    _assert_common(data, "DataRetentionPolicy")
    assert data["region"] in [r.value for r in ResidencyRegion]
    assert data["applies_to"] in [a.value for a in AppliesTo]
    assert is_iso8601_timestamp(data["retention_start"])
    assert is_iso8601_timestamp(data["retention_end"])
    assert data["policy_state"] in [s.value for s in PolicyState]


def assert_grade_entry(data: dict):
    _assert_common(data, "GradeEntry")
    assert is_valid_uuid(data["submission_id"])
    assert data["grade_state"] in [s.value for s in GradeState]
    assert isinstance(data["pinned_report_version"], int) and data["pinned_report_version"] >= 1
    assert data["score_points"] >= 0

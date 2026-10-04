"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ApplicationStatus,
    CapOrigin,
    CapStatus,
    CredentialLevel,
    EditionStatus,
    ElementCategory,
    EvidenceStatus,
    HealthPlanStatus,
    OutcomeStatus,
    ProductLine,
    QuestionStatus,
    ReportStatus,
    SampleStatus,
    SampleType,
    ScoreStatus,
    ScoringBasis,
    SessionStatus,
    SurveyMode,
    SurveyStatus,
    SurveyType,
    TimelinessBasis,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_health_plan(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("plan_code"), str) and data["plan_code"]
    assert data.get("status") in [s.value for s in HealthPlanStatus]


def assert_product_line_scope(data: dict):
    _assert_common(data)
    assert isinstance(data.get("health_plan_id"), str)
    assert data.get("product_line") in [p.value for p in ProductLine]
    assert isinstance(data.get("state_codes"), list) and len(data["state_codes"]) >= 1
    assert isinstance(data.get("member_count"), int) and data["member_count"] >= 1


def assert_standards_edition(data: dict):
    _assert_common(data)
    assert isinstance(data.get("edition_year"), int)
    assert isinstance(data.get("min_file_sample_per_category"), int)
    assert isinstance(data.get("timeliness_threshold"), (int, float))
    assert data.get("status") in [s.value for s in EditionStatus]


def assert_standard_element(data: dict):
    _assert_common(data)
    assert isinstance(data.get("standards_edition_id"), str)
    assert isinstance(data.get("element_code"), str) and data["element_code"]
    assert data.get("category") in [c.value for c in ElementCategory]
    assert isinstance(data.get("max_points"), int) and data["max_points"] >= 1
    assert isinstance(data.get("is_must_pass"), bool)
    assert isinstance(data.get("evidence_required_count"), int)


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data.get("health_plan_id"), str)
    assert isinstance(data.get("product_line_scope_id"), str)
    assert isinstance(data.get("standards_edition_id"), str)
    assert data.get("status") in [s.value for s in ApplicationStatus]
    assert isinstance(data.get("total_awarded_points"), (int, float))
    assert isinstance(data.get("total_forfeited_points"), (int, float))


def assert_evidence_item(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("standard_element_id"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("revision_count"), int)
    assert data.get("status") in [s.value for s in EvidenceStatus]


def assert_file_review_sample(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert data.get("sample_type") in [s.value for s in SampleType]
    assert data.get("category") in [c.value for c in ElementCategory]
    assert isinstance(data.get("required_size"), int)
    assert data.get("timeliness_basis") in [b.value for b in TimelinessBasis]
    assert isinstance(data.get("timely_case_count"), int)
    assert data.get("timeliness_rate") is None or isinstance(data["timeliness_rate"], (int, float))
    assert isinstance(data.get("must_pass_threshold_breached"), bool)
    assert data.get("status") in [s.value for s in SampleStatus]


def assert_file_review_case(data: dict):
    _assert_common(data)
    assert isinstance(data.get("file_review_sample_id"), str)
    assert isinstance(data.get("case_reference"), str)
    assert isinstance(data.get("required_turnaround_days"), int)


def assert_survey(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert data.get("survey_type") in [t.value for t in SurveyType]
    assert data.get("mode") in [m.value for m in SurveyMode]
    assert isinstance(data.get("budgeted_surveyor_hours"), int)
    for f in ("scheduled_minutes", "completed_minutes", "cancelled_minutes", "active_minutes"):
        assert isinstance(data.get(f), int)
    assert data.get("frozen_cap_closure_rate") is None or isinstance(data["frozen_cap_closure_rate"], (int, float))
    assert data.get("status") in [s.value for s in SurveyStatus]


def assert_survey_session(data: dict):
    _assert_common(data)
    assert isinstance(data.get("survey_id"), str)
    assert isinstance(data.get("surveyor_id"), str)
    assert isinstance(data.get("duration_minutes"), int)
    assert isinstance(data.get("is_onsite"), bool)
    assert data.get("status") in [s.value for s in SessionStatus]


def assert_surveyor(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("credential_level") in [c.value for c in CredentialLevel]
    assert data.get("active") is True


def assert_surveyor_question(data: dict):
    _assert_common(data)
    assert isinstance(data.get("survey_session_id"), str)
    assert isinstance(data.get("standard_element_id"), str)
    assert isinstance(data.get("question_text"), str)
    assert isinstance(data.get("raises_gap"), bool)
    assert data.get("status") in [s.value for s in QuestionStatus]


def assert_element_score(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("standard_element_id"), str)
    assert data.get("scoring_basis") in [b.value for b in ScoringBasis]
    assert data.get("sample_rate_used") is None or isinstance(data["sample_rate_used"], (int, float))
    assert isinstance(data.get("evidence_count_used"), int)
    assert isinstance(data.get("gap_count_used"), int)
    assert isinstance(data.get("awarded_points"), (int, float))
    assert isinstance(data.get("forfeited_points"), (int, float))
    assert_cost_precision(data["awarded_points"])
    assert_cost_precision(data["forfeited_points"])
    assert data.get("status") in [s.value for s in ScoreStatus]


def assert_quality_measure_result(data: dict):
    _assert_common(data)
    assert isinstance(data.get("product_line_scope_id"), str)
    assert isinstance(data.get("measure_code"), str)
    assert isinstance(data.get("measurement_year"), int)
    assert isinstance(data.get("percentile"), int) and 0 <= data["percentile"] <= 100
    assert isinstance(data.get("is_reportable"), bool)


def assert_consumer_survey_score(data: dict):
    _assert_common(data)
    assert isinstance(data.get("product_line_scope_id"), str)
    assert isinstance(data.get("survey_year"), int)
    assert isinstance(data.get("composite_score"), (int, float))
    assert isinstance(data.get("response_count"), int) and data["response_count"] >= 1


def assert_corrective_action_plan(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("standard_element_id"), str)
    assert data.get("origin") in [o.value for o in CapOrigin]
    assert data.get("status") in [s.value for s in CapStatus]


def assert_outcome(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("composite_score"), (int, float))
    assert isinstance(data.get("measure_bonus"), (int, float))
    assert isinstance(data.get("must_pass_failure_count"), int)
    assert data.get("status") in [s.value for s in OutcomeStatus]
    assert isinstance(data.get("decision_sequence"), int)
    assert isinstance(data.get("published"), bool)
    assert isinstance(data.get("is_publicly_displayed"), bool)


def assert_annual_report(data: dict):
    _assert_common(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("reporting_year"), int)
    assert isinstance(data.get("attestation"), str)
    assert isinstance(data.get("is_late"), bool)
    assert data.get("status") in [s.value for s in ReportStatus]


def assert_element_score_invariants(data: dict, max_points: float):
    """Domain invariants that must hold for any element score (PRD §3.7)."""
    assert abs(data["awarded_points"] + data["forfeited_points"] - max_points) < 1e-9, (
        "awarded_points + forfeited_points must equal max_points"
    )
    assert data["awarded_points"] >= 0
    assert data["awarded_points"] <= max_points


def assert_survey_minutes_invariants(data: dict):
    """Minute reconciliation invariants (PRD §3.5): active == scheduled + completed."""
    assert data["active_minutes"] == data["scheduled_minutes"] + data["completed_minutes"]
    for f in ("scheduled_minutes", "completed_minutes", "cancelled_minutes", "active_minutes"):
        assert data[f] >= 0

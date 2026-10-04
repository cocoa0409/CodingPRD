"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ACCREDITATION_STATUSES = {"PROSPECTIVE", "CANDIDATE", "ACCREDITED", "DENIED_ENTRY", "WITHDRAWN"}
_SANCTION_STATUSES = {"NONE", "NOTICE", "PROBATION", "SHOW_CAUSE", "MEMBERSHIP_REMOVED"}
_LEGAL_STATUSES = {"PUBLIC", "PRIVATE_NONPROFIT", "PRIVATE_FORPROFIT"}
_DEGREE_LEVELS = {"ASSOCIATE", "BACCALAUREATE", "MASTERS", "DOCTORAL"}
_PATHWAYS = {"STANDARD", "ACCELERATED"}
_APPLICATION_STATUSES = {"DRAFT", "FILED", "DEFICIENT", "APPROVED", "DENIED"}
_CYCLE_TYPES = {"INITIAL_ACCREDITATION", "REAFFIRMATION"}
_CYCLE_STATUSES = {
    "SCHEDULED", "MATERIALS_OPEN", "EVALUATION_ACTIVE",
    "VISIT_COMPLETE", "PANEL_REVIEW", "DECIDED", "CLOSED",
}
_FEDERAL_STATUSES = {"PENDING", "COMPLIANT", "DEFICIENT"}
_ARGUMENT_STATUSES = {
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED",
    "REVIEW_LOCKED", "ACCEPTED", "REJECTED_AS_INSUFFICIENT",
}
_CRITERION_CODES = {
    "CRIT_MISSION", "CRIT_INTEGRITY", "CRIT_TEACHING_QUALITY",
    "CRIT_TEACHING_EVALUATION", "CRIT_RESOURCES_PLANNING",
}
_EVIDENCE_TYPES = {"INSTITUTIONAL_DATA", "ASSESSMENT_RESULT", "FINANCIAL_INDICATOR", "POLICY_DOCUMENT"}
_MODALITIES = {"ON_SITE", "VIRTUAL"}
_TEAM_STATUSES = {"PROPOSED", "CONFIRMED", "VISIT_SCHEDULED", "REPORT_FILED", "DISBANDED"}
_TEAM_ROLES = {"CHAIR", "MEMBER"}
_CONFLICT_STATUSES = {"CLEARED", "CONFLICTED"}
_ASSIGNMENT_RESPONSES = {"PENDING", "ACCEPTED", "DECLINED"}
_ASSIGNMENT_STATUSES = {"ACTIVE", "CLOSED"}
_PANEL_STATUSES = {"CONVENED", "CLOSED"}
_VOTE_CHOICES = {"REAFFIRM", "GRANT", "NOTICE", "PROBATION", "SHOW_CAUSE", "DENY", "WITHDRAW"}
_OUTCOME_ORIGINS = {"PANEL", "INDICATOR_MONITOR"}
_ACTION_TYPES = {
    "REAFFIRMATION", "GRANT_INITIAL", "DENIAL",
    "NOTICE", "PROBATION", "SHOW_CAUSE", "WITHDRAWAL",
}
_OUTCOME_STATUSES = {"DRAFTED", "DISCLOSED", "EFFECTIVE"}
_SANCTION_LEVELS = {"NOTICE", "PROBATION", "SHOW_CAUSE"}
_CURE_STATUSES = {"NONE", "UNDER_CURE_REVIEW", "CURED"}
_CHANGE_TYPES = {"NEW_LOCATION", "PROGRAM_LEVEL", "OWNERSHIP_CHANGE", "DISTANCE_DELIVERY"}
_CHANGE_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "DENIED", "DEFERRED"}
_REPORT_STATUSES = {"DUE", "SUBMITTED", "CLEARED", "FLAGGED_REVIEW", "FLAGGED_PANEL"}
_CFI_VARIANTS = {"PUBLIC", "PRIVATE"}
_CFI_BANDS = {"CLEAR", "REVIEW", "PANEL"}
_RATINGS = {"MET", "MET_WITH_CONCERNS", "NOT_MET"}


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_present(data: dict, fields, entity: str):
    for field in fields:
        assert field in data, f"{entity}.{field} missing from response"


def _assert_nullable_timestamp(data: dict, field: str, entity: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity}.{field} must be null or an ISO 8601 timestamp"
    )


def assert_institution(data: dict):
    _assert_common(data, "Institution")
    _assert_present(data, [
        "legal_name", "legal_status", "state_code", "fte_enrollment",
        "degree_levels_offered", "distance_delivery_approved", "locations_count",
        "accreditation_status", "sanction_status", "candidacy_pathway",
        "candidacy_started_at", "candidacy_expires_at", "accredited_since",
        "last_reaffirmed_at", "current_annual_dues_cents", "dues_paid_cents",
        "outstanding_dues_cents", "latest_cfi_value", "latest_cfi_band",
    ], "Institution")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["legal_status"] in _LEGAL_STATUSES
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["fte_enrollment"], int) and data["fte_enrollment"] >= 0
    assert isinstance(data["degree_levels_offered"], list) and data["degree_levels_offered"]
    assert set(data["degree_levels_offered"]) <= _DEGREE_LEVELS
    assert isinstance(data["distance_delivery_approved"], bool)
    assert isinstance(data["locations_count"], int) and data["locations_count"] >= 1
    assert data["accreditation_status"] in _ACCREDITATION_STATUSES
    assert data["sanction_status"] in _SANCTION_STATUSES
    assert data["candidacy_pathway"] is None or data["candidacy_pathway"] in _PATHWAYS
    for field in ("candidacy_started_at", "candidacy_expires_at", "accredited_since", "last_reaffirmed_at"):
        _assert_nullable_timestamp(data, field, "Institution")
    assert isinstance(data["current_annual_dues_cents"], int)
    assert isinstance(data["dues_paid_cents"], int)
    assert isinstance(data["outstanding_dues_cents"], int)
    assert data["latest_cfi_value"] is None or isinstance(data["latest_cfi_value"], (int, float))
    assert data["latest_cfi_band"] is None or data["latest_cfi_band"] in _CFI_BANDS
    assert_dues_invariants(data)


def assert_dues_invariants(data: dict):
    """outstanding_dues_cents == max(0, current - paid) (PRD §3.1)."""
    expected = max(0, data["current_annual_dues_cents"] - data["dues_paid_cents"])
    assert data["outstanding_dues_cents"] == expected, (
        f"outstanding_dues_cents {data['outstanding_dues_cents']} != max(0, "
        f"{data['current_annual_dues_cents']} - {data['dues_paid_cents']})"
    )


def assert_eligibility_application(data: dict):
    _assert_common(data, "EligibilityApplication")
    _assert_present(data, [
        "institution_id", "pathway", "statement_of_intent", "status",
        "filed_at", "adjudicated_at", "adjudication_notes",
    ], "EligibilityApplication")
    assert is_valid_uuid(data["institution_id"])
    assert data["pathway"] in _PATHWAYS
    assert data["status"] in _APPLICATION_STATUSES
    _assert_nullable_timestamp(data, "filed_at", "EligibilityApplication")
    _assert_nullable_timestamp(data, "adjudicated_at", "EligibilityApplication")


def assert_review_cycle(data: dict):
    _assert_common(data, "ReviewCycle")
    _assert_present(data, [
        "institution_id", "cycle_type", "status", "federal_compliance_status",
        "federal_components", "cohort_default_rates", "decided_at",
    ], "ReviewCycle")
    assert is_valid_uuid(data["institution_id"])
    assert data["cycle_type"] in _CYCLE_TYPES
    assert data["status"] in _CYCLE_STATUSES
    assert data["federal_compliance_status"] in _FEDERAL_STATUSES
    assert isinstance(data["federal_components"], list)
    for component in data["federal_components"]:
        assert "component_code" in component and component["result"] in {"PASS", "FAIL"}
    assert isinstance(data["cohort_default_rates"], list) and len(data["cohort_default_rates"]) <= 3
    _assert_nullable_timestamp(data, "decided_at", "ReviewCycle")


def assert_assurance_argument(data: dict):
    _assert_common(data, "AssuranceArgument")
    _assert_present(data, [
        "review_cycle_id", "narrative_text", "status", "revision_count",
        "readiness_self_reported", "readiness_team_verified", "submitted_at", "locked_at",
    ], "AssuranceArgument")
    assert is_valid_uuid(data["review_cycle_id"])
    assert data["status"] in _ARGUMENT_STATUSES
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    for field in ("readiness_self_reported", "readiness_team_verified"):
        value = data[field]
        assert value is None or (isinstance(value, (int, float)) and 0 <= value <= 100)
    _assert_nullable_timestamp(data, "submitted_at", "AssuranceArgument")
    _assert_nullable_timestamp(data, "locked_at", "AssuranceArgument")


def assert_evidence_item(data: dict):
    _assert_common(data, "EvidenceItem")
    _assert_present(data, [
        "assurance_argument_id", "criterion_code", "evidence_type",
        "title", "document_uri", "verified", "verified_by_reviewer_id",
    ], "EvidenceItem")
    assert is_valid_uuid(data["assurance_argument_id"])
    assert data["criterion_code"] in _CRITERION_CODES
    assert data["evidence_type"] in _EVIDENCE_TYPES
    assert isinstance(data["verified"], bool)
    verifier = data["verified_by_reviewer_id"]
    if data["verified"]:
        assert verifier is not None and is_valid_uuid(verifier)
    else:
        assert verifier is None, "verified_by_reviewer_id resets to null when verified is false"


def assert_reviewer(data: dict):
    _assert_common(data, "Reviewer")
    _assert_present(data, [
        "full_name", "affiliation_institution_id", "specialty_criteria",
        "declared_conflict_institution_ids", "quality_rating", "prior_chair_count",
        "is_active", "current_assignment_count",
    ], "Reviewer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    affiliation = data["affiliation_institution_id"]
    assert affiliation is None or is_valid_uuid(affiliation)
    assert isinstance(data["specialty_criteria"], list)
    assert set(data["specialty_criteria"]) <= _CRITERION_CODES
    assert isinstance(data["declared_conflict_institution_ids"], list)
    assert isinstance(data["quality_rating"], (int, float))
    assert 0.00 <= data["quality_rating"] <= 5.00
    assert isinstance(data["prior_chair_count"], int) and data["prior_chair_count"] >= 0
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["current_assignment_count"], int) and data["current_assignment_count"] >= 0


def assert_review_team(data: dict):
    _assert_common(data, "ReviewTeam")
    _assert_present(data, [
        "review_cycle_id", "visit_modality", "status", "chair_reviewer_id",
        "visit_start_at", "visit_end_at", "criterion_ratings",
        "report_recommendation", "report_summary", "recommended_action_computed",
        "report_filed_at",
    ], "ReviewTeam")
    assert is_valid_uuid(data["review_cycle_id"])
    assert data["visit_modality"] in _MODALITIES
    assert data["status"] in _TEAM_STATUSES
    assert is_valid_uuid(data["chair_reviewer_id"])
    _assert_nullable_timestamp(data, "visit_start_at", "ReviewTeam")
    _assert_nullable_timestamp(data, "visit_end_at", "ReviewTeam")
    _assert_nullable_timestamp(data, "report_filed_at", "ReviewTeam")
    assert isinstance(data["criterion_ratings"], list)
    for entry in data["criterion_ratings"]:
        assert entry["criterion_code"] in _CRITERION_CODES
        assert entry["rating"] in _RATINGS
    assert data["report_recommendation"] is None or data["report_recommendation"] in {
        "REAFFIRM", "GRANT", "NOTICE", "PROBATION", "SHOW_CAUSE", "DENY",
    }
    assert data["recommended_action_computed"] is None or data["recommended_action_computed"] in {
        "REAFFIRMATION", "GRANT_INITIAL", "NOTICE", "PROBATION", "SHOW_CAUSE", "DENIAL",
    }


def assert_team_assignment(data: dict):
    _assert_common(data, "TeamAssignment")
    _assert_present(data, [
        "review_team_id", "reviewer_id", "role_on_team",
        "conflict_status", "response", "status",
    ], "TeamAssignment")
    assert is_valid_uuid(data["review_team_id"])
    assert is_valid_uuid(data["reviewer_id"])
    assert data["role_on_team"] in _TEAM_ROLES
    assert data["conflict_status"] in _CONFLICT_STATUSES
    assert data["response"] in _ASSIGNMENT_RESPONSES
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_decision_panel(data: dict):
    _assert_common(data, "DecisionPanel")
    _assert_present(data, [
        "review_cycle_id", "member_reviewer_ids", "status",
        "votes", "prevailing_action", "closed_at",
    ], "DecisionPanel")
    assert is_valid_uuid(data["review_cycle_id"])
    assert isinstance(data["member_reviewer_ids"], list)
    assert len(data["member_reviewer_ids"]) == 7, "panel seats exactly 7 members (PRD §3.7)"
    assert data["status"] in _PANEL_STATUSES
    assert isinstance(data["votes"], list)
    for vote in data["votes"]:
        assert is_valid_uuid(vote["reviewer_id"])
        assert vote["choice"] in _VOTE_CHOICES
        assert is_iso8601_timestamp(vote["cast_at"])
    assert data["prevailing_action"] is None or data["prevailing_action"] in _VOTE_CHOICES
    _assert_nullable_timestamp(data, "closed_at", "DecisionPanel")


def assert_action_outcome(data: dict):
    _assert_common(data, "ActionOutcome")
    _assert_present(data, [
        "review_cycle_id", "indicator_origin_institution_id", "origin",
        "action_type", "status", "public_disclosure_text", "disclosed_at",
        "effective_at", "sanction_level", "cure_status",
        "cure_review_opened_at", "cure_threshold_snapshot", "cure_deadline_at",
    ], "ActionOutcome")
    assert data["origin"] in _OUTCOME_ORIGINS
    assert data["action_type"] in _ACTION_TYPES
    assert data["status"] in _OUTCOME_STATUSES
    assert data["sanction_level"] is None or data["sanction_level"] in _SANCTION_LEVELS
    assert data["cure_status"] in _CURE_STATUSES
    for field in ("disclosed_at", "effective_at", "cure_review_opened_at", "cure_deadline_at"):
        _assert_nullable_timestamp(data, field, "ActionOutcome")
    assert data["cure_threshold_snapshot"] is None or isinstance(data["cure_threshold_snapshot"], int)


def assert_substantive_change_request(data: dict):
    _assert_common(data, "SubstantiveChangeRequest")
    _assert_present(data, [
        "institution_id", "change_type", "requested_program_level",
        "new_location_state", "ownership_details", "status", "decision_notes",
    ], "SubstantiveChangeRequest")
    assert is_valid_uuid(data["institution_id"])
    assert data["change_type"] in _CHANGE_TYPES
    assert data["status"] in _CHANGE_STATUSES
    assert data["requested_program_level"] is None or data["requested_program_level"] in _DEGREE_LEVELS


def assert_indicator_report(data: dict):
    _assert_common(data, "IndicatorReport")
    _assert_present(data, [
        "institution_id", "period_start", "period_end", "status",
        "primary_reserve_ratio", "viability_ratio", "net_operating_ratio",
        "state_appropriation_ratio", "enrollment_change_pct", "completion_rate",
        "retention_rate", "fte_enrollment", "cfi_value", "cfi_variant_used",
        "emi_value", "evaluated_at",
    ], "IndicatorReport")
    assert is_valid_uuid(data["institution_id"])
    assert isinstance(data["period_start"], str) and isinstance(data["period_end"], str)
    assert data["period_end"] > data["period_start"], "period_end must be strictly after period_start"
    assert data["status"] in _REPORT_STATUSES
    assert data["cfi_variant_used"] is None or data["cfi_variant_used"] in _CFI_VARIANTS
    _assert_nullable_timestamp(data, "evaluated_at", "IndicatorReport")

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an int >= 1")


def assert_laboratory(data: dict):
    _assert_common(data, "Laboratory")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["clia_number"], str) and data["clia_number"]
    assert data["accreditation_status"] in [
        "APPLIED", "ENROLLED", "ACCREDITED", "PROBATION", "ACCREDITATION_REVOKED"]
    assert isinstance(data["active_discipline_count"], int)
    assert data["active_discipline_count"] >= 0


def assert_inspector_profile(data: dict):
    _assert_common(data, "InspectorProfile")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("affiliated_laboratory_id", ""))
    assert isinstance(data["specialties"], list) and len(data["specialties"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_enrollment(data: dict):
    _assert_common(data, "DisciplineEnrollment")
    assert is_valid_uuid(data.get("laboratory_id", ""))
    assert data["discipline"] in [
        "CHEMISTRY", "HEMATOLOGY", "MICROBIOLOGY", "IMMUNOLOGY", "MOLECULAR",
        "TRANSFUSION"]
    assert data["status"] in ["WAITING", "ACTIVE", "SUSPENDED", "CEASED"]
    assert data["standing_per_event"] in ["SATISFACTORY", "UNSATISFACTORY"]
    assert data["standing_rolling"] in ["SATISFACTORY", "UNSATISFACTORY"]
    assert isinstance(data["unsuccessful_event_streak"], int)
    assert data["unsuccessful_event_streak"] >= 0


def assert_section(data: dict):
    _assert_common(data, "TestingSection")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["section_name"], str) and data["section_name"]
    assert isinstance(data["critical_testing"], bool)
    assert data["checklist_status"] in ["UNASSIGNED", "ASSIGNED", "CHECKLIST_INVALIDATED"]


def assert_pt_subscription(data: dict):
    _assert_common(data, "PTSubscription")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["analytes"], list) and len(data["analytes"]) > 0


def assert_pt_shipment(data: dict):
    _assert_common(data, "PTShipment")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert is_iso8601_timestamp(data.get("shipped_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ["OPEN", "CLOSED"]
    assert data.get("closure_reason") in [None, "ADMIN_CLOSED", "DEADLINE_ELAPSED"]


def assert_pt_result(data: dict):
    _assert_common(data, "PTResult")
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert is_iso8601_timestamp(data.get("collected_at", ""))
    assert isinstance(data["analyte_scores"], list)
    assert data["status"] in ["SUBMITTED", "GRADED", "VOID"]


def assert_pt_investigation(data: dict):
    _assert_common(data, "PTInvestigation")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["trigger_variant"] in ["PER_EVENT", "ROLLING", "BOTH"]
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "CORRECTIVE_ACTION_REQUIRED", "RESOLVED",
        "TESTING_CEASED"]


def assert_inspection_cycle(data: dict):
    _assert_common(data, "InspectionCycle")
    assert is_valid_uuid(data.get("laboratory_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in [
        "TEAM_ASSEMBLY", "SCREENED", "CONDUCTED", "FINDINGS_ISSUED", "DECIDED",
        "APPEALED", "INTERIM_SELF_INSPECTION", "RE_DECIDED"]
    assert isinstance(data["posture_ready"], bool)
    assert isinstance(data["deficiency_burden_score"], int)
    assert data.get("provisional_decision") in [None, "ACCREDITED", "CONDITIONAL", "DENIED"]
    assert data.get("final_decision") in [None, "ACCREDITED", "CONDITIONAL", "DENIED"]
    assert isinstance(data["appeal_count"], int)


def assert_team_assignment(data: dict):
    _assert_common(data, "TeamAssignment")
    assert is_valid_uuid(data.get("inspection_cycle_id", ""))
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert data["role_in_team"] in ["LEAD", "MEMBER"]
    assert data["status"] in ["PENDING", "CLEARED", "CONFLICTED", "REPLACED"]


def assert_finding(data: dict):
    _assert_common(data, "InspectionFinding")
    assert is_valid_uuid(data.get("inspection_cycle_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert isinstance(data["checklist_item_code"], str) and data["checklist_item_code"]
    assert data["deficiency_level"] in ["LEVEL_1", "LEVEL_2"]
    assert data["status"] in [
        "CITED", "RESPONSE_SUBMITTED", "ACCEPTED", "ESCALATED", "WITHDRAWN"]


def assert_personnel_record(data: dict):
    _assert_common(data, "PersonnelRecord")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["person_name"], str) and data["person_name"]
    assert data["personnel_role"] in ["DIRECTOR", "TECHNICAL_SUPERVISOR", "TESTING_PERSONNEL"]
    assert data["qualification_status"] in [
        "PROVISIONAL", "QUALIFIED", "COMPETENCY_REVIEW", "DISQUALIFIED"]
    assert isinstance(data["consecutive_failed_assessments"], int)


def assert_competency_assessment(data: dict):
    _assert_common(data, "CompetencyAssessment")
    assert is_valid_uuid(data.get("personnel_id", ""))
    assert is_iso8601_timestamp(data.get("assessed_at", ""))
    assert isinstance(data["element_scores"], list) and len(data["element_scores"]) == 6
    assert isinstance(data["composite_score"], (int, float))
    assert isinstance(data["passed"], bool)
    assert is_iso8601_timestamp(data.get("valid_until", ""))


def assert_method_validation(data: dict):
    _assert_common(data, "MethodValidation")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["method_name"], str) and data["method_name"]
    assert isinstance(data["instrument_name"], str) and data["instrument_name"]
    assert isinstance(data["correlation_r_squared"], (int, float))
    assert isinstance(data["precision_cv_pct"], (int, float))
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_checklist_edition(data: dict):
    _assert_common(data, "ChecklistEditionSummary")
    assert isinstance(data["checklist_code"], str) and data["checklist_code"]
    assert isinstance(data["checklist_version"], str) and data["checklist_version"]
    assert isinstance(data["retired_count"], int)

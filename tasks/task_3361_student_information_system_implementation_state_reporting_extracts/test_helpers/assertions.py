"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Common resource metadata of PRD §2.5 (id/created_at/updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in ("IMPLEMENTATION", "LIVE", "SUSPENDED")


def assert_school_year(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["instructional_days"], int) and data["instructional_days"] > 0
    assert data["status"] in ("PLANNING", "OPEN", "CLOSED_FOR_REPORTING",
                              "ROLLED_OVER", "ARCHIVED")


def assert_collection_spec(data: dict):
    _assert_common_fields(data)
    assert data["funding_method"] in ("ADM", "COUNT_DATE")
    assert isinstance(data["attendance_code_map"], dict)
    assert isinstance(data["discipline_code_map"], dict)
    assert isinstance(data["program_code_map"], dict)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_number"], str) and data["student_number"]
    assert data["entry_grade_level"] in ("KG", "01", "02", "03", "04", "05", "06",
                                         "07", "08", "09", "10", "11", "12")
    assert data["status"] in ("PRE_REGISTERED", "ENROLLED", "INACTIVE",
                              "GRADUATED", "ARCHIVED")


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["credit_hours"] > 0
    assert data["grade_band"] in ("ELEMENTARY", "MIDDLE", "HIGH", "ALL")


def assert_section(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_start_min"], int)
    assert isinstance(data["period_end_min"], int)
    assert data["period_end_min"] > data["period_start_min"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["roster_count"], int) and data["roster_count"] >= 0
    assert data["status"] in ("DRAFT", "COMMITTED", "LOCKED", "CANCELLED")


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle"] in ("ACTIVE", "WITHDRAWN", "COMPLETED")
    assert data["absence_posture"] in ("CLEAR", "AT_RISK", "CHRONIC")
    assert isinstance(data["membership_days"], int) and data["membership_days"] >= 0
    assert isinstance(data["prior_segment_days"], int)
    assert isinstance(data["absence_weight_sum"], (int, float))
    assert isinstance(data["absence_rate"], (int, float))
    assert isinstance(data["fte_adm"], (int, float))
    assert 0.0 <= data["fte_adm"] <= 1.0, "fte_adm capped at 1.0 (PRD §2.6)"
    assert isinstance(data["fte_count_date"], (int, float))
    assert 0.0 <= data["fte_count_date"] <= 1.0, "fte_count_date capped at 1.0 (PRD §2.6)"


def assert_attendance_event(data: dict):
    """Immutable ledger entry (PRD §2.5): id + created_at only — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AttendanceEvent must not carry updated_at (PRD §2.5)"
    assert "version" not in data, "AttendanceEvent must not carry version (PRD §2.5)"
    assert data["absence_weight"] in (0.0, 0.5, 1.0)
    assert isinstance(data["is_excused"], bool)


def assert_discipline_incident(data: dict):
    _assert_common_fields(data)
    assert data["action_type"] in ("NONE", "ISS", "OSS", "EXPULSION")
    assert isinstance(data["action_days"], int) and data["action_days"] >= 0
    assert isinstance(data["severity_base"], int)
    assert isinstance(data["severity_score"], int)
    assert data["status"] in ("REPORTED", "APPROVED", "VOIDED")


def assert_reporting_extract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "VALIDATED", "SUBMITTED", "ACCEPTED",
                              "REJECTED", "SUPERSEDED")
    assert isinstance(data["generation"], int) and data["generation"] >= 1
    assert isinstance(data["record_count"], int) and data["record_count"] >= 0
    assert isinstance(data["invalid_record_count"], int)
    assert isinstance(data["total_fte_millis"], int)
    assert isinstance(data["chronic_absentee_count"], int)
    assert data["escalation_priority"] in ("NONE", "STANDARD", "URGENT")


def assert_portal_account(data: dict):
    _assert_common_fields(data)
    assert data["account_type"] in ("PARENT", "STUDENT")
    assert data["access_level"] in ("FULL", "GRADES_ONLY", "ATTENDANCE_ONLY")
    assert data["grade_visibility"] in ("ALL_GRADES", "CURRENT_TERM_ONLY", "HIDDEN")
    assert data["status"] in ("INVITED", "ACTIVE", "REVOKED")


def assert_integration_feed(data: dict):
    _assert_common_fields(data)
    assert data["platform"] in ("ASSESSMENT", "FOOD_SERVICE", "TRANSPORTATION", "LMS")
    assert data["status"] in ("PENDING", "IN_SYNC", "FAILED")


def assert_rollover_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "COMMITTED", "COMPENSATED", "SUPERSEDED")
    assert isinstance(data["promoted_count"], int) and data["promoted_count"] >= 0
    assert isinstance(data["graduated_count"], int) and data["graduated_count"] >= 0
    assert isinstance(data["archived_student_count"], int) \
        and data["archived_student_count"] >= 0

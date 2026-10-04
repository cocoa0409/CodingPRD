"""Entity assertions and domain invariant checkers (PRD §2.7, §3.11)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common fields for mutable entities (PRD §2.7)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), \
        f"version must be an int: {data.get('version')}"


def _assert_ledger(data: dict):
    """Append-only entities carry only id and created_at (PRD §2.7)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')}"
    assert "updated_at" not in data, "ledger entity must not expose updated_at"
    assert "version" not in data, "ledger entity must not expose version"


def assert_training_center(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in [
        "PROVISIONAL", "ACTIVE", "PROBATION", "SUSPENDED", "REVOKED"]
    assert data["probation_started_at"] is None or is_iso8601_timestamp(
        data["probation_started_at"])
    assert data["last_audit_opened_at"] is None or is_iso8601_timestamp(
        data["last_audit_opened_at"])
    assert isinstance(data["cards_issued_count"], int)
    assert isinstance(data["active_card_count"], int)


def assert_training_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["street_address"], str)
    assert isinstance(data["city"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["capacity_students"], int)
    assert data["capacity_students"] >= 1
    assert data["status"] in [
        "PENDING_ALIGNMENT", "ALIGNED", "SUSPENDED", "DECOMMISSIONED"]
    assert is_valid_uuid(data["training_center_id"])


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["discipline"] in ["BLS", "ACLS", "PALS", "HEARTSAVER"]
    assert is_valid_uuid(data["home_training_center_id"])
    assert data["status"] in [
        "CANDIDATE", "MONITORED", "CERTIFIED", "SUSPENDED", "EXPIRED"]
    assert data["certified_since"] is None or is_iso8601_timestamp(
        data["certified_since"])
    assert data["renewal_due_at"] is None or is_iso8601_timestamp(
        data["renewal_due_at"])
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["is_faculty"], bool)
    assert isinstance(data["sessions_taught_count"], int)


def assert_alignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["training_center_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert isinstance(data["as_faculty"], bool)
    assert data["status"] in ["ACTIVE", "ENDED"]


def assert_course_monitoring(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data["instructor_id"])
    assert is_valid_uuid(data["monitoring_faculty_id"])
    assert data["course_type_observed"] in [
        "BLS_PROVIDER", "ACLS_PROVIDER", "PALS_PROVIDER", "HEARTSAVER"]
    assert data["outcome"] in ["SATISFACTORY", "UNSATISFACTORY"]


def assert_teaching_evaluation(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data["instructor_id"])
    assert is_valid_uuid(data["evaluator_faculty_id"])
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5
    assert isinstance(data["notes"], str)


def assert_guidelines_version(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data["published_at"])
    assert is_iso8601_timestamp(data["transition_deadline_at"])
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_course_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["training_center_id"])
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["primary_instructor_id"])
    assert is_valid_uuid(data["guidelines_version_id"])
    assert data["course_type"] in [
        "BLS_PROVIDER", "ACLS_PROVIDER", "PALS_PROVIDER",
        "HEARTSAVER", "BLS_INSTRUCTOR"]
    assert data["delivery_format"] in ["CLASSROOM", "BLENDED_SKILLS_SESSION"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["manikin_count"], int) and data["manikin_count"] >= 0
    assert isinstance(data["aed_trainer_count"], int) and data["aed_trainer_count"] >= 0
    assert isinstance(data["assisting_instructor_count"], int) \
        and data["assisting_instructor_count"] >= 0
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert data["cancel_reason"] is None or data["cancel_reason"] in [
        "MANUAL", "GUIDELINES_TRANSITION", "CENTER_SUSPENDED",
        "SITE_SUSPENDED", "INSTRUCTOR_SUSPENDED"]
    assert isinstance(data["seats_available"], int)
    assert data["curriculum_flag"] in ["CURRENT", "LEGACY"]


def assert_roster_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["course_session_id"])
    assert isinstance(data["student_name"], str) and data["student_name"]
    assert isinstance(data["student_email"], str) and data["student_email"]
    assert data["prior_card_id"] is None or is_valid_uuid(data["prior_card_id"])
    assert data["status"] in ["ENROLLED", "PASSED", "FAILED", "CANCELLED"]
    assert isinstance(data["remediation_used"], bool)


def assert_skills_evaluation(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data["roster_entry_id"])
    assert is_valid_uuid(data["evaluated_by_instructor_id"])
    assert data["attempt_number"] in [1, 2]
    assert isinstance(data["is_remediation_retest"], bool)
    assert isinstance(data["items"], list) and len(data["items"]) >= 1
    assert isinstance(data["total_items"], int) and data["total_items"] == len(
        data["items"])
    assert isinstance(data["passed_items"], int)
    assert isinstance(data["score_percent"], (int, float))
    assert data["outcome"] in ["PASS", "REMEDIATION_REQUIRED", "FAIL"]


def assert_card(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["roster_entry_id"])
    assert is_valid_uuid(data["training_center_id"])
    assert data["prior_card_id"] is None or is_valid_uuid(data["prior_card_id"])
    assert isinstance(data["is_renewal"], bool)
    assert isinstance(data["card_code"], str) and data["card_code"].startswith("AHA-")
    assert isinstance(data["verification_token"], str) and data["verification_token"]
    assert isinstance(data["holder_email"], str)
    assert data["course_type"] in [
        "BLS_PROVIDER", "ACLS_PROVIDER", "PALS_PROVIDER",
        "HEARTSAVER", "BLS_INSTRUCTOR"]
    assert isinstance(data["guidelines_version_code"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]


def assert_quality_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["target_training_center_id"])
    assert isinstance(data["opened_by"], str) and data["opened_by"]
    assert data["status"] in ["OPEN", "CLOSED_CLEAN", "CLOSED_CORRECTIVE"]
    assert isinstance(data["compliance_score"], (int, float))
    assert data["compliance_score"] >= 0
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["closed_at"] is None or is_iso8601_timestamp(data["closed_at"])


def assert_audit_finding(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data["audit_id"])
    assert data["severity"] in ["OBSERVATION", "MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["is_repeat_offense"], bool)
    assert isinstance(data["description"], str)
    assert isinstance(data["deduction_points"], (int, float))


def assert_card_verification(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data["card_id"])
    assert isinstance(data["verifier_reference"], str) and data["verifier_reference"]
    assert is_iso8601_timestamp(data["verified_at"])
    assert data["result"] in ["VALID", "EXPIRED", "REVOKED"]
    assert is_iso8601_timestamp(data["card_expires_at"])


def assert_seat_conservation(session: dict, enrolled_count: int):
    """PRD §3.11: seats_available + count(ENROLLED) == capacity."""
    assert session["seats_available"] + enrolled_count == session["capacity"], (
        f"seat conservation violated: {session['seats_available']} + "
        f"{enrolled_count} != {session['capacity']}")


def assert_card_stock_partition(center: dict, expired_count: int, revoked_count: int):
    """PRD §3.11: cards_issued_count == active + expired + revoked."""
    assert center["cards_issued_count"] == (
        center["active_card_count"] + expired_count + revoked_count
    ), (
        f"card stock partition violated: {center['cards_issued_count']} != "
        f"{center['active_card_count']} + {expired_count} + {revoked_count}")

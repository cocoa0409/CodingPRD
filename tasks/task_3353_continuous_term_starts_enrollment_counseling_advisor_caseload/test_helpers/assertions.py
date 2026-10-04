"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_term(data: dict):
    _assert_common_fields(data)
    for f in ("name", "start_date", "add_drop_end_date", "census_date", "end_date"):
        assert isinstance(data.get(f), str) and len(data[f]) > 0, f"{f} required"
    assert data["status"] in ("SCHEDULED", "ENROLLMENT_OPEN", "IN_SESSION", "CLOSED")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("code"), str) and len(data["code"]) > 0
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert isinstance(data.get("total_credits_required"), int)
    assert isinstance(data.get("licensure_flag"), bool)


def assert_state_authorization(data: dict):
    # Append-only row: only id + created_at among the common fields (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "state authorization rows carry no updated_at"
    assert "version" not in data, "state authorization rows carry no version"
    assert data.get("authorization_status") in (
        "AUTHORIZED", "RESTRICTED", "PROHIBITED", "PENDING")
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("effective_from"), str)


def assert_staff(data: dict):
    _assert_common_fields(data)
    assert data.get("staff_type") in ("COUNSELOR", "ADVISOR")
    assert data.get("compensation_plan") in ("NON_INCENTIVE", "INCENTIVE")
    assert isinstance(data.get("caseload_cap"), int)
    assert isinstance(data.get("active_caseload_count"), int)
    assert data["active_caseload_count"] >= 0


def assert_applicant(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in ("PROSPECT", "APPLIED", "ADMITTED", "ENROLLED")
    assert isinstance(data.get("contact_log"), list)
    assert "assigned_counselor_id" in data


def assert_application(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in (
        "SUBMITTED", "ADMITTED", "DENIED", "WITHDRAWN", "CONVERTED")
    assert isinstance(data.get("disclosure_acknowledged"), bool)
    assert isinstance(data.get("licensure_disclosure_acknowledged"), bool)


def assert_tce(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "IN_REVIEW", "COMPLETED", "VOID")
    assert isinstance(data.get("accepted_credits"), int)
    assert isinstance(data.get("in_progress_credits"), int)
    assert isinstance(data.get("capped_credits"), int)
    assert isinstance(data.get("remaining_credits"), int)
    assert data["remaining_credits"] >= 0


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in (
        "REGISTERED", "ACTIVE", "COMPLETED", "WITHDRAWN", "DEFERRED")
    assert data.get("enrollment_intensity") in (
        "FULL_TIME", "HALF_TIME", "LESS_THAN_HALF_TIME")
    assert isinstance(data.get("tuition_cents"), int)
    assert isinstance(data.get("financial_hold"), bool)
    assert isinstance(data.get("institutional_refund_cents"), int)


def assert_section(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in ("PLANNED", "STAFFING", "STAFFED", "OPEN", "LOCKED")
    assert isinstance(data.get("capacity"), int)
    assert isinstance(data.get("enrolled_count"), int)
    assert isinstance(data.get("seats_available"), int)
    assert isinstance(data.get("adjuncts_required"), int)


def assert_section_seat_invariant(data: dict):
    """PRD §3.7: enrolled_count + seats_available == capacity at all times."""
    assert data["enrolled_count"] + data["seats_available"] == data["capacity"], (
        f"seat invariant broken: {data['enrolled_count']} + "
        f"{data['seats_available']} != {data['capacity']}"
    )


def assert_aid_package(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in (
        "PACKAGED", "CERTIFIED", "DISBURSING", "SETTLED", "RETURNED")
    for f in ("efc_cents", "estimated_award_cents", "certified_award_cents",
              "disbursed_cents", "returned_cents", "retained_cents",
              "cancelled_cents"):
        assert isinstance(data.get(f), int), f"{f} must be integer cents"
    assert isinstance(data.get("disbursement_schedule"), list)


def assert_early_alert(data: dict):
    _assert_common_fields(data)
    assert data.get("trigger_type") in ("GRADE_THRESHOLD", "LATE_SUBMISSION")
    assert data.get("severity") in ("HIGH", "LOW")
    assert data.get("status") in (
        "OPEN", "ACKNOWLEDGED", "INTERVENTION", "RESOLVED", "ESCALATED")


def assert_retention_outreach(data: dict):
    _assert_common_fields(data)
    assert data.get("status") in (
        "QUEUED", "SENT", "RESPONDED", "REENROLLED", "EXPIRED")
    assert "sent_at" in data
    assert "applicant_id" in data

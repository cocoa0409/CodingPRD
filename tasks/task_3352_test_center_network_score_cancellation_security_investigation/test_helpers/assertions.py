"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Fields every primary resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_iso_equal(actual: str, expected: str):
    """Two ISO 8601 strings denote the same instant (formatting may differ)."""
    assert parse_iso8601(actual) == parse_iso8601(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_test_center(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["facility_seat_capacity"], int)
    assert data["facility_seat_capacity"] >= 1
    assert isinstance(data["equipment_list"], list)
    assert data["authorization_status"] in ("APPLIED", "AUTHORIZED", "SUSPENDED")
    assert data["last_audit_outcome"] in ("NONE", "PASSED", "FAILED")
    assert isinstance(data["active_staff_count"], int)


def assert_staff(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in ("PROCTOR", "CENTER_MANAGER")
    assert data["certification_level"] in ("BASIC", "ADVANCED")


def assert_center_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert data["audit_type"] in ("ANNOUNCED", "UNANNOUNCED")
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert data["outcome"] in ("PENDING", "PASSED", "FAILED")


def assert_test_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert data["status"] in (
        "DRAFT", "PUBLISHED", "LOCKED", "ADMINISTERED", "SCORED", "CANCELLED",
    )
    assert isinstance(data["total_seats"], int) and data["total_seats"] >= 1
    assert isinstance(data["reserved_accommodation_seats"], int)
    assert 0 <= data["reserved_accommodation_seats"] <= data["total_seats"]
    assert isinstance(data["proctor_staff_ids"], list)
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert data["effective_general_cap"] == (
        data["total_seats"] - data["reserved_accommodation_seats"]
    ), "effective_general_cap must equal total_seats minus reserved_accommodation_seats"


def assert_examinee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["id_document_type"] in ("PASSPORT", "NATIONAL_ID", "DRIVERS_LICENSE")
    assert isinstance(data["id_document_number"], str) and data["id_document_number"]
    assert data["status"] in ("ACTIVE", "BANNED")


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("examinee_id", ""))
    assert data["booking_status"] in ("CONFIRMED", "WAITLISTED", "CANCELLED")
    assert data["attendance_status"] in (
        "PENDING", "ADMITTED", "DENIED", "NO_SHOW", "COMPLETED",
    )
    assert data["pool"] in ("GENERAL", "ACCOMMODATION")
    if data["booking_status"] == "WAITLISTED":
        assert isinstance(data["waitlist_position"], int) and data["waitlist_position"] >= 1
    else:
        assert data.get("waitlist_position") is None


def assert_check_in_record(data: dict):
    """CheckInRecord is append-only: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "check-in records must not carry updated_at"
    assert "version" not in data, "check-in records must not carry version"
    assert data["document_check_result"] in ("PASS", "FAIL")
    assert data["biometric_result"] in ("FIRST_CAPTURE", "MATCH", "MISMATCH")
    assert data["admission_decision"] in ("ADMITTED", "DENIED")
    assert data["denial_reason"] in (
        "NONE", "DOCUMENT_MISMATCH", "DOCUMENT_EXPIRED", "BIOMETRIC_MISMATCH", "LATE_ARRIVAL",
    )


def assert_irregularity_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["category"] in (
        "SEATING_VIOLATION", "PROHIBITED_ITEM", "BREAK_VIOLATION",
        "SUSPECTED_IMPERSONATION", "CONTENT_EXPOSURE",
    )
    assert data["severity"] in ("LOW", "HIGH")
    assert data["status"] in ("FILED", "SUBSTANTIATED", "DISMISSED")


def assert_score_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data["section_raws"], list) and len(data["section_raws"]) == 3
    assert all(isinstance(r, int) and 0 <= r <= 50 for r in data["section_raws"])
    assert isinstance(data["raw_total"], int)
    assert data["raw_total"] == sum(data["section_raws"])
    assert isinstance(data["provisional_scaled_score"], int)
    assert data["status"] in (
        "PENDING_ANALYSIS", "UNDER_REVIEW", "VALIDATED", "RELEASED", "CANCELLED",
    )
    assert isinstance(data["released_report_count"], int) and data["released_report_count"] >= 0


def assert_score_review_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["trigger_reason"] in (
        "ANOMALOUS_GAIN", "RESPONSE_SIMILARITY", "CONTENT_EXPOSURE",
    )
    assert data["status"] in (
        "OPENED", "NOTIFIED", "RESPONSE_RECEIVED", "WINDOW_EXPIRED",
        "ADJUDICATED_UPHELD", "ADJUDICATED_CANCELLED",
    )
    assert data["adjudication_outcome"] in ("NONE", "UPHELD", "CANCELLED")


def assert_score_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("score_record_id", ""))
    assert isinstance(data["institution_code"], str)
    assert data["status"] in ("HELD", "RELEASED", "RECALLED")


def assert_accommodation_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("examinee_id", ""))
    assert data["accommodation_type"] in (
        "EXTENDED_TIME", "SCREEN_READER", "LARGE_PRINT", "SEPARATE_ROOM",
    )
    assert isinstance(data["requires_alternate_format"], bool)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_seat_invariant(session: dict, cancelled_count: int, total_created: int):
    """Seat invariant (PRD §3.3): confirmed + waitlisted + cancelled == total created."""
    assert (
        session["confirmed_count"] + session["waitlist_count"] + cancelled_count
        == total_created
    ), (
        f"seat invariant violated: {session['confirmed_count']} confirmed + "
        f"{session['waitlist_count']} waitlisted + {cancelled_count} cancelled "
        f"!= {total_created} ever created"
    )
    assert session["confirmed_count"] <= session["total_seats"]

"""Per-entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_STATUS_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict, entity: str):
    """Every persisted entity carries the full common property set."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_school(data: dict):
    assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert isinstance(data["center_code"], str) and data["center_code"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert data["test_center_status"] in ["ACTIVE", "SUSPENDED", "RETIRED"]
    assert isinstance(data["program_label_authorized"], bool)
    assert isinstance(data["accrued_fee_cents"], int)
    assert isinstance(data["designation_slots_used"], int)


def assert_course_audit(data: dict):
    assert_common_fields(data, "CourseAudit")
    assert data["status"] in [
        "SUBMITTED",
        "IN_REVIEW",
        "REVISION_REQUESTED",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
    ]
    assert isinstance(data["review_round"], int)
    assert isinstance(data["syllabus_revision_count"], int)
    assert isinstance(data["school_id"], str)


def assert_student(data: dict):
    assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["school_id"], str)
    assert isinstance(data["grade_level"], int)
    assert isinstance(data["accommodation_eligible"], bool)
    assert isinstance(data["enrolled"], bool)


def assert_exam_order(data: dict):
    assert_common_fields(data, "ExamOrder")
    assert data["status"] in [
        "DRAFT",
        "OPEN",
        "SUBMITTED",
        "MATERIALS_SHIPPED",
        "MATERIALS_RECEIVED",
        "DELIVERED",
        "VOIDED",
    ]
    assert data["ordering_window"] in ["NOT_OPEN", "REGULAR", "LATE", "CLOSED"]
    assert isinstance(data["registration_count"], int)
    assert isinstance(data["order_fee_cents"], int)
    assert isinstance(data["provisional_order_fee_cents"], int)
    assert isinstance(data["unused_exam_charge_cents"], int)
    assert isinstance(data["materials_sealed"], bool)


def assert_exam_registration(data: dict):
    assert_common_fields(data, "ExamRegistration")
    assert data["status"] in [
        "REGISTERED",
        "FEE_PENDING",
        "CONFIRMED",
        "MATERIAL_ASSIGNED",
        "SCORED",
        "SCORE_RELEASED",
        "CANCELLED",
        "INVALIDATED",
    ]
    assert data["registration_tier"] in ["REGULAR", "LATE", "EMERGENCY"]
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["refundable_cents"], int)
    assert isinstance(data["fees_paid_cents"], int)
    assert isinstance(data["accommodation_flag"], bool)


def assert_accommodation_request(data: dict):
    assert_common_fields(data, "AccommodationRequest")
    assert data["status"] in [
        "SUBMITTED",
        "UNDER_DOC_REVIEW",
        "INFO_REQUESTED",
        "APPROVED",
        "DENIED",
        "REVOKED",
    ]
    assert data["accommodation_type"] in [
        "EXTENDED_TIME",
        "ALTERNATE_FORMAT",
        "SMALL_GROUP",
        "BREAK_AS_NEEDED",
    ]
    assert 0 <= data["documentation_completeness"] <= 3
    assert isinstance(data["review_round"], int)
    assert isinstance(data["extended_time_multiplier"], (int, float))


def assert_alternate_exam_request(data: dict):
    assert_common_fields(data, "AlternateExamRequest")
    assert data["status"] in [
        "FILED",
        "UNDER_REVIEW",
        "APPROVED",
        "SCHEDULED",
        "DENIED",
        "WITHDRAWN",
    ]
    assert data["reason_code"] in [
        "SCHEDULE_CONFLICT",
        "ILLNESS",
        "RELIGIOUS_OBSERVANCE",
        "EMERGENCY",
        "OTHER",
    ]
    assert isinstance(data["seat_block_conflict"], bool)


def assert_exam_score(data: dict):
    assert_common_fields(data, "ExamScore")
    assert data["status"] in [
        "NOT_SCORED",
        "RUBRIC_PENDING",
        "AGGREGATED",
        "RELEASED",
        "CANCELLED",
        "WITHHELD",
        "INVALIDATED",
    ]
    assert 0.0 <= data["raw_composite"] <= 120.0
    assert isinstance(data["ap_score"], int)
    assert isinstance(data["release_blocked"], bool)
    assert isinstance(data["reader_reliability_index"], (int, float))


def assert_reader(data: dict):
    assert_common_fields(data, "Reader")
    assert data["calibration_status"] in [
        "RECRUITED",
        "CALIBRATING",
        "CALIBRATED",
        "DEMOTED",
        "INACTIVE",
    ]
    assert data["load_status"] in ["AVAILABLE", "AT_CAPACITY", "DEMOTED", "INACTIVE"]
    assert 0.0 <= data["reliability_index"] <= 1.0
    assert 0.0 <= data["calibration_index"] <= 1.0
    assert isinstance(data["calibration_round_count"], int)
    assert isinstance(data["assigned_score_count"], int)


def assert_material_shipment(data: dict):
    assert_common_fields(data, "ExamMaterialShipment")
    assert data["status"] in [
        "CREATED",
        "DISPATCHED",
        "IN_TRANSIT",
        "RECEIVED",
        "SEAL_BROKEN",
        "RETURNED",
    ]
    assert isinstance(data["seal_verified"], bool)
    assert isinstance(data["storage_checkpoint_count"], int)
    assert isinstance(data["custody_sequence_count"], int)


def assert_score_send(data: dict):
    assert_common_fields(data, "ScoreSend")
    assert data["recipient_type"] in ["COLLEGE", "STUDENT", "SCHOOL"]
    assert data["status"] in ["PENDING", "SENT", "ACKNOWLEDGED", "FAILED", "CANCELLED"]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["credit_back_cents"], int)


def assert_irregularity_case(data: dict):
    assert_common_fields(data, "IrregularityCase")
    assert data["status"] in [
        "OPEN",
        "INVESTIGATING",
        "DECISION_PENDING",
        "CONFIRMED",
        "DISMISSED",
        "APPEALED",
    ]
    assert data["irregularity_type"] in [
        "UNAUTHORIZED_DEVICE",
        "IMPROPER_ADMINISTRATION",
        "IDENTITY_DISCREPANCY",
        "MATERIAL_COMPROMISE",
        "ADMINISTRATOR_MISCONDUCT",
    ]
    assert isinstance(data["investigation_round"], int)


def assert_error_envelope(body: dict):
    """The 4xx envelope carries only the two meta fields plus error_id / message."""
    assert body.get("response_type") == "error", f"expected error envelope, got {body}"
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "error meta.api_request_id must be a non-empty string"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "error meta.api_request_timestamp must be ISO 8601"
    )
    data = body.get("data") or {}
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"]


def assert_success_envelope(body: dict, response_type: str = "object"):
    assert body.get("response_type") == response_type, (
        f"expected response_type {response_type}, got {body.get('response_type')}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))

"""Entity assertions and domain invariant checkers.

Every entity carries the common system-managed fields of PRD section 2.5:
id (UUID), created_at / updated_at (ISO 8601), and version (starts at 1).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_institution(data: dict):
    _assert_common_fields(data, "institution")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ope_id"], str) and len(data["ope_id"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["suspension_reason"] in ["NONE", "OPS", "AGREEMENT_LAPSE"]
    assert data["compliance_standing"] in ["COMPLIANT", "WATCH", "NON_COMPLIANT"]


def assert_agreement(data: dict):
    _assert_common_fields(data, "agreement")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["status"] in ["SCHEDULED", "ACTIVE", "EXPIRED"]


def assert_institution_user(data: dict):
    _assert_common_fields(data, "institution_user")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["role"] in ["SUBMITTER", "CERTIFIER"]
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_reporting_period(data: dict):
    _assert_common_fields(data, "reporting_period")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert isinstance(data["term_label"], str)
    assert data["status"] in ["SCHEDULED", "OPEN", "GRACE", "CLOSED"]
    assert data["outcome"] in ["NONE", "ON_TIME", "LATE", "DELINQUENT"]
    assert isinstance(data["upload_count"], int) and data["upload_count"] >= 0
    assert is_iso8601_timestamp(data.get("grace_ends_at", ""))


def assert_student(data: dict):
    _assert_common_fields(data, "student")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["deferment_standing"] in [
        "NONE", "DEFERMENT_ELIGIBLE", "DEFERMENT_INELIGIBLE",
        "WITHDRAWN_GRACE", "REPAYMENT_DUE",
    ]


def assert_directive(data: dict):
    _assert_common_fields(data, "directive")
    assert is_valid_uuid(data.get("student_id", ""))
    assert data["directive_type"] in ["FULL_BLOCK", "DIRECTORY_BLOCK", "RESEARCH_OPT_OUT"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "EXPIRED"]


def assert_enrollment_file(data: dict):
    _assert_common_fields(data, "enrollment_file")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("reporting_period_id", ""))
    assert data["status"] in ["UPLOADED", "CERTIFIED", "AMENDMENT_PENDING", "SUPERSEDED"]
    assert isinstance(data["row_count"], int) and data["row_count"] >= 0
    assert isinstance(data["accepted_rows"], int) and data["accepted_rows"] >= 0
    assert isinstance(data["rejected_rows"], int) and data["rejected_rows"] >= 0
    assert isinstance(data["open_correction_count"], int) and data["open_correction_count"] >= 0
    assert isinstance(data["late_submission"], bool)


def assert_file_row_partition(data: dict):
    """Row partition invariant: every row is accepted or rejected."""
    assert data["row_count"] == data["accepted_rows"] + data["rejected_rows"], (
        f"row partition broken: {data['row_count']} != "
        f"{data['accepted_rows']} + {data['rejected_rows']}"
    )


def assert_enrollment_entry(data: dict):
    _assert_common_fields(data, "enrollment_entry")
    assert is_valid_uuid(data.get("file_id", ""))
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert isinstance(data["row_index"], int) and data["row_index"] >= 0
    assert data["career_level"] in ["UNDERGRAD", "GRADUATE"]
    assert data["entry_status"] in ["ACCEPTED", "REJECTED", "SUPERSEDED"]
    assert data["reject_reason"] in [
        "NONE", "MISSING_FIELD", "INVALID_ENUM_VALUE", "INVALID_CREDITS",
        "INVALID_TERM_DATES", "INVALID_WITHDRAWAL_DATE", "DUPLICATE_STUDENT_IN_FILE",
    ]
    for field in ("status_code", "census_status_code"):
        assert data[field] in [
            "NONE", "FULL_TIME", "HALF_TIME", "LESS_THAN_HALF_TIME", "WITHDRAWN",
        ], f"{field} out of range: {data[field]}"
    assert data["deferment_status"] in [
        "NONE", "DEFERMENT_ELIGIBLE", "DEFERMENT_INELIGIBLE",
        "WITHDRAWN_GRACE", "REPAYMENT_DUE",
    ]


def assert_correction_case(data: dict):
    _assert_common_fields(data, "correction_case")
    assert is_valid_uuid(data.get("enrollment_entry_id", ""))
    assert data["reason_code"] in [
        "REPORTING_ERROR", "STATUS_MISSTATEMENT", "LATE_WITHDRAWAL_NOTICE",
    ]
    assert data["status"] in ["FILED", "APPLIED", "DENIED"]


def assert_degree_record(data: dict):
    _assert_common_fields(data, "degree_record")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert data["degree_level"] in [
        "CERTIFICATE", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE",
    ]
    assert isinstance(data["degree_title"], str)
    assert data["status"] in ["REPORTED", "SEALED", "REVOKED"]


def assert_requester(data: dict):
    _assert_common_fields(data, "requester")
    assert isinstance(data["org_name"], str) and len(data["org_name"]) > 0
    assert data["requester_kind"] in ["EMPLOYER", "BACKGROUND_SCREENER"]
    assert data["status"] in ["PENDING_VETTING", "VETTED", "SUSPENDED", "DENIED"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["initial_credit_cents"], int)


def assert_verification_request(data: dict):
    _assert_common_fields(data, "verification_request")
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["product_type"] in ["DEGREE", "ENROLLMENT", "TRANSCRIPT"]
    assert data["purpose"] in [
        "EMPLOYMENT", "BACKGROUND_SCREEN", "LOAN_DEFERMENT", "INSURANCE", "SELF",
    ]
    assert data["status"] in [
        "QUOTED", "PAID", "RELEASED", "BLOCKED_PRIVACY",
        "NO_RECORD", "EXPIRED", "CANCELLED",
    ]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert data["volume_tier_at_quote"] in ["STANDARD", "PREFERRED"]
    assert data["result_status"] in ["NONE", "VERIFIED", "NOT_VERIFIED"]
    assert data["enrollment_status_at_release"] in [
        "NONE", "FULL_TIME", "HALF_TIME", "LESS_THAN_HALF_TIME", "WITHDRAWN",
    ]
    assert is_iso8601_timestamp(data.get("quote_expires_at", ""))


def assert_servicer_notification(data: dict):
    _assert_common_fields(data, "servicer_notification")
    assert is_valid_uuid(data.get("enrollment_entry_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert isinstance(data["servicer_ref"], str)
    assert data["notification_type"] in [
        "DEFERMENT_ELIGIBLE", "DEFERMENT_INELIGIBLE",
        "WITHDRAWN_GRACE", "REPAYMENT_DUE",
    ]
    assert data["status"] in ["QUEUED", "SENT", "ACKNOWLEDGED", "SUPERSEDED"]


def assert_research_dataset(data: dict):
    _assert_common_fields(data, "research_dataset")
    assert is_valid_uuid(data.get("scope_institution_id", ""))
    assert isinstance(data["created_by_analyst_id"], str)
    assert data["status"] in ["REQUESTED", "GENERATED"]

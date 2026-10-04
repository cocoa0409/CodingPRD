"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_employer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["fein"].isdigit() and len(data["fein"]) == 9
    assert data["employer_type"] in ["PRIVATE", "NON_PROFIT", "STAFFING_AGENCY", "GOVERNMENT"]
    assert data["payroll_frequency"] in ["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
    assert data["feed_status"] in ["CURRENT", "DELAYED", "STALLED"]
    assert data["freeze_state"] in ["NONE", "REQUESTED", "ACTIVE", "LAPSED", "RELEASED"]
    assert data["review_state"] in ["NONE", "PENDING", "SCORED", "ESCALATED", "CLEARED"]


def assert_employer_invariants(data: dict):
    assert data["total_records_contributed"] >= 0
    assert data["dispute_open_count"] >= 0
    assert data["compensation_earned_cents"] >= 0
    assert data["counted_verification_records"] >= 0
    assert data["missing_periods"] >= 0
    assert 0 <= data["currency_score"] <= 600


def assert_record_layout(data: dict):
    assert_common_fields(data)
    assert data["layout_version"] >= 1
    assert data["status"] in ["DRAFT", "VERIFIED", "SUPERSEDED"]
    assert isinstance(data["validation_error_count"], int)
    assert isinstance(data["missing_canonical_fields"], list)
    assert data["missing_canonical_fields"] == sorted(data["missing_canonical_fields"])


def assert_payroll_batch(data: dict):
    assert_common_fields(data)
    assert data["batch_sequence"] >= 1
    assert data["record_count"] >= 1
    assert data["validation_state"] in ["RECEIVED", "VALIDATED", "REJECTED"]
    assert data["accepted_record_count"] + data["rejected_record_count"] == data["record_count"]


def assert_employment_record(data: dict):
    assert_common_fields(data)
    assert data["employment_status"] in [
        "ACTIVE", "LEAVE_OF_ABSENCE", "FURLOUGH", "TERMINATED", "RETIRED",
    ]
    assert data["pay_rate_basis"] in [
        "HOURLY", "WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY", "ANNUAL",
    ]
    assert data["record_state"] in [
        "PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CORRECTED", "IMMUTABLE",
    ]
    assert data["currency_state"] in ["CURRENT", "STALE", "FROZEN"]


def assert_covered_worker(data: dict):
    assert_common_fields(data)
    assert len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit()
    assert data["consent_status"] in ["PROVIDED", "REVOKED"]
    assert isinstance(data["opt_out"], bool)
    assert data["disclosure_state"] in ["NEVER_DISCLOSED", "CURRENT", "STALE"]


def assert_verifier(data: dict):
    assert_common_fields(data)
    assert data["verifier_class"] in [
        "DEPARTMENT_OF_SOCIAL_SERVICES", "MORTGAGE_LENDER", "BACKGROUND_CHECKER",
        "LANDLORD", "INSURER", "GOVERNMENT_AGENCY",
    ]
    assert data["entitlement_status"] in [
        "UNVERIFIED", "PENDING_REVIEW", "AUTHORIZED", "RESTRICTED",
    ]
    assert data["posture"] in ["NORMAL", "RESTRICTED"]
    assert data["negative_escalation_count"] >= 0


def assert_verification_product(data: dict):
    assert_common_fields(data)
    assert data["tier"] in ["EMPLOYMENT_ONLY", "EMPLOYMENT_INCOME", "FULL_INCOME_HISTORY"]
    assert data["history_months_included"] in [0, 12, 24]
    assert isinstance(data["rendered_field_set"], list)
    assert data["rendered_field_set"] == sorted(data["rendered_field_set"])


def assert_consumer_authorization(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["CAPTURED", "REVOKED"]
    assert is_iso8601_timestamp(data["granted_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_verification_request(data: dict):
    assert_common_fields(data)
    assert data["request_state"] in [
        "SUBMITTED", "PENDING_AUTH", "PERMITTED", "VALIDATED", "RESPONDED",
        "DECLINED", "REVERSED_RECONSENT_REQUIRED",
    ]
    if data.get("resolved_product_tier") is not None:
        assert data["resolved_product_tier"] in [
            "EMPLOYMENT_ONLY", "EMPLOYMENT_INCOME", "FULL_INCOME_HISTORY",
        ]
    assert isinstance(data["rendered_field_set"], list)
    assert data["rendered_field_set"] == sorted(data["rendered_field_set"])


def assert_verification_response(data: dict):
    # No common fields: only id and created_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a VerificationResponse carries no updated_at"
    assert "version" not in data, "a VerificationResponse carries no version"
    assert data["product_tier"] in [
        "EMPLOYMENT_ONLY", "EMPLOYMENT_INCOME", "FULL_INCOME_HISTORY",
    ]
    assert data["employer_feed_status"] in ["CURRENT", "DELAYED", "STALLED"]
    assert isinstance(data["income_history"], list)


def assert_consumer_disclosure(data: dict):
    assert_common_fields(data)
    assert data["disclosure_state"] in ["REQUESTED", "GENERATED", "SUPERSEDED"]
    assert data["included_record_count"] >= 0
    assert data["held_record_count"] >= 0


def assert_record_dispute(data: dict):
    assert_common_fields(data)
    assert data["claimed_field"] in [
        "EMPLOYMENT_STATUS", "HIRE_DATE", "SEPARATION_DATE", "PAY_RATE", "TENURE",
    ]
    assert data["dispute_state"] in [
        "FILED", "AWAITING_EMPLOYER", "NOTICE_SENT", "EMPLOYER_RESPONDED",
        "ESCALATED", "RESOLVED_CORRECTED", "RESOLVED_UPHELD", "CLOSED",
    ]
    assert is_iso8601_timestamp(data["response_due_date"])
    assert isinstance(data["deadline_extended"], bool)


def assert_compensation_accrual(data: dict):
    assert_common_fields(data)
    assert data["records_count"] >= 1
    assert data["cycle_state"] in ["ACCRUED", "WAIVED", "PAID"]
    assert data["gross_accrued_cents"] == data["records_count"] * data["unit_rate_cents"]


def assert_data_currency_review(data: dict):
    assert_common_fields(data)
    assert data["window_days"] >= 1
    assert data["expected_periods"] >= 0
    assert data["missing_periods"] == max(
        0, data["expected_periods"] - data["distinct_pay_periods_in_window"]
    )
    assert data["review_state"] in ["PENDING", "SCORED", "ESCALATED", "CLEARED"]


def assert_single_population_count_invariant(disclosure: dict, total_records: int):
    """included + held must equal the worker's total record count."""
    assert disclosure["included_record_count"] + disclosure["held_record_count"] == total_records, (
        "the disclosure's included and held counts must sum to the worker's total record count"
    )
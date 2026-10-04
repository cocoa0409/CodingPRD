"""Entity assertions and domain invariant checkers (PRD §2.7, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_append_only_fields(data: dict):
    # PRD §2.7: append-only resources carry ONLY id and created_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_seller(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["seller_number"], str) and data["seller_number"]
    assert isinstance(data["net_worth_cents"], int)
    assert isinstance(data["qc_defect_rate_bps"], int)
    assert data["status"] in ["PENDING_APPROVAL", "APPROVED", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["approval_cycle"], int) and data["approval_cycle"] >= 1
    assert isinstance(data["probation_relief_enabled"], bool)


def assert_servicer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["servicer_number"], str) and data["servicer_number"]
    assert isinstance(data["net_worth_cents"], int)
    assert data["qc_rating"] in ["SATISFACTORY", "NEEDS_IMPROVEMENT", "UNSATISFACTORY"]
    assert data["status"] in ["PENDING_APPROVAL", "APPROVED", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["oversight_score"], int) and 0 <= data["oversight_score"] <= 100


def assert_master_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert is_valid_uuid(data["servicer_id"])
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]


def assert_llpa_matrix(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert isinstance(data["rows"], list)
    for row in data["rows"]:
        assert row["occupancy"] in ["PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT"]
        assert row["product_type"] in ["FIXED_30", "FIXED_15", "ARM_5_1"]
        assert isinstance(row["llpa_bps"], int)
        assert isinstance(row["ltv_min_bp"], int)
        assert isinstance(row["ltv_max_bp"], int)
        assert isinstance(row["credit_min"], int)
        assert isinstance(row["credit_max"], int)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert is_valid_uuid(data["servicer_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["borrower_name"], str) and data["borrower_name"]
    assert isinstance(data["unpaid_principal_balance_cents"], int)
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["credit_score"], int)
    assert data["occupancy"] in ["PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT"]
    assert data["product_type"] in ["FIXED_30", "FIXED_15", "ARM_5_1"]
    assert isinstance(data["ltv_bp"], int)
    assert data["au_status"] in ["NOT_SUBMITTED", "RECOMMEND_APPROVE", "RECOMMEND_REFER", "INELIGIBLE"]
    assert data["status"] in ["DRAFT", "UNDERWRITTEN", "DELIVERED", "PURCHASED", "REJECTED", "REPURCHASED"]
    assert data["relief_tier"] in ["NONE", "PAYMENT_HISTORY_36", "INDEPENDENT_VALIDATION"]
    assert isinstance(data["consecutive_on_time_payments"], int)
    assert isinstance(data["independent_validation_complete"], bool)


def assert_underwriting_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1
    assert data["case_status"] in ["SUBMITTED", "VALIDATING", "VALIDATED", "FAILED", "FINALIZED"]
    assert data["recommendation"] in ["PENDING", "APPROVE_ELIGIBLE", "REFER_WITH_CAUTION"]
    assert data["final_outcome"] in ["PENDING", "PASS", "FAIL"]


def assert_validation_report(data: dict):
    _assert_append_only_fields(data)
    assert data["service_type"] in ["INCOME", "ASSET", "EMPLOYMENT"]
    assert data["result"] in ["PENDING", "VALIDATED", "NOT_VALIDATED"]
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert isinstance(data["provider_reference"], str)


def assert_pool(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["pool_number"], str) and data["pool_number"]
    assert is_iso8601_timestamp(data["issue_date"])
    assert isinstance(data["target_balance_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["loan_count"], int)
    assert data["status"] in ["OPEN", "LOCKED", "ISSUED", "CANCELLED"]


def assert_payment_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["paid_on_time"], bool)
    assert isinstance(data["amount_cents"], int)
    assert data["outcome"] in ["ON_TIME", "LATE"]


def assert_qc_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert data["sampling_method"] in ["RANDOM", "TARGETED", "DISCRETIONARY"]
    assert data["status"] in ["OPEN", "IN_REVIEW", "FINDINGS_ISSUED", "CLOSED"]


def assert_qc_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["defect_category"] in [
        "INCOME_MISREP", "ASSET_MISREP", "EMPLOYMENT_MISREP",
        "COLLATERAL", "ELIGIBILITY", "OTHER",
    ]
    assert data["severity"] in ["SIGNIFICANT", "MODERATE", "MINOR"]
    assert data["status"] in [
        "IDENTIFIED", "REPURCHASE_ISSUED", "APPEALED",
        "UPHELD", "OVERTURNED", "REMEDIATED",
    ]


def assert_repurchase_demand(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["finding_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["ISSUED", "APPEALED", "UPHELD", "WITHDRAWN", "SETTLED"]
    assert is_iso8601_timestamp(data["appeal_deadline"])
    assert isinstance(data["appeal_rounds_used"], int) and 0 <= data["appeal_rounds_used"] <= 2


def assert_servicing_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["to_servicer_id"])
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED"]


def assert_subservicer_oversight(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["servicer_id"])
    assert is_valid_uuid(data["subservicer_id"])
    assert is_iso8601_timestamp(data["oversight_period_start"])
    assert is_iso8601_timestamp(data["oversight_period_end"])
    assert isinstance(data["findings_count"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_pipeline(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["projected_value_cents"], int)


def assert_llpa_update_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["projected_value_before_cents"], int)
    assert isinstance(data["projected_value_after_cents"], int)
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["impacted_loan_count"], int)
    assert data["delta_cents"] == (
        data["projected_value_after_cents"] - data["projected_value_before_cents"]
    ), "delta_cents must equal after minus before (PRD §3.7)"

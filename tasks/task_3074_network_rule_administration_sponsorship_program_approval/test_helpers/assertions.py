"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MEMBER_KINDS = {"ISSUER", "ACQUIRER", "BOTH"}
REGIONS = {"NA", "EU", "APAC", "LATAM", "CEMEA"}


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["member_kind"] in MEMBER_KINDS
    assert data["region"] in REGIONS
    assert data["status"] in {"APPLICATION", "ACTIVE", "SUSPENDED", "TERMINATED"}
    assert isinstance(data["settled_balance_cents"], int)
    assert "suspension_reason" in data


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("sponsor_member_id", ""))
    assert data["status"] in {"PENDING_REVIEW", "ACTIVE", "SUSPENDED",
                              "TERMINATED"}
    assert isinstance(data["fraud_attributed_count"], int)


def assert_merchant(data: dict):
    _assert_common_fields(data)
    assert data["mcc"].isdigit() and len(data["mcc"]) == 4
    assert data["region"] in REGIONS
    assert isinstance(data["declared_monthly_volume_cents"], int)
    assert data["status"] in {"ACTIVE", "SUSPENDED", "TERMINATED"}
    assert data["fraud_monitoring_status"] in {
        "NOT_MONITORED", "UNDER_MONITORING", "REMEDIATION_REQUIRED", "EXEMPTED"}


def assert_bin_range(data: dict):
    _assert_common_fields(data)
    assert data["bin_prefix"].isdigit() and len(data["bin_prefix"]) == 6
    assert is_valid_uuid(data.get("issuer_member_id", ""))
    assert data["status"] in {"REQUESTED", "ACTIVE", "SUSPENDED", "DEACTIVATED"}
    assert "assigned_program_id" in data


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["program_type"] in {"CARD_PRODUCT", "WALLET", "COMMERCIAL"}
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert is_valid_uuid(data.get("owner_member_id", ""))
    assert data["status"] in {"REGISTERED", "UNDER_CERTIFICATION", "APPROVED",
                              "PRODUCTION_ENABLED", "RETIRED"}
    assert "approved_version" in data


def assert_certification_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["scope"] in {"NEW_PRODUCT", "WALLET", "COMBINED"}
    assert data["status"] in {"SUBMITTED", "PASSED", "FAILED"}
    assert isinstance(data["evaluated_program_version"], int)
    assert "failure_reason" in data


def assert_network_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["region_scope"] in {"GLOBAL"} | REGIONS
    assert data["status"] in {"DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED"}
    assert isinstance(data["fine_schedule"], list)
    assert is_iso8601_timestamp(data.get("effective_from", ""))


def assert_rule_violation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rule_id", ""))
    assert is_valid_uuid(data.get("subject_member_id", ""))
    assert data["severity"] in {"MINOR", "MAJOR", "CRITICAL"}
    assert isinstance(data["transaction_amount_minor"], int)
    assert data["status"] in {"CITED", "ASSESSED", "APPEALED", "CONFIRMED",
                              "WAIVED"}
    assert "fine_cents" in data


def assert_dispute_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert is_valid_uuid(data.get("issuer_member_id", ""))
    assert is_valid_uuid(data.get("acquirer_member_id", ""))
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["transaction_amount_cents"], int)
    assert data["status"] in {"OPENED", "EVIDENCE_SUBMITTED", "DECIDED",
                              "ARBITRATION_REQUESTED", "ARBITRATION_DECIDED",
                              "CLOSED"}
    assert "winning_side" in data
    assert is_iso8601_timestamp(data.get("filing_clock", ""))


def assert_dispute_evidence(data: dict):
    # Append-only: id + created_at only; no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "dispute evidence must not carry version"
    assert "updated_at" not in data, "dispute evidence must not carry updated_at"
    assert is_valid_uuid(data.get("dispute_case_id", ""))
    assert data["evidence_type"] in {
        "TRANSACTION_RECORD", "PROOF_OF_DELIVERY", "REFUND_POLICY",
        "CARDHOLDER_LETTER", "OTHER"}
    assert isinstance(data["document_ref"], str)


def assert_interchange_rate(data: dict):
    _assert_common_fields(data)
    assert data["merchant_category"].isdigit() and len(data["merchant_category"]) == 4
    assert data["transaction_type"] in {"CARD_PRESENT", "CARD_NOT_PRESENT",
                                        "ECOM_TOKENIZED", "RECURRING"}
    assert data["data_quality_tier"] in {"STANDARD", "ENHANCED", "PREMIUM"}
    assert isinstance(data["rate_basis_points"], int)
    assert isinstance(data["fixed_fee_cents"], int)
    assert data["region_scope"] in {"GLOBAL"} | REGIONS
    assert data["status"] in {"DRAFT", "PUBLISHED", "RETIRED"}


def assert_fraud_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert is_valid_uuid(data.get("reported_by_member_id", ""))
    assert isinstance(data["fraud_amount_cents"], int)
    assert data["status"] in {"REPORTED", "CONFIRMED", "DISMISSED"}
    assert "confirmed_at" in data


def assert_remediation_plan(data: dict):
    _assert_common_fields(data)
    assert data["subject_type"] in {"MERCHANT", "ACQUIRER"}
    assert is_valid_uuid(data.get("subject_id", ""))
    assert is_valid_uuid(data.get("fraud_program_cycle_id", ""))
    assert data["status"] in {"OPEN", "SUBMITTED", "APPROVED", "COMPLETED",
                              "OVERDUE", "ESCALATED"}
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert "approved_by_id" in data


def assert_fraud_program_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_label"], str) and data["cycle_label"]
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["status"] in {"SCHEDULED", "COMPLETED"}
    assert isinstance(data["merchants_flagged"], int)
    assert isinstance(data["acquirers_flagged"], int)
    assert "evaluated_at" in data


def assert_settlement_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["window_date"], str) and data["window_date"]
    assert is_iso8601_timestamp(data.get("opens_at", ""))
    assert is_iso8601_timestamp(data.get("closes_at", ""))
    assert data["status"] in {"SCHEDULED", "OPEN", "RECONCILED", "CLOSED"}
    assert isinstance(data["total_settled_cents"], int)


def assert_settlement_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("window_id", ""))
    assert is_valid_uuid(data.get("from_member_id", ""))
    assert is_valid_uuid(data.get("to_member_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {"DRAFT", "COMMITTED", "REVERSED"}
    assert "committed_at" in data

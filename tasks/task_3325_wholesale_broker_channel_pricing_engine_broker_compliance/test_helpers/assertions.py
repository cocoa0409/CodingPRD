"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

BROKER_STATUSES = ["SUBMITTED", "APPROVED", "SUSPENDED", "TERMINATED"]
BROKER_TIERS = ["UNRATED", "TIER_1", "TIER_2", "TIER_3"]
EXCLUSIVITY_STATUSES = ["CLEAR", "WARNED", "RESTRICTED", "BLOCKED"]
LICENSE_STATUSES = ["ACTIVE", "EXPIRED", "REVOKED"]
LICENSE_TYPES = ["MORTGAGE_BROKER", "MORTGAGE_LENDER", "DUAL_AUTHORITY"]
REVIEW_STATUSES = ["PENDING", "PASSED", "FAILED"]
ELIGIBILITY_STATUSES = ["PENDING", "APPROVED", "REVOKED"]
POLICY_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED", "VOIDED"]
SCOPE_VALUES = ["LOAN_SUBMISSION", "RATE_LOCK", "ALL"]
SHEET_STATUSES = ["PUBLISHED", "SUPERSEDED", "RETIRED"]
OCCUPANCY_VALUES = ["PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT"]
PURPOSE_VALUES = ["PURCHASE", "RATE_TERM_REFINANCE", "CASH_OUT_REFINANCE"]
LOAN_STATUSES = [
    "SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL", "SUSPENDED_REVIEW",
    "CLEAR_TO_CLOSE", "FUNDED", "DENIED", "WITHDRAWN", "REPURCHASED",
]
CLOSING_PATHS = ["ESCALATION_PATH", "STANDARD_PATH"]
ELECTION_VALUES = ["LENDER_PAID", "BORROWER_PAID", "UNDECIDED"]
DECISION_TYPES = ["APPROVED", "CONDITIONAL", "SUSPENDED", "DENIED"]
ESCALATION_STAGES = ["UNDERWRITING", "CLOSING"]
ESCALATION_STATUSES = ["OPEN", "RESOLVED"]
DEFECT_TYPES = [
    "INCOME_DISCREPANCY", "UNDISCLOSED_LIABILITY", "APPRAISAL_DEVIATION",
    "TITLE_DEFECT", "LICENSE_DEFECT", "NON_DEFECT",
]
SEVERITY_VALUES = ["MINOR", "MAJOR", "CRITICAL"]
OUTCOME_VALUES = ["PENDING", "CLEAR", "DEFECT"]
REMEDIATION_VALUES = ["NONE", "OPEN", "REMEDIATED", "VOIDED"]


def assert_common_fields(data: dict):
    """Top-level resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert ":" not in str(data.get("id", "")), "id must not carry a type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_broker(data: dict, strict: bool = True):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["nmls_id"], str) and len(data["nmls_id"]) > 0
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert data["status"] in BROKER_STATUSES
    assert data["tier"] in BROKER_TIERS
    assert data["exclusivity_status"] in EXCLUSIVITY_STATUSES
    assert isinstance(data["licensed_states"], list)
    assert isinstance(data["approved_product_codes"], list)
    assert isinstance(data["volume_expectation_cents"], int)
    assert isinstance(data["rolling_funded_volume_cents"], int)
    assert isinstance(data["open_defect_tier"], int)
    assert isinstance(data["active_loan_count"], int)
    assert isinstance(data["total_active_compensation_commitment_cents"], int)
    assert 0.0 <= float(data["rolling_quality_score"]) <= 100.0
    assert 0.0 <= float(data["financial_strength_score"]) <= 100.0
    if data["status"] != "SUSPENDED":
        assert data.get("suspended_reason") is None


def assert_broker_invariants(data: dict):
    assert data["rolling_funded_volume_cents"] >= 0
    assert data["active_loan_count"] >= 0
    assert data["open_defect_tier"] >= 0
    assert_cost_precision(data["rolling_funded_volume_cents"])
    assert_cost_precision(data["total_active_compensation_commitment_cents"])
    if data["status"] == "TERMINATED":
        assert data["active_loan_count"] == 0, "a terminated broker holds no active loans"


def assert_license(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in LICENSE_STATUSES
    assert data["license_type"] in LICENSE_TYPES
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_iso8601_timestamp(data["expires_on"])
    if data["status"] == "ACTIVE":
        assert data.get("revoked_at") is None
    if data["status"] == "REVOKED":
        assert is_iso8601_timestamp(data.get("revoked_at") or "")


def assert_financial_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in REVIEW_STATUSES
    assert isinstance(data["audit_attested"], bool)
    assert isinstance(data["is_current"], bool)
    assert 0.0 <= float(data["computed_financial_strength_score"]) <= 100.0
    for field in ("net_worth_cents", "liquidity_cents", "total_liabilities_cents",
                  "years_in_business", "prior_year_funded_volume_cents"):
        assert isinstance(data[field], int)


def assert_product_eligibility(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in ELIGIBILITY_STATUSES
    assert data["product_code"] in ["CONVENTIONAL", "FHA", "VA", "JUMBO", "USDA"]
    assert isinstance(data["max_ltv"], (int, float))
    assert isinstance(data["min_fico"], int)
    assert isinstance(data["max_loan_amount_cents"], int)
    if data["status"] == "APPROVED":
        assert is_iso8601_timestamp(data.get("approved_at") or "")
    else:
        assert data.get("approved_at") is None


def assert_exclusivity_policy(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in POLICY_STATUSES
    assert data["restriction_scope"] in SCOPE_VALUES
    assert isinstance(data["breach_count"], int) and data["breach_count"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["effective_to"] > data["effective_from"]


def assert_rate_sheet(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in SHEET_STATUSES
    assert data["product_code"] in ["CONVENTIONAL", "FHA", "VA", "JUMBO", "USDA"]
    assert isinstance(data["publish_sequence"], int) and data["publish_sequence"] >= 1
    assert is_iso8601_timestamp(data["published_at"])
    assert len(data["adjustment_table"]) == 4
    dims = [row["dim"] for row in data["adjustment_table"]]
    assert dims == ["credit", "ltv", "occupancy", "product"], f"table order must be pinned, got {dims}"
    if data["status"] == "PUBLISHED":
        assert data.get("superseded_by_sheet_id") is None
    if data["status"] == "SUPERSEDED":
        assert is_valid_uuid(data.get("superseded_by_sheet_id") or "")


def assert_pricing_quote(data: dict):
    """A quote is an immutable snapshot: id + created_at only."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "a pricing quote has no version"
    assert "updated_at" not in data, "a pricing quote has no updated_at"
    assert is_valid_uuid(data["rate_sheet_id"])
    assert is_valid_uuid(data["broker_id"])
    assert isinstance(data["adjustment_trace"], list)
    assert len(data["adjustment_trace"]) == 4
    trace_dims = [row["dim"] for row in data["adjustment_trace"]]
    assert trace_dims == ["credit", "ltv", "occupancy", "product"]
    assert isinstance(data["is_repriced"], bool)


def assert_loan_submission(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert is_valid_uuid(data["pricing_quote_id"])
    assert data["status"] in LOAN_STATUSES
    assert data["compensation_election"] in ELECTION_VALUES
    assert isinstance(data["loan_amount_cents"], int)
    assert isinstance(data["defect_remediation_open"], bool)
    assert isinstance(data["lender_paid_comp_cents"], int)
    assert isinstance(data["borrower_paid_comp_cents"], int)
    assert isinstance(data["repurchase_exposure_cents"], int)
    if data.get("closing_path") is not None:
        assert data["closing_path"] in CLOSING_PATHS
    assert_cost_precision(data["lender_paid_comp_cents"])
    assert_cost_precision(data["borrower_paid_comp_cents"])
    assert_cost_precision(data["repurchase_exposure_cents"])


def assert_loan_invariants(data: dict):
    election = data["compensation_election"]
    if election == "BORROWER_PAID":
        assert data["lender_paid_comp_cents"] == 0
    if election == "LENDER_PAID":
        assert data["borrower_paid_comp_cents"] == 0
    if election == "UNDECIDED":
        assert data["lender_paid_comp_cents"] == 0
        assert data["borrower_paid_comp_cents"] == 0
    assert data["repurchase_exposure_cents"] >= 0
    if data["status"] != "REPURCHASED":
        assert data["repurchase_exposure_cents"] == 0


def assert_compensation_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["broker_id"])
    assert data["plan_code"] in ["PLAN_A", "PLAN_B", "PLAN_C"]
    assert data["default_election"] in ["LENDER_PAID", "BORROWER_PAID"]
    assert isinstance(data["lender_paid_amount_cents"], int)
    assert isinstance(data["borrower_paid_amount_cents"], int)
    assert isinstance(data["is_active"], bool)


def assert_underwriting_decision(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_submission_id"])
    assert is_valid_uuid(data["broker_id"])
    assert data["decision_type"] in DECISION_TYPES
    assert isinstance(data["underwriter_id"], str) and len(data["underwriter_id"]) > 0
    assert isinstance(data["is_final"], bool)
    assert is_iso8601_timestamp(data["decided_at"])


def assert_escalation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_submission_id"])
    assert is_valid_uuid(data["broker_id"])
    assert data["stage"] in ESCALATION_STAGES
    assert data["status"] in ESCALATION_STATUSES
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["target_due_at"])
    if data["status"] == "OPEN":
        assert data.get("resolved_at") is None
    else:
        assert is_iso8601_timestamp(data.get("resolved_at") or "")


def assert_quality_control_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_submission_id"])
    assert is_valid_uuid(data["broker_id"])
    assert data["defect_type"] in DEFECT_TYPES
    assert data["severity"] in SEVERITY_VALUES
    assert data["outcome"] in OUTCOME_VALUES
    assert data["remediation_status"] in REMEDIATION_VALUES
    assert isinstance(data["repurchase_required"], bool)
    assert isinstance(data["weighted_defect_points"], (int, float))
    assert is_iso8601_timestamp(data["reviewed_at"])
    if data["repurchase_required"]:
        assert is_iso8601_timestamp(data.get("repurchase_due_at") or "")
    else:
        assert data.get("repurchase_due_at") is None


def assert_reconciliation(data: dict):
    for field in ("total_active_compensation_commitment_cents",
                  "rolling_funded_volume_cents",
                  "commitment_drift_cents",
                  "active_loan_count"):
        assert field in data, f"reconciliation must report {field}"
        assert isinstance(data[field], int)


def assert_closing_pipeline(data: dict):
    for field in ("escalated_count", "standard_count", "near_deadline_count",
                  "escalated_loan_ids", "standard_loan_ids"):
        assert field in data, f"closing pipeline must report {field}"
    assert isinstance(data["escalated_loan_ids"], list)
    assert isinstance(data["standard_loan_ids"], list)
    assert data["escalated_count"] == len(data["escalated_loan_ids"])
    assert data["standard_count"] == len(data["standard_loan_ids"])


def assert_clock_state(data: dict):
    assert is_iso8601_timestamp(data.get("current_utc", ""))
    assert isinstance(data["licenses_expired"], int)
    assert isinstance(data["escalations_opened"], int)


def assert_adjustment_trace_agrees(quote: dict):
    """overall_adjustment_pct must equal the sum of the trace's four rows."""
    total = sum(row["adjust_pct"] for row in quote["adjustment_trace"])
    assert abs(float(quote["overall_adjustment_pct"]) - total) < 1e-9, (
        f"overall_adjustment_pct {quote['overall_adjustment_pct']} != trace sum {total}"
    )
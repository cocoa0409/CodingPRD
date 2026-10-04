"""Entity assertions and domain invariant checkers (PRD §2.2, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

WORKER_STATUSES = ["LIVING", "DECEASED"]
CORRECTION_STATUSES = ["PENDING_REVIEW", "EVIDENCE_REQUESTED", "APPROVED", "DENIED", "EXPIRED"]
EVIDENCE_TYPES = ["WAGE_STATEMENT", "TAX_RETURN", "EMPLOYER_LETTER", "OTHER"]
RELATIONSHIP_TYPES = ["CURRENT_SPOUSE", "DIVORCED_SPOUSE", "WIDOW"]
RELATIONSHIP_STATUSES = ["ASSERTED", "VERIFIED", "REJECTED"]
CLAIM_TYPES = ["RETIREMENT", "SPOUSAL", "DIVORCED_SPOUSAL", "SURVIVOR"]
CLAIM_STATUSES = ["FILED", "ENTITLED", "DENIED", "SUSPENDED", "WITHDRAWN", "TERMINATED"]
PAYMENT_STATUSES = ["PAID", "WITHHELD_FULL", "REPAYED"]
PAID_TO_VALUES = ["BENEFICIARY", "REPRESENTATIVE_PAYEE"]
OVERPAYMENT_STATUSES = ["NOTIFIED", "WAIVER_REVIEW", "WAIVED", "RECOVERY_ACTIVE", "RECOVERED"]
OVERPAYMENT_REASONS = ["RECOMPUTATION", "FRAUD", "REPORTING_ERROR", "SYSTEM_ERROR"]
RECOVERY_MODES = ["FULL", "PARTIAL", "PROPORTIONAL"]
PAYEE_CASE_STATUSES = ["INVESTIGATING", "ACTIVE", "DENIED", "ENDED"]
RECOMPUTATION_TRIGGERS = ["CORRECTION_APPROVED", "PENSION_UPDATED", "SUSPENSION_RESUME"]
RECOMPUTATION_RESOLUTIONS = ["UNDERPAYMENT_CREDIT", "OVERPAYMENT_CREATED", "NONE"]


def _assert_common_fields(data: dict):
    """PRD §2.6: id is a bare UUID, created_at/updated_at ISO 8601, version int."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_append_only_fields(data: dict):
    """PRD §2.6: wage reports and recomputation events carry only id and
    created_at — updated_at and version are absent from them."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_year"], int) and 1900 <= data["birth_year"] <= 2100
    assert isinstance(data["birth_month"], int) and 1 <= data["birth_month"] <= 12
    assert isinstance(data["noncovered_pension_monthly_cents"], int)
    assert data["noncovered_pension_monthly_cents"] >= 0
    assert data["status"] in WORKER_STATUSES
    assert isinstance(data["fra_months"], int)
    assert isinstance(data["age_months"], int)
    assert isinstance(data["eligibility_year"], int)
    assert data["eligibility_year"] == data["birth_year"] + 62
    assert isinstance(data["withdrawal_used"], bool)


def assert_earnings_year(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("worker_id", "")), "worker_id must be a UUID"
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["posted_earnings_cents"], int) and data["posted_earnings_cents"] >= 0
    assert isinstance(data["noncovered_earnings_cents"], int) and data["noncovered_earnings_cents"] >= 0
    assert isinstance(data["corrected"], bool)
    assert isinstance(data["indexed_earnings_cents"], int) and data["indexed_earnings_cents"] >= 0


def assert_wage_report(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("worker_id", "")), "worker_id must be a UUID"
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["tax_year"], int) and 1986 <= data["tax_year"] <= 2100
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["covered_employment"], bool)
    assert isinstance(data["posted_amount_cents"], int) and data["posted_amount_cents"] >= 0
    assert data["status"] == "POSTED"


def assert_correction_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("worker_id", "")), "worker_id must be a UUID"
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["claimed_earnings_cents"], int) and data["claimed_earnings_cents"] >= 0
    assert data["evidence_type"] in EVIDENCE_TYPES
    assert data["status"] in CORRECTION_STATUSES
    # statute_deadline = (tax_year+4)-04-15 (PRD §3.2)
    assert data["statute_deadline"] == f"{data['tax_year'] + 4}-04-15"


def assert_relationship(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("worker_id", "")), "worker_id must be a UUID"
    assert is_valid_uuid(data.get("spouse_worker_id", "")), "spouse_worker_id must be a UUID"
    assert data["relationship_type"] in RELATIONSHIP_TYPES
    assert isinstance(data["marriage_date"], str)
    assert data["status"] in RELATIONSHIP_STATUSES
    assert isinstance(data["marriage_months"], int) and data["marriage_months"] >= 0


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("worker_id", "")), "worker_id must be a UUID"
    assert data["claim_type"] in CLAIM_TYPES
    assert isinstance(data["entitlement_month"], str) and len(data["entitlement_month"]) == 7
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["monthly_benefit_cents"], int) and data["monthly_benefit_cents"] >= 0
    assert isinstance(data["total_paid_cents"], int) and data["total_paid_cents"] >= 0
    assert isinstance(data["underpayment_credit_cents"], int) and data["underpayment_credit_cents"] >= 0
    assert data["recovery_mode"] in RECOVERY_MODES
    assert isinstance(data["has_active_payee"], bool)
    assert isinstance(data["drc_months"], int) and data["drc_months"] >= 0


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be a UUID"
    assert isinstance(data["month"], str) and len(data["month"]) == 7
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["withheld_cents"], int) and data["withheld_cents"] >= 0
    assert isinstance(data["underpayment_credit_cents"], int) and data["underpayment_credit_cents"] >= 0
    assert isinstance(data["net_paid_cents"], int)
    # PRD §3.7: net = gross - withheld + underpayment credit applied.
    assert data["net_paid_cents"] == (
        data["gross_cents"] - data["withheld_cents"] + data["underpayment_credit_cents"]
    ), "payment must reconcile: net == gross - withheld + credit"
    assert data["paid_to"] in PAID_TO_VALUES
    assert data["status"] in PAYMENT_STATUSES


def assert_overpayment_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["period_start_month"], str)
    assert isinstance(data["period_end_month"], str)
    assert data["reason"] in OVERPAYMENT_REASONS
    assert data["status"] in OVERPAYMENT_STATUSES
    assert isinstance(data["created_by"], str) and data["created_by"]
    assert isinstance(data["recovered_cents"], int) and data["recovered_cents"] >= 0
    # PRD §3.8: remaining_cents is the amount minus what has been recovered.
    assert data["remaining_cents"] == data["amount_cents"] - data["recovered_cents"], (
        "remaining_cents must equal amount_cents - recovered_cents"
    )


def assert_payee_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be a UUID"
    assert isinstance(data["payee_name"], str) and data["payee_name"]
    assert isinstance(data["determination_basis"], str) and data["determination_basis"]
    assert data["status"] in PAYEE_CASE_STATUSES
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_recomputation_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be a UUID"
    assert data["trigger"] in RECOMPUTATION_TRIGGERS
    assert isinstance(data["old_pia_cents"], int)
    assert isinstance(data["new_pia_cents"], int)
    assert isinstance(data["old_monthly_benefit_cents"], int)
    assert isinstance(data["new_monthly_benefit_cents"], int)
    assert isinstance(data["retro_delta_cents"], int)
    assert data["resolution"] in RECOMPUTATION_RESOLUTIONS

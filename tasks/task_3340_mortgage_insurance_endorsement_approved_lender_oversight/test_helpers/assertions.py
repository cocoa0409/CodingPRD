"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_lender(data: dict):
    _assert_common(data, "Lender")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["institution_type"] in (
        "MORTGAGEE_SUPERVISED",
        "MORTGAGEE_NONSUPERVISED",
        "MORTGAGEE_INVESTING",
    )
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert isinstance(data["qc_plan_on_file"], bool)
    assert data["status"] in (
        "DESK_REVIEW", "FIELD_REVIEW", "RETURNED", "APPROVED", "SUSPENDED", "TERMINATED",
    )
    assert isinstance(data["endorsed_volume_cents"], int)
    assert data["endorsed_volume_cents"] >= 0
    assert isinstance(data["required_net_worth_cents"], int)
    assert data["net_worth_variant"] in ("SMALL_LENDER", "STANDARD")


def assert_filing(data: dict):
    _assert_common(data, "FinancialFiling")
    assert is_valid_uuid(data.get("lender_id", ""))
    assert isinstance(data["fiscal_year_end"], str)
    assert isinstance(data["total_assets_cents"], int)
    assert isinstance(data["total_liabilities_cents"], int)
    assert isinstance(data["liquid_assets_cents"], int)
    assert isinstance(data["adjusted_net_worth_cents"], int)
    assert data["adjusted_net_worth_cents"] == (
        data["total_assets_cents"] - data["total_liabilities_cents"]
    ), "adjusted_net_worth_cents must equal total assets minus total liabilities"
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_loan_case(data: dict):
    _assert_common(data, "LoanCase")
    assert is_valid_uuid(data.get("lender_id", ""))
    assert isinstance(data["borrower_reference"], str)
    assert isinstance(data["base_loan_amount_cents"], int)
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["note_rate_bps"], int)
    assert isinstance(data["current_monthly_payment_cents"], int)
    assert data["status"] in (
        "CASE_NUMBER_ASSIGNED", "UNDERWRITE_SUBMITTED", "DEFICIENT", "BLOCKED",
        "ENDORSED", "IN_DEFAULT", "CLAIM_FILED", "VOIDED", "CLAIM_PAID", "CLAIM_DENIED",
    )
    assert data["endorsement_integrity"] in ("SOUND", "IMPAIRED")
    assert isinstance(data["mip_cancelled"], bool)
    assert isinstance(data["mip_retained_cents"], int)


def assert_appraisal(data: dict):
    _assert_common(data, "Appraisal")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert isinstance(data["mps_deficiency_codes"], list)
    assert data["status"] in ("DELIVERED", "ACCEPTED", "REJECTED", "EXPIRED", "TRANSFERRED")


def assert_escrow(data: dict):
    _assert_common(data, "RepairEscrow")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("OPEN", "FROZEN", "DISBURSED", "EXPIRED", "FORFEITED")
    assert isinstance(data["remaining_amount_cents"], int)
    assert isinstance(data["disbursed_amount_cents"], int)


def assert_mip_entry(data: dict):
    _assert_common(data, "MipLedgerEntry")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert data["entry_type"] in ("UPFRONT", "ANNUAL", "REFUND")
    assert isinstance(data["period_index"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert data["status"] in ("BILLED", "CANCELLED")


def assert_review(data: dict):
    _assert_common(data, "PostEndorsementReview")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert isinstance(data["reviewer_user_id"], str)
    assert isinstance(data["scope_codes"], list)
    assert data["status"] in ("INITIATED", "FINDINGS_RECORDED", "CLOSURE_PENDING", "CLOSED")


def assert_defect(data: dict):
    _assert_common(data, "Defect")
    assert is_valid_uuid(data.get("review_id", ""))
    assert data["defect_code"] in (
        "INCOME_MISCALC", "APPRAISAL_INFLATED", "ASSET_VERIFICATION_MISSING",
        "QC_PLAN_VIOLATION", "ELIGIBILITY_CRITERIA_UNMET",
    )
    assert isinstance(data["severity_score"], int)
    assert data["severity_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["status"] in ("OPEN", "CONFIRMED", "REMEDIATED", "DISMISSED")
    assert isinstance(data["created_by_user_id"], str)


def assert_agreement(data: dict):
    _assert_common(data, "IndemnificationAgreement")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert isinstance(data["coverage_cap_cents"], int)
    assert data["status"] in ("DRAFT", "EXECUTED", "SATISFIED")
    assert isinstance(data["recovered_total_cents"], int)


def assert_lm_action(data: dict):
    _assert_common(data, "LossMitigationAction")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert data["action_type"] in (
        "REPAYMENT_PLAN", "SPECIAL_FORBEARANCE", "LOAN_MODIFICATION",
        "PARTIAL_CLAIM", "PRE_FORECLOSURE_SALE", "DEED_IN_LIEU",
    )
    assert data["tier"] in (1, 2, 3, 4, 5, 6)
    assert data["status"] in ("PENDING", "APPROVED", "FAILED", "INFEASIBLE")


def assert_claim(data: dict):
    _assert_common(data, "InsuranceClaim")
    assert is_valid_uuid(data.get("loan_case_id", ""))
    assert data["claim_type"] in ("CONVEYANCE", "WITHOUT_CONVEYANCE")
    assert isinstance(data["unpaid_principal_balance_cents"], int)
    assert isinstance(data["expense_items"], list)
    assert isinstance(data["principal_component_cents"], int)
    assert isinstance(data["expense_component_cents"], int)
    assert isinstance(data["total_claim_cents"], int)
    assert data["status"] in ("UNDER_REVIEW", "PAID", "DENIED")


def assert_timestamp_startswith(value: str, expected_prefix: str, field: str):
    """Logical-clock stamped timestamps compare by their second-precision prefix,
    tolerating the fractional-digit rendering."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value.startswith(expected_prefix), (
        f"{field} must start with {expected_prefix!r}, got {value!r}"
    )

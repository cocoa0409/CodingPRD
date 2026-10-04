"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be an int >= 1"


def _assert_immutable_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is immutable and must not carry updated_at"
    assert "version" not in data, f"{entity} is immutable and must not carry version"


def assert_model_version(data: dict):
    _assert_common_fields(data, "ModelVersion")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["variables"], list)
    for var in data["variables"]:
        assert isinstance(var["name"], str) and var["name"]
        assert isinstance(var["weight"], (int, float))
        assert isinstance(var["min"], (int, float))
        assert isinstance(var["max"], (int, float))
    assert isinstance(data["score_floor"], int)
    assert isinstance(data["score_ceiling"], int)
    assert data["status"] in ["DRAFT", "VALIDATED", "ACTIVE", "RETIRED"]
    assert "fairness_report" in data


def assert_partner(data: dict):
    _assert_common_fields(data, "Partner")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["partner_type"] in ["BANK", "CREDIT_UNION", "LOAN_BUYER", "SECURITIZATION_TRUST"]
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"]
    assert "active_credit_box_id" in data
    assert isinstance(data["originated_this_month_count"], int)
    assert isinstance(data["funded_balance_cents"], int)


def assert_credit_box(data: dict):
    _assert_common_fields(data, "CreditBox")
    assert isinstance(data["partner_id"], str)
    assert isinstance(data["min_score"], int)
    assert isinstance(data["max_score"], int)
    assert isinstance(data["allowed_states"], list)
    assert isinstance(data["min_loan_cents"], int)
    assert isinstance(data["max_loan_cents"], int)
    assert isinstance(data["monthly_volume_cap_count"], int)
    assert isinstance(data["annual_percentage_rate"], (int, float))
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"]


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["monthly_debt_payments_cents"], int)
    assert data["education_level"] in ["HIGH_SCHOOL", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE"]
    assert data["employment_status"] in ["EMPLOYED", "SELF_EMPLOYED", "UNEMPLOYED", "RETIRED"]
    assert isinstance(data["months_employed"], int)
    assert isinstance(data["bank_account_avg_balance_cents"], int)
    assert isinstance(data["bank_account_nsf_count_90d"], int)
    assert isinstance(data["monthly_net_cashflow_cents"], int)
    assert isinstance(data["bureau_score"], int)


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert isinstance(data["applicant_id"], str)
    assert data["channel"] in ["DIRECT", "PARTNER_REFERRAL"]
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["model_version_id"], str)
    assert data["status"] in [
        "SUBMITTED", "VERIFICATION_PENDING", "DOCS_REQUIRED",
        "UNDERWRITTEN", "APPROVED", "DECLINED", "WITHDRAWN",
    ]


def assert_verification(data: dict):
    _assert_common_fields(data, "Verification")
    assert isinstance(data["application_id"], str)
    assert data["kind"] in ["INCOME", "IDENTITY"]
    assert data["status"] in [
        "PENDING", "INSTANT_PASSED", "INSTANT_FAILED",
        "MANUAL_REVIEW", "MANUAL_PASSED", "MANUAL_FAILED",
    ]


def assert_fairness_review(data: dict):
    _assert_common_fields(data, "FairnessReview")
    assert isinstance(data["model_version_id"], str)
    assert data["review_type"] in ["VARIABLE_EXCLUSION", "DISPARATE_IMPACT"]
    assert data["outcome"] in ["PENDING", "PASSED", "FAILED"]


def assert_attestation(data: dict):
    _assert_common_fields(data, "Attestation")
    assert isinstance(data["model_version_id"], str)
    assert isinstance(data["partner_id"], str)
    assert isinstance(data["period_label"], str) and data["period_label"]
    assert isinstance(data["expected_default_rate_bps"], int)
    assert isinstance(data["actual_default_rate_bps"], int)
    assert isinstance(data["variance_bps"], int)
    assert isinstance(data["attested_by_user_id"], str) and data["attested_by_user_id"]


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["holder_partner_id"], str)
    assert data["allocation_channel"] in [
        "PARTNER_RETAINED", "REFERRAL_RETAINED", "WHOLE_LOAN_SALE", "SECURITIZATION",
    ]
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["apr"], (int, float))
    assert data["term_months"] == 36
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["scheduled_interest_cents"], int)
    assert isinstance(data["late_fee_accrued_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["days_delinquent"], int)
    assert data["status"] in ["FUNDED", "CURRENT", "DELINQUENT", "DEFAULTED", "CHARGED_OFF", "PAID_OFF"]


def assert_servicing_event(data: dict):
    _assert_immutable_fields(data, "ServicingEvent")
    assert isinstance(data["loan_id"], str)
    assert data["event_type"] in [
        "PAYMENT_APPLIED", "LATE_FEE_ASSESSED", "DELINQUENCY_ADVANCED",
        "DEFAULT_DECLARED", "CHARGE_OFF_REPORTED", "PAYOFF_RECORDED",
    ]
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["resulting_loan_status"] in [
        "FUNDED", "CURRENT", "DELINQUENT", "DEFAULTED", "CHARGED_OFF", "PAID_OFF",
    ]


def assert_securitization_pool(data: dict):
    _assert_common_fields(data, "SecuritizationPool")
    assert isinstance(data["trust_partner_id"], str)
    assert isinstance(data["pool_label"], str) and data["pool_label"]
    assert isinstance(data["target_principal_cents"], int)
    assert isinstance(data["allocated_principal_cents"], int)
    assert isinstance(data["max_single_loan_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_allocation_decision(data: dict):
    _assert_immutable_fields(data, "AllocationDecision")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["candidate_partner_ids"], list)
    assert "chosen_partner_id" in data
    assert data["channel"] in [
        "PARTNER_RETAINED", "REFERRAL_RETAINED", "WHOLE_LOAN_SALE",
        "SECURITIZATION", "UNALLOCATED",
    ]
    assert isinstance(data["reason_codes"], list)
    assert is_iso8601_timestamp(data["decided_at"])

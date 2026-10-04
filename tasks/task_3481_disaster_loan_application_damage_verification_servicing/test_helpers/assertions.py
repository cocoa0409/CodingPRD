"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` validates shape, field types and enum membership of
one API resource body. Immutable ledger records (credit review, payment,
grant award) must NOT carry ``updated_at`` or ``version`` — the PRD states
they are absent entirely — so those assertions check absence, not presence.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ApplicantType,
    ApplicationStatus,
    CreditVerdict,
    DeclarationStatus,
    DisasterType,
    LoanLifecycleStatus,
    LoanPurpose,
    MilestoneStatus,
    ModificationStatus,
    PaymentStatus,
    ReceivableStatus,
    ServicingActionStatus,
    ServicingActionType,
    ServicingStatus,
    SettlementStatus,
    TrancheStatus,
    ValuationBasis,
    VerificationMethod,
    VerificationStatus,
)


def _values(enum_cls):
    return [e.value for e in enum_cls]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}: version must be an int >= 1"


def _assert_ledger_fields(data, label):
    """Immutable ledger record: id + created_at, never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}: created_at must be ISO 8601"
    assert "updated_at" not in data, \
        f"{label}: updated_at must be absent on an immutable record"
    assert "version" not in data, \
        f"{label}: version must be absent on an immutable record"


def _assert_nullable_timestamp(data, field, label):
    assert field in data, f"{label}: {field} key must be present"
    value = data[field]
    assert value is None or is_iso8601_timestamp(value), \
        f"{label}: {field} must be null or ISO 8601, got {value!r}"


def assert_declaration(data: dict):
    _assert_common_fields(data, "DisasterDeclaration")
    assert isinstance(data["declaration_number"], str) and data["declaration_number"]
    assert data["disaster_type"] in _values(DisasterType)
    for field in ("incident_start_date", "incident_end_date", "declared_date",
                  "physical_filing_deadline", "economic_injury_filing_deadline"):
        assert is_iso8601_timestamp(data.get(field, "")), \
            f"DisasterDeclaration: {field} must be ISO 8601"
    assert isinstance(data["counties"], list) and len(data["counties"]) >= 1
    for entry in data["counties"]:
        assert isinstance(entry["county_fips"], str) and entry["county_fips"]
        purposes = entry["eligible_purposes"]
        assert isinstance(purposes, list) and purposes
        for purpose in purposes:
            assert purpose in _values(LoanPurpose)
    assert data["status"] in _values(DeclarationStatus)


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["applicant_type"] in _values(ApplicantType)
    assert isinstance(data["annual_income_cents"], int) \
        and data["annual_income_cents"] > 0
    assert isinstance(data["monthly_debt_cents"], int) \
        and data["monthly_debt_cents"] >= 0


def assert_application(data: dict):
    _assert_common_fields(data, "LoanApplication")
    assert is_valid_uuid(data["declaration_id"])
    assert isinstance(data["applicant_id"], str) and data["applicant_id"]
    assert isinstance(data["county_fips"], str) and data["county_fips"]
    assert data["loan_purpose"] in _values(LoanPurpose)
    assert isinstance(data["requested_amount_cents"], int) \
        and data["requested_amount_cents"] > 0
    assert data["status"] in _values(ApplicationStatus)
    assert isinstance(data["reconsideration_count"], int) \
        and data["reconsideration_count"] >= 0
    _assert_nullable_timestamp(data, "submitted_at", "LoanApplication")
    assert "decline_reason" in data
    assert "loan_id" in data
    if data["loan_id"] is not None:
        assert is_valid_uuid(data["loan_id"]), \
            "LoanApplication: loan_id must be a UUID when set"


def assert_credit_review(data: dict):
    _assert_ledger_fields(data, "CreditReview")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]
    assert isinstance(data["credit_score"], int) \
        and 300 <= data["credit_score"] <= 850
    assert isinstance(data["verified_monthly_debt_cents"], int) \
        and data["verified_monthly_debt_cents"] >= 0
    assert isinstance(data["proposed_payment_cents"], int) \
        and data["proposed_payment_cents"] >= 0
    assert isinstance(data["score_pass"], bool)
    assert isinstance(data["dti_pass"], bool)
    assert data["verdict"] in _values(CreditVerdict)
    expected = "PASS" if (data["score_pass"] and data["dti_pass"]) else "FAIL"
    assert data["verdict"] == expected, (
        f"CreditReview: verdict {data['verdict']} inconsistent with "
        f"score_pass={data['score_pass']} dti_pass={data['dti_pass']}")


def assert_verification(data: dict):
    _assert_common_fields(data, "DamageVerification")
    assert is_valid_uuid(data["application_id"])
    assert data["method"] in _values(VerificationMethod)
    assert data["valuation_basis"] in _values(ValuationBasis)
    assert "depreciation_pct" in data
    assert isinstance(data["status"], str) \
        and data["status"] in _values(VerificationStatus)
    assert "verifier_user_id" in data
    _assert_nullable_timestamp(data, "completed_at", "DamageVerification")
    if data["status"] == "COMPLETED":
        assert isinstance(data["assessed_loss_cents"], int) \
            and data["assessed_loss_cents"] >= 0
        assert isinstance(data["insurance_proceeds_cents"], int) \
            and data["insurance_proceeds_cents"] >= 0
        assert isinstance(data["verified_loss_cents"], int) \
            and data["verified_loss_cents"] >= 0
        assert isinstance(data["net_verified_loss_cents"], int) \
            and data["net_verified_loss_cents"] >= 0
        assert data["net_verified_loss_cents"] <= data["verified_loss_cents"]
        assert isinstance(data["verifier_user_id"], str) \
            and data["verifier_user_id"]
        assert data["completed_at"] is not None


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["applicant_id"], str) and data["applicant_id"]
    assert data["loan_purpose"] in _values(LoanPurpose)
    assert isinstance(data["approved_amount_cents"], int) \
        and data["approved_amount_cents"] > 0
    assert isinstance(data["interest_rate"], (int, float)) \
        and data["interest_rate"] > 0
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert data["deferral_months"] == 12
    assert isinstance(data["monthly_payment_cents"], int) \
        and data["monthly_payment_cents"] > 0
    assert isinstance(data["collateral_required"], bool)
    assert "collateral_description" in data
    assert "collateral_value_cents" in data
    assert data["lifecycle_status"] in _values(LoanLifecycleStatus)
    assert data["servicing_status"] in _values(ServicingStatus)
    assert_loan_ledger_invariants(data)


def assert_loan_ledger_invariants(data: dict):
    """Ledger invariants that must hold after any loan money event."""
    for field in ("commitment_amount_cents", "disbursed_total_cents",
                  "outstanding_balance_cents", "accrued_interest_balance_cents",
                  "late_fee_balance_cents", "total_principal_paid_cents",
                  "total_interest_paid_cents", "days_past_due"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"Loan: {field} must be an int >= 0"
    assert data["outstanding_balance_cents"] <= data["disbursed_total_cents"], \
        "Loan: outstanding principal cannot exceed total disbursed"
    _assert_nullable_timestamp(data, "last_accrual_date", "Loan")
    _assert_nullable_timestamp(data, "next_due_date", "Loan")


def assert_tranche(data: dict):
    _assert_common_fields(data, "DisbursementTranche")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["stage_number"], int) and data["stage_number"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in _values(TrancheStatus)
    _assert_nullable_timestamp(data, "released_at", "DisbursementTranche")
    if data["status"] == "RELEASED":
        assert data["released_at"] is not None


def assert_milestone(data: dict):
    _assert_common_fields(data, "RepairMilestone")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["claimed_cost_cents"], int) \
        and data["claimed_cost_cents"] > 0
    assert data["status"] in _values(MilestoneStatus)
    assert "verified_cost_cents" in data
    assert "verifier_user_id" in data
    if data["status"] == "VERIFIED":
        assert isinstance(data["verified_cost_cents"], int)
        assert 0 <= data["verified_cost_cents"] <= data["claimed_cost_cents"]
        assert isinstance(data["verifier_user_id"], str) \
            and data["verifier_user_id"]


def assert_modification_request(data: dict):
    _assert_common_fields(data, "ModificationRequest")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["requested_amount_cents"], int) \
        and data["requested_amount_cents"] > 0
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in _values(ModificationStatus)
    assert "decided_by" in data


def assert_settlement(data: dict):
    _assert_common_fields(data, "InsuranceSettlement")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["settlement_amount_cents"], int) \
        and data["settlement_amount_cents"] > 0
    assert is_iso8601_timestamp(data["received_date"])
    assert data["status"] in _values(SettlementStatus)
    assert "clawback_commitment_delta_cents" in data
    assert "excess_due_cents" in data
    if data["status"] == "APPLIED":
        assert isinstance(data["clawback_commitment_delta_cents"], int) \
            and data["clawback_commitment_delta_cents"] >= 0
        assert isinstance(data["excess_due_cents"], int) \
            and data["excess_due_cents"] >= 0


def assert_receivable(data: dict):
    _assert_common_fields(data, "ExcessFundsReceivable")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_due_cents"], int) \
        and data["amount_due_cents"] > 0
    assert isinstance(data["amount_paid_cents"], int) \
        and data["amount_paid_cents"] >= 0
    assert data["amount_paid_cents"] <= data["amount_due_cents"]
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in _values(ReceivableStatus)


def assert_servicing_action(data: dict):
    _assert_common_fields(data, "ServicingAction")
    assert is_valid_uuid(data["loan_id"])
    assert data["action_type"] in _values(ServicingActionType)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["end_date"] > data["start_date"]
    assert data["status"] in _values(ServicingActionStatus)
    assert "decided_by" in data


def assert_payment(data: dict):
    _assert_ledger_fields(data, "Payment")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    total = 0
    for field in ("fee_portion_cents", "interest_portion_cents",
                  "principal_portion_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
        total += data[field]
    assert total == data["amount_cents"], (
        f"Payment: waterfall portions {total} must sum to "
        f"amount_cents {data['amount_cents']}")
    assert data["status"] in _values(PaymentStatus)


def assert_grant_award(data: dict):
    _assert_ledger_fields(data, "GrantAward")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["award_amount_cents"], int) \
        and data["award_amount_cents"] > 0
    assert data["purpose_category"] in _values(LoanPurpose)

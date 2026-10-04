"""Entity assertions and domain invariant checkers.

Each assert_* validates the shape of one resource per the PRD's §2.4 common
properties and the §3 entity narratives.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}: version must be an int"


def assert_jurisdiction(data):
    _assert_common(data, "Jurisdiction")
    for field in (
        "code",
        "name",
        "deposit_frequency",
        "penalty_tier1_rate",
        "penalty_tier2_rate",
        "penalty_tier3_rate",
        "underpayment_threshold_cents",
        "active",
    ):
        assert field in data, f"Jurisdiction missing field {field}"
    assert data["deposit_frequency"] in ("SEMIWEEKLY", "MONTHLY", "QUARTERLY")
    assert isinstance(data["underpayment_threshold_cents"], int)
    assert isinstance(data["active"], bool)


def assert_client(data):
    _assert_common(data, "Client")
    assert data["status"] in (
        "PROSPECT",
        "ONBOARDING",
        "ACTIVE",
        "SUSPENDED",
        "TERMINATED",
    )
    assert data["risk_posture"] in ("NORMAL", "ELEVATED", "HIGH")
    assert isinstance(data["funding_failure_count"], int)
    assert isinstance(data["credit_hold"], bool)


def assert_registration(data):
    _assert_common(data, "JurisdictionRegistration")
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert data.get("client_id")
    assert data.get("jurisdiction_id")


def assert_payroll_run(data):
    _assert_common(data, "PayrollRun")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "IMPOUNDED",
        "SETTLED",
        "REVERSED",
        "CANCELLED",
    )
    assert isinstance(data["gross_pay_cents"], int)
    assert isinstance(data["total_tax_cents"], int)
    assert isinstance(data["impound_amount_cents"], int)


def assert_impound(data):
    _assert_common(data, "Impound")
    assert data["status"] in ("PENDING", "SETTLED", "FAILED", "RETURNED")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("initiated_at", ""))
    assert is_iso8601_timestamp(data.get("due_by", ""))


def assert_funding_failure(data):
    assert is_valid_uuid(data.get("id", "")), "FundingFailureEvent: id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "FundingFailureEvent: created_at must be ISO 8601"
    # Immutable audit record: no updated_at, no version.
    assert (
        "updated_at" not in data
    ), "FundingFailureEvent must not carry updated_at"
    assert "version" not in data, "FundingFailureEvent must not carry version"
    assert data["kind"] in ("NSF_RETURN", "WIRE_NOT_CONFIRMED")
    assert isinstance(data["strike_count_after"], int)


def assert_deposit(data):
    _assert_common(data, "TaxDeposit")
    assert data["status"] in (
        "SCHEDULED",
        "SUBMITTED",
        "CONFIRMED",
        "FAILED",
        "CANCELLED",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["late_days"], int)
    assert isinstance(data["penalty_exposure_cents"], int)
    assert data.get("due_date")


def assert_return(data):
    _assert_common(data, "TaxReturn")
    assert data["status"] in (
        "DRAFT",
        "FILED",
        "ACCEPTED",
        "RECONCILED",
        "AMENDED",
        "REJECTED",
    )
    assert data["filing_method"] in ("ELECTRONIC", "MANUAL_INTERIM")
    assert isinstance(data["expected_liability_cents"], int)
    assert isinstance(data["shortfall_penalty_exposure_cents"], int)


def assert_amendment(data):
    _assert_common(data, "ReturnAmendment")
    assert data["status"] in ("DRAFT", "FILED", "ACCEPTED", "REJECTED")
    assert isinstance(data["adjusted_liability_cents"], int)


def assert_notice(data):
    _assert_common(data, "AgencyNotice")
    assert data["status"] in (
        "OPEN",
        "IN_REVIEW",
        "RESOLVED_NO_CHANGE",
        "RESOLVED_ADJUSTMENT",
        "ESCALATED",
        "CLOSED",
    )
    assert data["notice_type"] in (
        "BALANCE_DUE",
        "PENALTY_ASSESSMENT",
        "DATA_MISMATCH",
        "MISSING_RETURN",
    )
    assert isinstance(data["claimed_amount_cents"], int)


def assert_credit_assessment(data):
    _assert_common(data, "CreditAssessment")
    assert data["prior_posture"] in ("NORMAL", "ELEVATED", "HIGH")
    assert data["new_posture"] in ("NORMAL", "ELEVATED", "HIGH")
    assert data["trigger"] in ("FUNDING_FAILURE", "FAILURE_CURED", "MANUAL_REVIEW")


def assert_wage_statement(data):
    _assert_common(data, "WageStatement")
    assert data["status"] in ("DRAFT", "ISSUED", "CORRECTED", "VOIDED")
    assert data["statement_kind"] in ("ORIGINAL", "CORRECTION")
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["wages_cents"], int)
    assert isinstance(data["withheld_cents"], int)

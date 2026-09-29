"""Entity assertions and domain invariant checkers.

Timestamp comparisons go through :func:`assert_iso_equals`, which canonicalises
sub-second precision instead of comparing raw strings, so a server that renders
`2027-07-04T00:00:00Z` and one that renders `2027-07-04T00:00:00.000Z` are both
accepted for the same instant.
"""
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import iso_norm, parse_iso
from .types import (
    ActivationStatus, CarrierActivationState, CarrierCode, CreditApplicationStatus,
    CreditScoreBand, CustomerStatus, DelinquencyEventType, DelinquencyState,
    DeviceCondition, DiagnosticResult, ExpiryReason, FundingFlag, InstallmentStatus,
    LoanClosureReason, LoanStatus, PossessionStatus, PostingType,
    ProtectionCoverageStatus, QuoteStatus, QuoteType, ReportType, ScreenGrade,
    TradeInStatus, UnlockStatus, UpgradeRequestStatus,
)

_APPEND_ONLY_FORBIDDEN = ("updated_at", "version")


# --- Generic building blocks ---------------------------------------------
def assert_iso_equals(actual: str, expected: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment, ignoring the
    number of fractional digits each side chose to render."""
    assert actual is not None, f"{label} must not be null"
    assert parse_iso(actual) == parse_iso(expected), (
        f"{label} expected {iso_norm(expected)}, got {iso_norm(actual)}")


def assert_timestamp(value: str, label: str) -> None:
    assert is_iso8601_timestamp(value or ""), f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"


def assert_identity_fields(data: dict, entity: str) -> None:
    """Every persisted resource carries a server-minted UUID `id` and a
    `created_at` recorded from the logical clock."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert_timestamp(data.get("created_at"), f"{entity}.created_at")


def assert_mutable_audit_fields(data: dict, entity: str) -> None:
    """Resources that are not append-only additionally carry `updated_at` and an
    integer `version` beginning at 1."""
    assert_identity_fields(data, entity)
    assert_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version begins at 1, got {data['version']}"


def assert_append_only_record(data: dict, entity: str) -> None:
    """An append-only record carries only `id` and `created_at`: both
    `updated_at` and `version` are absent from the payload entirely."""
    assert_identity_fields(data, entity)
    for field in _APPEND_ONLY_FORBIDDEN:
        assert field not in data, (
            f"{entity} is append-only: {field} must be absent from the payload, "
            f"got {data.get(field)!r}")


def assert_cents(data: dict, field: str, entity: str, minimum: Optional[int] = 0) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{entity}.{field} must be an integer count of cents, got {value!r}")
    if minimum is not None:
        assert value >= minimum, f"{entity}.{field} must be >= {minimum}, got {value}"


def _assert_enum(data: dict, field: str, enum_cls, entity: str, nullable: bool = False) -> None:
    value = data.get(field)
    if value is None and nullable:
        return
    allowed = [member.value for member in enum_cls]
    assert value in allowed, f"{entity}.{field} must be one of {allowed}, got {value!r}"


# --- Per-entity assertions ----------------------------------------------
def assert_customer(data: dict) -> None:
    assert_mutable_audit_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["mobile_number"], str)
    _assert_enum(data, "status", CustomerStatus, "Customer")
    _assert_enum(data, "credit_score_band", CreditScoreBand, "Customer", nullable=True)
    for field in ("credit_limit_cents", "outstanding_principal_cents"):
        assert_cents(data, field, "Customer")
    for field in ("open_loan_count", "completed_upgrade_count", "default_strike_count"):
        assert isinstance(data[field], int) and data[field] >= 0, f"Customer.{field}"
    if data["status"] == CustomerStatus.ACTIVE.value:
        assert data["financing_lock_reason"] is None, (
            "financing_lock_reason is null while the customer is ACTIVE")
        assert data["financing_locked_at"] is None, (
            "financing_locked_at is null while the customer is ACTIVE")
    if data["completed_upgrade_count"] == 0:
        assert data["last_upgrade_completed_at"] is None, (
            "last_upgrade_completed_at remains null while completed_upgrade_count is zero")


def assert_device_model(data: dict) -> None:
    assert_mutable_audit_fields(data, "DeviceModel")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["display_name"], str)
    assert_cents(data, "retail_price_cents", "DeviceModel", minimum=1)
    assert_cents(data, "monthly_protection_premium_cents", "DeviceModel")
    assert_cents(data, "trade_in_base_credit_cents", "DeviceModel")
    assert isinstance(data["concurrent_reservation_capacity"], int)
    assert data["concurrent_reservation_capacity"] >= 0
    assert isinstance(data["reserved_slot_count"], int) and data["reserved_slot_count"] >= 0
    assert isinstance(data["generation_year"], int)
    assert isinstance(data["active"], bool)


def assert_carrier_account(data: dict) -> None:
    assert_mutable_audit_fields(data, "CarrierAccount")
    assert is_valid_uuid(data["customer_id"])
    _assert_enum(data, "carrier_code", CarrierCode, "CarrierAccount")
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["unlock_policy_days"], int) and data["unlock_policy_days"] >= 0
    _assert_enum(data, "activation_state", CarrierActivationState, "CarrierAccount")
    assert isinstance(data["port_freeze_flag"], bool)
    if data["activation_state"] == CarrierActivationState.PENDING.value:
        assert data["active_device_imei"] is None or isinstance(data["active_device_imei"], str)


def assert_credit_application(data: dict) -> None:
    assert_mutable_audit_fields(data, "CreditApplication")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert data["requested_term_months"] in (12, 24)
    for field in ("declared_down_payment_cents", "requested_principal_cents",
                  "credit_limit_cents", "exposure_at_decision_cents",
                  "approved_principal_cents", "conditional_down_payment_required_cents"):
        assert_cents(data, field, "CreditApplication")
    _assert_enum(data, "status", CreditApplicationStatus, "CreditApplication")
    _assert_enum(data, "credit_score_band", CreditScoreBand, "CreditApplication", nullable=True)
    if data["status"] == CreditApplicationStatus.SUBMITTED.value:
        assert data["credit_score_band"] is None
        assert data["decision_reason"] is None
        assert data["underwriter_user_id"] is None
        assert data["decided_at"] is None


def assert_loan(data: dict) -> None:
    assert_mutable_audit_fields(data, "InstallmentLoan")
    assert is_valid_uuid(data["customer_id"])
    # A first-generation loan records the `credit_application_id` it originated from;
    # a successor loan minted by an upgrade completion is drawn from the rollover quote
    # rather than from an application, and PRD names no application for it.
    if data["credit_application_id"] is not None:
        assert is_valid_uuid(data["credit_application_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert data["term_months"] in (12, 24)
    for field in ("down_payment_cents", "origination_fee_cents", "rolled_over_balance_cents",
                  "principal_cents", "monthly_protection_premium_cents",
                  "premium_total_cents", "monthly_installment_cents", "paid_principal_cents",
                  "paid_premium_cents", "outstanding_late_fee_cents",
                  "obligation_balance_cents"):
        assert_cents(data, field, "InstallmentLoan")
    assert isinstance(data["paid_installment_count"], int)
    assert 0 <= data["paid_installment_count"] <= data["term_months"]
    _assert_enum(data, "status", LoanStatus, "InstallmentLoan")
    _assert_enum(data, "closure_reason", LoanClosureReason, "InstallmentLoan", nullable=True)
    _assert_enum(data, "delinquency_state", DelinquencyState, "InstallmentLoan")
    _assert_enum(data, "protection_coverage_status", ProtectionCoverageStatus, "InstallmentLoan")
    assert isinstance(data["days_past_due"], int) and data["days_past_due"] >= 0
    assert isinstance(data["upgrade_hold_flag"], bool)
    assert_timestamp(data["origination_date"], "InstallmentLoan.origination_date")
    assert_timestamp(data["upgrade_window_opens_at"], "InstallmentLoan.upgrade_window_opens_at")
    if data["status"] == LoanStatus.ACTIVE.value:
        assert data["closure_reason"] is None, "closure_reason is null while the loan is ACTIVE"


def assert_installment(data: dict) -> None:
    assert_mutable_audit_fields(data, "Installment")
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["installment_number"], int) and data["installment_number"] >= 1
    assert_timestamp(data["due_date"], "Installment.due_date")
    for field in ("principal_component_cents", "premium_component_cents", "amount_due_cents",
                  "paid_principal_cents", "paid_premium_cents", "paid_amount_cents",
                  "late_fee_cents", "late_fee_paid_cents"):
        assert_cents(data, field, "Installment")
    assert data["amount_due_cents"] == (
        data["principal_component_cents"] + data["premium_component_cents"]), (
        "amount_due_cents is principal_component_cents plus premium_component_cents")
    assert isinstance(data["late_fee_assessed"], bool)
    _assert_enum(data, "status", InstallmentStatus, "Installment")


def assert_payment_posting(data: dict) -> None:
    """A PaymentPosting is append-only: id and created_at only."""
    assert_append_only_record(data, "PaymentPosting")
    assert is_valid_uuid(data["loan_id"])
    _assert_enum(data, "posting_type", PostingType, "PaymentPosting")
    assert_cents(data, "amount_cents", "PaymentPosting", minimum=1)
    for field in ("allocated_late_fee_cents", "allocated_premium_cents",
                  "allocated_principal_cents", "overpayment_cents",
                  "obligation_balance_after_cents"):
        assert_cents(data, field, "PaymentPosting")
    assert isinstance(data["installments_satisfied_count"], int)
    assert data["installments_satisfied_count"] >= 0
    assert_timestamp(data["posted_at"], "PaymentPosting.posted_at")
    if data["posting_type"] in (PostingType.PAYMENT.value, PostingType.PAYOFF.value):
        assert data["reverses_posting_id"] is None, (
            "reverses_posting_id is null on both PAYMENT and PAYOFF")


def assert_device_unit(data: dict) -> None:
    assert_mutable_audit_fields(data, "DeviceUnit")
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert isinstance(data["imei"], str) and len(data["imei"]) == 15 and data["imei"].isdigit()
    _assert_enum(data, "activation_status", ActivationStatus, "DeviceUnit")
    _assert_enum(data, "unlock_status", UnlockStatus, "DeviceUnit")
    _assert_enum(data, "possession_status", PossessionStatus, "DeviceUnit")


def assert_upgrade_request(data: dict) -> None:
    assert_mutable_audit_fields(data, "UpgradeRequest")
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["target_device_model_id"])
    assert_timestamp(data["fulfillment_window_start"], "UpgradeRequest.fulfillment_window_start")
    assert_timestamp(data["fulfillment_window_end"], "UpgradeRequest.fulfillment_window_end")
    assert isinstance(data["paid_installment_count_at_request"], int)
    assert isinstance(data["eligibility_ratio_bps"], int)
    for field in ("trade_in_credit_projection_cents", "projected_rollover_balance_cents",
                  "credit_shortfall_cents", "additional_down_payment_cents"):
        assert_cents(data, field, "UpgradeRequest")
    _assert_enum(data, "funding_flag", FundingFlag, "UpgradeRequest")
    _assert_enum(data, "status", UpgradeRequestStatus, "UpgradeRequest")
    _assert_enum(data, "expiry_reason", ExpiryReason, "UpgradeRequest", nullable=True)


def assert_trade_in(data: dict) -> None:
    assert_mutable_audit_fields(data, "TradeIn")
    assert is_valid_uuid(data["upgrade_request_id"])
    assert is_valid_uuid(data["device_unit_id"])
    _assert_enum(data, "declared_condition", DeviceCondition, "TradeIn")
    assert_cents(data, "credit_estimate_cents", "TradeIn")
    _assert_enum(data, "graded_condition", DeviceCondition, "TradeIn", nullable=True)
    _assert_enum(data, "diagnostic_result", DiagnosticResult, "TradeIn", nullable=True)
    _assert_enum(data, "status", TradeInStatus, "TradeIn")
    assert isinstance(data["latest_report_sequence_no"], int)
    assert isinstance(data["credit_variance_cents"], int)
    assert isinstance(data["dispute_count"], int) and data["dispute_count"] >= 0
    if data["status"] == TradeInStatus.DECLARED.value:
        assert data["graded_condition"] is None and data["credit_final_cents"] is None
        assert data["diagnostic_result"] is None and data["latest_report_sequence_no"] == 0


def assert_diagnostic_report(data: dict) -> None:
    """A DiagnosticReport is append-only: id and created_at only."""
    assert_append_only_record(data, "DiagnosticReport")
    assert is_valid_uuid(data["trade_in_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    _assert_enum(data, "report_type", ReportType, "DiagnosticReport")
    assert isinstance(data["technician_user_id"], str) and data["technician_user_id"]
    _assert_enum(data, "screen_grade", ScreenGrade, "DiagnosticReport")
    assert isinstance(data["battery_health_pct"], int)
    assert 0 <= data["battery_health_pct"] <= 100
    assert isinstance(data["water_damage_flag"], bool)
    assert isinstance(data["functional_pass"], bool)
    _assert_enum(data, "derived_condition", DeviceCondition, "DiagnosticReport")
    _assert_enum(data, "diagnostic_result", DiagnosticResult, "DiagnosticReport")
    for field in ("condition_multiplier_bps", "battery_deduction_cents",
                  "screen_deduction_cents", "computed_credit_cents"):
        assert_cents(data, field, "DiagnosticReport")


def assert_payoff_quote(data: dict) -> None:
    assert_mutable_audit_fields(data, "PayoffQuote")
    assert is_valid_uuid(data["loan_id"])
    _assert_enum(data, "quote_type", QuoteType, "PayoffQuote")
    _assert_enum(data, "status", QuoteStatus, "PayoffQuote")
    for field in ("remaining_principal_cents", "outstanding_late_fee_cents",
                  "unearned_premium_cents", "premium_rebate_cents", "admin_fee_cents",
                  "total_payoff_cents", "past_due_amount_cents"):
        assert_cents(data, field, "PayoffQuote")
    assert isinstance(data["paid_installment_count_at_quote"], int)
    assert_timestamp(data["issued_at"], "PayoffQuote.issued_at")
    assert_timestamp(data["expires_at"], "PayoffQuote.expires_at")


def assert_delinquency_event(data: dict) -> None:
    """A DelinquencyEvent is append-only: id and created_at only."""
    assert_append_only_record(data, "DelinquencyEvent")
    assert is_valid_uuid(data["loan_id"])
    _assert_enum(data, "event_type", DelinquencyEventType, "DelinquencyEvent")
    _assert_enum(data, "from_state", DelinquencyState, "DelinquencyEvent", nullable=True)
    _assert_enum(data, "to_state", DelinquencyState, "DelinquencyEvent", nullable=True)
    assert isinstance(data["days_past_due_at_event"], int)
    assert_cents(data, "amount_cents", "DelinquencyEvent")
    assert_timestamp(data["occurred_at"], "DelinquencyEvent.occurred_at")


# --- Domain invariant checkers ------------------------------------------
def assert_loan_ledger_invariants(loan: dict) -> None:
    """`obligation_balance_cents` is the unpaid principal plus the unpaid premium
    plus `outstanding_late_fee_cents`, at every point in the loan's life."""
    expected = ((loan["principal_cents"] - loan["paid_principal_cents"])
                + (loan["premium_total_cents"] - loan["paid_premium_cents"])
                + loan["outstanding_late_fee_cents"])
    assert loan["obligation_balance_cents"] == expected, (
        f"obligation_balance_cents expected {expected}, got {loan['obligation_balance_cents']}")
    assert loan["premium_total_cents"] == (
        loan["monthly_protection_premium_cents"] * loan["term_months"]), (
        "premium_total_cents is the monthly premium multiplied by term_months")


def assert_schedule_sums_to_principal(installments: list, loan: dict) -> None:
    """The principal components sum to `principal_cents` exactly."""
    total = sum(i["principal_component_cents"] for i in installments)
    assert total == loan["principal_cents"], (
        f"principal components sum to {total}, expected {loan['principal_cents']}")
    assert len(installments) == loan["term_months"], (
        f"expected {loan['term_months']} installments, got {len(installments)}")


def assert_loan_matches_schedule(loan: dict, installments: list) -> None:
    """The loan's rolled-forward ledger fields agree with its installments."""
    assert loan["paid_principal_cents"] == sum(i["paid_principal_cents"] for i in installments)
    assert loan["paid_premium_cents"] == sum(i["paid_premium_cents"] for i in installments)
    assert loan["paid_installment_count"] == sum(
        1 for i in installments if i["status"] == InstallmentStatus.PAID.value), (
        "paid_installment_count counts only installments in status PAID")
    assert loan["outstanding_late_fee_cents"] == sum(
        i["late_fee_cents"] - i["late_fee_paid_cents"] for i in installments
        if i["status"] != InstallmentStatus.VOIDED.value)


def assert_allocation_splits_exactly(posting: dict) -> None:
    """The three allocation totals plus the overpayment account for the whole
    posted amount."""
    total = (posting["allocated_late_fee_cents"] + posting["allocated_premium_cents"]
             + posting["allocated_principal_cents"] + posting["overpayment_cents"])
    assert total == posting["amount_cents"], (
        f"allocations plus overpayment total {total}, expected {posting['amount_cents']}")


def assert_ledger_positions_equal(before: dict, after: dict) -> None:
    """A compensating movement must restore the exact pre-event position, with
    zero drift in any cents field and no residue in any counter."""
    for field in ("paid_principal_cents", "paid_premium_cents", "paid_installment_count",
                  "outstanding_late_fee_cents", "obligation_balance_cents",
                  "days_past_due", "delinquency_state"):
        assert before[field] == after[field], (
            f"{field} drifted: was {before[field]!r}, now {after[field]!r}")


def assert_version_advanced_by(before: dict, after: dict, expected_delta: int = 1) -> None:
    actual = after["version"] - before["version"]
    assert actual == expected_delta, (
        f"version expected to advance by {expected_delta}, advanced by {actual}")

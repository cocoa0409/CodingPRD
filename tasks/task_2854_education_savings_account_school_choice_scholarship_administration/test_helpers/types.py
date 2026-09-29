"""Shapes of the resources the ESA administration API returns.

The ``TypedDict`` declarations document the field set of every resource so that a
test reads as domain language rather than as dictionary spelunking. Alongside them
sit the field-name tuples the shape assertions iterate over, split by whether the
resource is mutable state or append-only event evidence: the four append-only
record types carry only ``id`` and ``created_at`` and have no ``updated_at`` and no
``version`` field at all.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - the fallback only matters on very old interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


# --- Field-name groups -----------------------------------------------------------

CREATED_FIELDS = ("id", "created_at")
MUTABLE_FIELDS = ("id", "created_at", "updated_at", "version")

#: Resources that are mutable state and therefore carry updated_at and version.
MUTABLE_RESOURCE_NAMES = (
    "program_year",
    "student",
    "application",
    "account",
    "provider",
    "expense_category",
    "purchase_request",
    "misuse_case",
    "renewal_review",
    "appeal",
)

#: Resources that are append-only event evidence and carry no version at all.
APPEND_ONLY_RESOURCE_NAMES = (
    "eligibility_determination",
    "fraud_screening",
    "disbursement",
    "clawback_entry",
)


# --- Programme configuration -----------------------------------------------------


class ProgramYear(TypedDict, total=False):
    id: str
    label: str
    residency_state: str
    status: str
    total_seats: int
    seats_committed: int
    seats_available: int
    current_quarter: int
    window_open_at: str
    window_close_at: str
    term_start_date: str
    term_end_date: str
    base_award_cents: int
    rollover_cap_pct: float
    admin_fee_pct: float
    acceptance_deadline_days: int
    min_assessment_percentile: int
    min_portfolio_artifacts: int
    created_at: str
    updated_at: str
    version: int


class ExpenseCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    per_year_cap_cents: int
    allowable: bool
    requires_preapproval: bool
    requires_service_period: bool
    created_at: str
    updated_at: str
    version: int


class ClockSetting(TypedDict, total=False):
    current_utc: str


# --- Students and applications ---------------------------------------------------


class Student(TypedDict, total=False):
    id: str
    household_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    residency_state: str
    prior_enrollment: str
    income_band: str
    category_flags: List[str]
    has_enrolled_sibling: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    program_year_id: str
    student_id: str
    status: str
    is_renewal: bool
    claimed_income_band: str
    claimed_category_flags: List[str]
    verified_income_band: Optional[str]
    verified_category_flags: List[str]
    provisional_award_cents: int
    annual_award_cents: int
    final_award_cents: Optional[int]
    priority_tier: int
    priority_score: int
    submitted_at: Optional[str]
    acceptance_deadline_at: Optional[str]
    waitlist_position: Optional[int]
    appeal_round_count: int
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict, total=False):
    id: str
    application_id: str
    round_number: int
    residency_check: str
    prior_enrollment_check: str
    verified_income_band: str
    verified_prior_enrollment: str
    verified_category_flags: List[str]
    outcome: str
    denial_reason_code: Optional[str]
    priority_tier: int
    priority_score: int
    annual_award_cents: int
    decided_by_user_id: str
    created_at: str


class AwardingRunResult(TypedDict, total=False):
    awarded_count: int
    waitlisted_count: int
    program_year_status: str
    seats_committed: int
    seats_available: int
    awarded_application_ids: List[str]
    waitlist_ordered_application_ids: List[str]


class AcceptAwardResult(TypedDict, total=False):
    application_id: str
    application_status: str
    account_id: str
    annual_award_cents: int
    final_award_cents: int
    quarters_remaining_at_award: int


class WithdrawResult(TypedDict, total=False):
    application_id: str
    application_status: str
    account_id: str
    account_status: str
    seats_committed: int
    seats_available: int
    promoted_application_id: Optional[str]


# --- Accounts and funding --------------------------------------------------------


class Account(TypedDict, total=False):
    id: str
    application_id: str
    program_year_id: str
    status: str
    balance_cents: int
    encumbered_cents: int
    lifetime_disbursed_cents: int
    lifetime_admin_fee_cents: int
    lifetime_spent_cents: int
    lifetime_clawed_back_cents: int
    disbursement_count: int
    rollover_carried_cents: int
    forfeited_cents: int
    rolled_out_cents: int
    rollover_in_cents: int
    final_award_cents: int
    quarters_remaining_at_award: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    account_id: str
    program_year_id: str
    quarter: int
    quarters_left_at_issue: int
    gross_amount_cents: int
    admin_fee_cents: int
    net_credited_cents: int
    remainder_applied_cents: int
    issued_at: str
    created_at: str


class DisbursementRunResult(TypedDict, total=False):
    quarter: int
    disbursement_count: int
    total_gross_cents: int
    total_admin_fee_cents: int
    total_net_credited_cents: int
    skipped_account_ids: List[str]
    expired_application_ids: List[str]
    promoted_application_ids: List[str]


class YearEndCloseResult(TypedDict, total=False):
    program_year_status: str
    closed_account_count: int
    total_rolled_cents: int
    total_forfeited_cents: int
    resolved_misuse_case_ids: List[str]


# --- Providers -------------------------------------------------------------------


class Provider(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    address_state: str
    provider_type: str
    status: str
    screening_score: int
    surveillance_score: int
    substantiated_case_count: int
    authorized_category_codes: List[str]
    screening_flags: List[str]
    screened_at: Optional[str]
    sanction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudScreening(TypedDict, total=False):
    id: str
    provider_id: str
    flags: List[str]
    screening_score: int
    recommended_status: str
    screened_by_user_id: str
    screened_at: str
    created_at: str


# --- Purchases -------------------------------------------------------------------


class PurchaseRequest(TypedDict, total=False):
    id: str
    account_id: str
    provider_id: str
    expense_category_id: str
    flow: str
    approval_status: str
    settlement_status: str
    amount_cents: int
    claimed_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    invoice_reference: Optional[str]
    service_start_at: str
    service_end_at: str
    approved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    decision_reason: Optional[str]
    flagged_rule: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementResult(TypedDict, total=False):
    purchase_request_id: str
    settlement_status: str
    paid_amount_cents: int
    released_cents: int
    account_balance_cents: int
    account_encumbered_cents: int
    opened_misuse_case_id: Optional[str]


# --- Misuse and clawback ---------------------------------------------------------


class MisuseCase(TypedDict, total=False):
    id: str
    account_id: str
    purchase_request_id: Optional[str]
    status: str
    detection_rule: str
    disallowed_principal_cents: int
    narrative: str
    auto_opened: bool
    opened_by_user_id: str
    reviewed_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    rationale: Optional[str]
    penalty_rate: Optional[float]
    penalty_cents: Optional[int]
    clawback_total_cents: Optional[int]
    account_debit_cents: Optional[int]
    receivable_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClawbackEntry(TypedDict, total=False):
    id: str
    misuse_case_id: str
    account_id: str
    entry_type: str
    amount_cents: int
    created_by_user_id: str
    created_at: str


class ClawbackResult(TypedDict, total=False):
    misuse_case_id: str
    misuse_case_status: str
    penalty_rate: float
    penalty_cents: int
    clawback_total_cents: int
    account_debit_cents: int
    receivable_cents: int
    account_balance_cents: int
    clawback_entry_ids: List[str]


# --- Renewals and appeals --------------------------------------------------------


class RenewalReview(TypedDict, total=False):
    id: str
    account_id: str
    next_program_year_id: str
    status: str
    assessment_type: str
    assessment_score: Optional[int]
    portfolio_artifact_count: Optional[int]
    residency_state_attested: str
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    renewed_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalDecisionResult(TypedDict, total=False):
    renewal_review_id: str
    status: str
    renewed_application_id: Optional[str]
    prior_account_status: str
    next_program_year_seats_available: int


class Appeal(TypedDict, total=False):
    id: str
    subject_type: str
    application_id: Optional[str]
    misuse_case_id: Optional[str]
    provider_id: Optional[str]
    status: str
    grounds: str
    rationale: Optional[str]
    round_number: int
    filed_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


Payload = Dict[str, Any]

__all__ = [
    "CREATED_FIELDS",
    "MUTABLE_FIELDS",
    "MUTABLE_RESOURCE_NAMES",
    "APPEND_ONLY_RESOURCE_NAMES",
    "ProgramYear",
    "ExpenseCategory",
    "ClockSetting",
    "Student",
    "Application",
    "EligibilityDetermination",
    "AwardingRunResult",
    "AcceptAwardResult",
    "WithdrawResult",
    "Account",
    "Disbursement",
    "DisbursementRunResult",
    "YearEndCloseResult",
    "Provider",
    "FraudScreening",
    "PurchaseRequest",
    "SettlementResult",
    "MisuseCase",
    "ClawbackEntry",
    "ClawbackResult",
    "RenewalReview",
    "RenewalDecisionResult",
    "Appeal",
    "Payload",
]

"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    EMPLOYER = "Employer"
    COVERED_WORKER = "CoveredWorker"
    VERIFIER = "Verifier"


class EmployerType(str, Enum):
    PRIVATE = "PRIVATE"
    NON_PROFIT = "NON_PROFIT"
    STAFFING_AGENCY = "STAFFING_AGENCY"
    GOVERNMENT = "GOVERNMENT"


class PayrollFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"


class FeedStatus(str, Enum):
    CURRENT = "CURRENT"
    DELAYED = "DELAYED"
    STALLED = "STALLED"


class FreezeState(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    RELEASED = "RELEASED"


class LayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class BatchValidationState(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    FURLOUGH = "FURLOUGH"
    TERMINATED = "TERMINATED"
    RETIRED = "RETIRED"


class PayRateBasis(str, Enum):
    HOURLY = "HOURLY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class RecordState(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    CORRECTED = "CORRECTED"
    IMMUTABLE = "IMMUTABLE"


class CurrencyState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    FROZEN = "FROZEN"


class RequestState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_AUTH = "PENDING_AUTH"
    PERMITTED = "PERMITTED"
    VALIDATED = "VALIDATED"
    RESPONDED = "RESPONDED"
    DECLINED = "DECLINED"
    REVERSED_RECONSENT_REQUIRED = "REVERSED_RECONSENT_REQUIRED"


class DisputeState(str, Enum):
    FILED = "FILED"
    AWAITING_EMPLOYER = "AWAITING_EMPLOYER"
    NOTICE_SENT = "NOTICE_SENT"
    EMPLOYER_RESPONDED = "EMPLOYER_RESPONDED"
    ESCALATED = "ESCALATED"
    RESOLVED_CORRECTED = "RESOLVED_CORRECTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    CLOSED = "CLOSED"


class ProductTier(str, Enum):
    EMPLOYMENT_ONLY = "EMPLOYMENT_ONLY"
    EMPLOYMENT_INCOME = "EMPLOYMENT_INCOME"
    FULL_INCOME_HISTORY = "FULL_INCOME_HISTORY"


class VerifierClass(str, Enum):
    DEPARTMENT_OF_SOCIAL_SERVICES = "DEPARTMENT_OF_SOCIAL_SERVICES"
    MORTGAGE_LENDER = "MORTGAGE_LENDER"
    BACKGROUND_CHECKER = "BACKGROUND_CHECKER"
    LANDLORD = "LANDLORD"
    INSURER = "INSURER"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"


class PermissiblePurpose(str, Enum):
    PUBLIC_BENEFIT_DETERMINATION = "PUBLIC_BENEFIT_DETERMINATION"
    MORTGAGE_CREDIT_DECISION = "MORTGAGE_CREDIT_DECISION"
    EMPLOYMENT_SCREENING = "EMPLOYMENT_SCREENING"
    TENANT_SCREENING = "TENANT_SCREENING"
    INSURANCE_UNDERWRITING = "INSURANCE_UNDERWRITING"


# common_fields: true — carries id + created_at + updated_at + version
class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    employer_type: str
    payroll_frequency: str
    feed_status: str
    last_feed_received_date: Optional[str]
    freeze_state: str
    freeze_reason_code: Optional[str]
    freeze_requested_at: Optional[str]
    review_state: str
    review_period_end: Optional[str]
    missing_periods: int
    currency_score: int
    total_records_contributed: int
    dispute_open_count: int
    compensation_earned_cents: int
    counted_verification_records: int
    created_at: str
    updated_at: str
    version: int


class RecordLayout(TypedDict, total=False):
    id: str
    employer_id: str
    layout_version: int
    column_map: dict
    fiscal_year_start_month: int
    status: str
    verified_at: Optional[str]
    validation_error_count: int
    missing_canonical_fields: List[str]
    created_at: str
    updated_at: str
    version: int


class PayrollFeedBatch(TypedDict, total=False):
    id: str
    employer_id: str
    record_layout_id: str
    batch_sequence: int
    pay_period_end_date: str
    received_at: str
    record_count: int
    accepted_record_count: int
    rejected_record_count: int
    gross_amount_cents: int
    validation_state: str
    created_at: str
    updated_at: str
    version: int


class EmploymentRecord(TypedDict, total=False):
    id: str
    employer_id: str
    covered_worker_id: str
    payroll_feed_batch_id: str
    employment_status: str
    hire_date: str
    separation_date: Optional[str]
    pay_rate_cents: int
    pay_rate_basis: str
    standard_hours_per_week: Optional[float]
    final_pay_period_income_cents: int
    record_state: str
    currency_state: str
    annualized_income_cents: int
    tenure_months: int
    frozen_by_employer_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CoveredWorker(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    date_of_birth: str
    consent_status: str
    opt_out: bool
    disclosure_state: str
    open_dispute_count: int
    corrected_record_count: int
    created_at: str
    updated_at: str
    version: int


class Verifier(TypedDict, total=False):
    id: str
    legal_name: str
    verifier_class: str
    permitted_purpose: str
    entitlement_status: str
    posture: str
    escrow_balance_cents: int
    transaction_count: int
    negative_escalation_count: int
    created_at: str
    updated_at: str
    version: int


class VerificationProduct(TypedDict, total=False):
    id: str
    product_code: str
    tier: str
    requesting_class: str
    base_fee_cents: int
    history_months_included: int
    includes_employment_status: bool
    active: bool
    rendered_field_set: List[str]
    created_at: str
    updated_at: str
    version: int


class ConsumerAuthorization(TypedDict, total=False):
    id: str
    covered_worker_id: str
    verifier_id: str
    permitted_purpose: str
    granted_at: str
    expires_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict, total=False):
    id: str
    verifier_id: str
    covered_worker_id: str
    product_id: str
    consumer_authorization_id: Optional[str]
    permissible_purpose_asserted: str
    submitted_at: str
    request_state: str
    decline_reason: Optional[str]
    resolved_product_tier: Optional[str]
    current_employer_id: Optional[str]
    current_employment_status: Optional[str]
    current_tenure_months: Optional[int]
    rendered_field_set: List[str]
    records_matched_count: int
    responded_at: Optional[str]
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class VerificationResponse(TypedDict, total=False):
    id: str
    verification_request_id: str
    product_tier: str
    rendered_fields: List[str]
    employment_status: Optional[str]
    tenure_months: Optional[int]
    income_history: List[dict]
    active_employment_found: bool
    employer_feed_status: str
    created_at: str


class ConsumerDisclosure(TypedDict, total=False):
    id: str
    covered_worker_id: str
    requested_at: str
    disclosure_state: str
    included_record_count: int
    held_record_count: int
    file_contents: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class RecordDispute(TypedDict, total=False):
    id: str
    employment_record_id: str
    covered_worker_id: str
    claimed_field: str
    claimed_correct_value: str
    filed_at: str
    response_due_date: str
    deadline_extended: bool
    notice_sent_at: Optional[str]
    resolved_at: Optional[str]
    dispute_state: str
    created_at: str
    updated_at: str
    version: int


class CompensationAccrual(TypedDict, total=False):
    id: str
    employer_id: str
    pay_period_end_date: str
    transaction_ref: str
    records_count: int
    unit_rate_cents: int
    gross_accrued_cents: int
    adjusted_cents: int
    waived_cents: int
    paid_cents: int
    cycle_state: str
    created_at: str
    updated_at: str
    version: int


class DataCurrencyReview(TypedDict, total=False):
    id: str
    employer_id: str
    review_period_end: str
    window_days: int
    last_feed_date_in_window: str
    distinct_pay_periods_in_window: int
    expected_periods: int
    missing_periods: int
    currency_score: int
    review_state: str
    created_at: str
    updated_at: str
    version: int


class VerificationAttestation(TypedDict, total=False):
    id: str
    verification_request_id: str
    verifier_id: str
    attested_purpose: str
    signed_at: str
    attestation_state: str
    created_at: str
    updated_at: str
    version: int
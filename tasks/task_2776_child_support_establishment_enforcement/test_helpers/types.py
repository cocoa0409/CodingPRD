"""
Typed shapes for every resource the Child Support Enforcement API returns.

These mirror the PRD's declared field sets. Two resources are deliberately
narrower than the rest: an obligation charge and a payment transaction are
immutable financial events that carry only ``id`` and ``created_at``, so their
shapes omit ``updated_at`` and ``version`` entirely.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


JsonDict = Dict[str, Any]


class Participant(TypedDict, total=False):
    """A custodial or noncustodial party to a IV-D case."""

    id: str
    role_type: str
    full_name: str
    ssn_last4: str
    residence_state_code: str
    employer_name: Optional[str]
    monthly_gross_income_cents: Optional[int]
    income_verification_source: str
    supports_second_family: bool
    has_valid_drivers_license: bool
    locate_status: str
    locate_attempt_count: int
    license_suspension_active: bool
    lien_recorded: bool
    credit_bureau_reported: bool
    enforcement_risk_score: int
    enforcement_risk_tier: str
    compromise_risk_score: int
    compromise_risk_tier: str
    total_arrears_certified_cents: int
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class SupportCase(TypedDict, total=False):
    """A IV-D case, carrying three independent status dimensions."""

    id: str
    case_type: str
    custodial_party_id: str
    noncustodial_party_id: str
    child_count: int
    tanf_assistance: bool
    good_cause_claim: bool
    case_status: str
    enforcement_posture: str
    interstate_role: str
    locate_referral_count: int
    total_charged_principal_cents: int
    total_collected_principal_cents: int
    arrears_principal_cents: int
    assigned_arrears_cents: int
    unassigned_arrears_cents: int
    interest_collected_cents: int
    interest_written_off_cents: int
    interest_receivable_cents: int
    unapplied_credit_cents: int
    closed_reason: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaternityAction(TypedDict, total=False):
    """The single paternity action a case may carry."""

    id: str
    case_id: str
    method: str
    status: str
    notary_verified: bool
    signed_by_participant_id: Optional[str]
    aop_signed_at: Optional[str]
    rescission_deadline_at: Optional[str]
    rescission_count: int
    collection_appointment_at: Optional[str]
    genetic_test_ordered_at: Optional[str]
    specimen_collected_at: Optional[str]
    chain_of_custody_ok: bool
    specimen_rejection_count: int
    genetic_probability_pct: Optional[float]
    genetic_cost_cents: Optional[int]
    genetic_cost_liable_party: str
    established_at: Optional[str]
    established_method: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportOrder(TypedDict, total=False):
    """A support order and the guideline worksheet that produced it."""

    id: str
    case_id: str
    order_type: str
    origin_state_code: str
    status: str
    effective_date: str
    terminated_date: Optional[str]
    superseded_by_order_id: Optional[str]
    guideline_monthly_cents: Optional[int]
    guideline_cp_income_cents: Optional[int]
    guideline_ncp_income_cents: Optional[int]
    guideline_basic_obligation_cents: Optional[int]
    guideline_ncp_share_ratio: Optional[float]
    multi_family_credit_cents: int
    imputation_applied: bool
    medical_support_monthly_cents: int
    requested_monthly_cents: Optional[int]
    monthly_obligation_cents: Optional[int]
    arrears_recovery_monthly_cents: int
    deviation_applied: bool
    deviation_requested_cents: Optional[int]
    deviation_reason: Optional[str]
    deviation_rejection_count: int
    drafted_by_user_id: Optional[str]
    findings_approved_by_user_id: Optional[str]
    next_accrual_due_date: Optional[str]
    review_eligible_date: str
    vacate_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    """A registered payor of income."""

    id: str
    legal_name: str
    fein: str
    state_code: str
    pay_frequency: str
    remittance_fee_cents: int
    statutory_cap_pct: Optional[float]
    active_iwo_count: int
    created_at: str
    updated_at: str
    version: int


class IncomeWithholdingOrder(TypedDict, total=False):
    """A withholding order, carrying two independent status dimensions."""

    id: str
    order_id: str
    case_id: str
    employer_id: str
    jurisdiction_state_code: str
    service_status: str
    remittance_status: str
    reported_disposable_income_cents: Optional[int]
    disposable_income_cents: int
    arrears_recovery_cents: int
    requested_amount_cents: int
    federal_cap_pct: float
    ccpa_cap_pct: float
    ccpa_cap_amount_cents: int
    withholding_amount_cents: int
    employer_fee_cents: int
    served_at: Optional[str]
    first_withholding_due_at: Optional[str]
    next_remittance_due_at: Optional[str]
    missed_remittance_count: int
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObligationCharge(TypedDict, total=False):
    """An immutable financial event: carries only ``id`` and ``created_at``."""

    id: str
    case_id: str
    order_id: str
    charge_type: str
    status: str
    period_start_date: str
    period_end_date: str
    due_date: str
    amount_cents: int
    paid_cents: int
    unpaid_balance_cents: int
    interest_accrued_cents: int
    created_at: str


class PaymentTransaction(TypedDict, total=False):
    """An immutable financial event: carries only ``id`` and ``created_at``."""

    id: str
    case_id: str
    iwo_id: Optional[str]
    compromise_offer_id: Optional[str]
    source: str
    amount_cents: int
    received_at: str
    applied_current_cents: int
    applied_medical_cents: int
    applied_arrears_cents: int
    applied_interest_cents: int
    applied_genetic_cost_cents: int
    unapplied_credit_cents: int
    disbursed_to_cp_cents: int
    retained_by_state_cents: int
    created_at: str


class ModificationReview(TypedDict, total=False):
    """A review of an entered order against the substantial-change test."""

    id: str
    case_id: str
    order_id: str
    trigger_type: str
    status: str
    current_obligation_snapshot_cents: int
    recalculated_guideline_cents: Optional[int]
    variance_numerator_cents: Optional[int]
    substantial_change_met: Optional[bool]
    info_requested_reason: Optional[str]
    info_request_count: int
    review_eligible_date: str
    screened_at: Optional[str]
    proposed_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict, total=False):
    """An enforcement remedy and its certification, notice and contest record."""

    id: str
    case_id: str
    action_type: str
    status: str
    arrears_certified_snapshot_cents: int
    eligibility_threshold_cents: int
    proposed_by_user_id: str
    notice_sent_at: Optional[str]
    contest_deadline_at: Optional[str]
    contested_at: Optional[str]
    contest_grounds: Optional[str]
    review_decision: Optional[str]
    review_decided_by_user_id: Optional[str]
    activated_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    remedy_applied: bool
    created_at: str
    updated_at: str
    version: int


class InterstateReferral(TypedDict, total=False):
    """A UIFSA transmittal to or from a sister state."""

    id: str
    case_id: str
    direction: str
    other_state_code: str
    child_home_state_code: str
    transmittal_type: str
    status: str
    transmitted_at: Optional[str]
    ack_due_at: Optional[str]
    registered_at: Optional[str]
    controlling_order_id: Optional[str]
    controlling_order_state_code: Optional[str]
    returned_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompromiseOffer(TypedDict, total=False):
    """An arrears compromise offer with frozen settlement terms."""

    id: str
    case_id: str
    status: str
    installment_count: int
    principal_due_snapshot_cents: int
    interest_due_snapshot_cents: int
    pre_waiver_total_cents: int
    waiver_tier_pct: float
    interest_waiver_cents: int
    settlement_total_cents: int
    monthly_installment_cents: int
    final_installment_cents: int
    compliance_payment_count: int
    accepted_at: Optional[str]
    next_installment_due_date: Optional[str]
    defaulted_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseLedger(TypedDict, total=False):
    """The computed ledger read, reporting both interest measures side by side."""

    case_id: str
    as_of_date: str
    arrears_principal_cents: int
    assigned_arrears_cents: int
    unassigned_arrears_cents: int
    statutory_interest_cents: int
    aggregate_interest_cents: int
    interest_written_off_cents: int
    interest_collected_cents: int
    interest_receivable_cents: int
    unapplied_credit_cents: int


class PaginationMeta(TypedDict, total=False):
    """The pagination block every list response carries in ``meta``."""

    limit: int
    offset: int
    total_count: int
    has_more: bool


EntityList = List[JsonDict]

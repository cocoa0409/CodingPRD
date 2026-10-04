"""Domain types: entity TypedDicts, status enums and role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    AGENCY_PRODUCER = "AgencyProducer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    RISK_CONSULTANT = "RiskConsultant"
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_REPORTER = "ComplianceReporter"
    ANONYMOUS = "Anonymous"


class PropertyBasePosture(str, Enum):
    PENDING_APPRAISAL = "PENDING_APPRAISAL"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    UNDERWRITABLE = "UNDERWRITABLE"
    DECLINED = "DECLINED"


class PropertyPosture(str, Enum):
    WRITE_FROZEN = "WRITE_FROZEN"
    REFERRAL_REQUIRED = "REFERRAL_REQUIRED"
    WRITE_ELIGIBLE = "WRITE_ELIGIBLE"


class MitigationBand(str, Enum):
    CLEARED = "CLEARED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class AppraisalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ScheduledItemStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ATTACHED = "ATTACHED"
    REJECTED = "REJECTED"


class MitigationRequirementStatus(str, Enum):
    IMPOSED = "IMPOSED"
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"
    WAIVED = "WAIVED"


class RiskConsultationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    VENDOR_ASSIGNED = "VENDOR_ASSIGNED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REFERRED = "REFERRED"
    APPROVED = "APPROVED"
    ATTACHED = "ATTACHED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class NonRenewalNoticeStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    EFFECTIVE = "EFFECTIVE"
    RESCINDED = "RESCINDED"


class ReplacementProvision(str, Enum):
    GUARANTEED = "GUARANTEED"
    EXTENDED = "EXTENDED"
    NONE = "NONE"


class RiskTier(str, Enum):
    MANAGED = "MANAGED"
    REVIEW = "REVIEW"
    SURCHARGE = "SURCHARGE"
    REFER = "REFER"


# ─── common_fields: true — id + created_at + updated_at + version ──────────────

class RiskZone(TypedDict):
    id: str
    zone_code: str
    state_code: str
    wildland_urban_interface_band: str
    sustained_wind_mph: int
    mitigation_band_multiplier: float
    mitigated_loss_multiplier: float
    concentration_ratio_pct: float
    concentration_band: str
    freeze_active: bool
    exposure_band: str
    state_event: str
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    agency_code: str
    legal_name: str
    state_code: str
    servicing_tier: str
    delegated_authority_limit_cents: int
    active: bool
    concentration_ratio_pct: float
    concentration_band: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    risk_zone_id: str
    agency_id: str
    address_line: str
    grid_risk_block: str
    dwelling_replacement_cost_cents: int
    contents_replacement_cost_cents: int
    scheduled_valuation_cents: int
    appraised_at: Optional[str]
    total_insured_value_cents: int
    mitigation_band: str
    base_posture: str
    posture: str
    defense_in_progress: bool
    non_renewal_ground_activated: bool
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    property_id: str
    appraiser_name: str
    valuation_method: str
    appraised_on: str
    dwelling_cost_cents: int
    contents_cost_cents: int
    valuation_confidence_pct: float
    percent_complete: float
    status: str
    review_kind: str
    created_at: str
    updated_at: str
    version: int


class ScheduledItem(TypedDict):
    id: str
    property_id: str
    item_type: str
    declared_value_cents: int
    appraisal_doc_id: str
    appraisal_currency_months: int
    status: str
    attached_value_cents: int
    created_at: str
    updated_at: str
    version: int


class MitigationRequirement(TypedDict):
    id: str
    property_id: str
    requirement_code: str
    band_awarded: str
    source: str
    due_on: str
    status: str
    verification_count: int
    verified_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskConsultation(TypedDict):
    id: str
    property_id: str
    consultant_user_id: str
    scheduled_for: str
    duration_minutes: int
    status: str
    completed_at: Optional[str]
    report_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WildfireDefenseDispatch(TypedDict):
    id: str
    property_id: str
    risk_zone_id: str
    vendor_ref: Optional[str]
    state_event: str
    status: str
    priority_rank: int
    assigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    property_id: str
    agency_id: str
    risk_zone_id: str
    dwelling_coverage_cents: int
    contents_coverage_cents: int
    scheduled_coverage_cents: int
    loss_of_use_coverage_cents: int
    risk_score: int
    risk_tier: str
    required_dwelling_coverage_cents: int
    gross_premium_cents: int
    extended_replacement_premium_cents: int
    extended_replacement_limit_cents: int
    guaranteed_replacement_limit_cents: Optional[int]
    replacement_provision: str
    stress_reserve_cents: int
    committed_reserve_cents: int
    status: str
    bound_at: Optional[str]
    valuation_fingerprint: Optional[str]
    expected_property_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    enrollment_id: str
    property_id: str
    cause_of_loss: str
    loss_date: str
    reported_at: str
    reported_indemnity_cents: int
    adjuster_user_id: Optional[str]
    adjuster_override: bool
    settlement_amount_cents: int
    deductible_applied_cents: int
    limit_applied_cents: int
    cash_settlement_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class NonRenewalNotice(TypedDict):
    id: str
    enrollment_id: str
    property_id: str
    risk_zone_id: str
    ground: str
    issued_on: Optional[str]
    effective_on: str
    required_notice_days: int
    notice_period_days: int
    delay_exempt: bool
    seal_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── common_fields: false — append-only, carries ONLY id + created_at ─────────

class AppraisalDocument(TypedDict):
    id: str
    property_id: str
    item_class: str
    appraiser_name: str
    appraisal_date: str
    appraised_value_cents: int
    currency_months: int
    currency_status: str
    expires_on: str
    created_at: str
    # No updated_at, no version — append-only record.


class ManagedRiskEvent(TypedDict):
    id: str
    property_id: str
    event_type: str
    source_requirement_id: str
    derived_key: str
    sent_at: str
    body_summary: str
    created_at: str
    # No updated_at, no version — append-only record.
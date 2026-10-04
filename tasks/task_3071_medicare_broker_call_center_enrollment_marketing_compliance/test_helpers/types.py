"""Domain types: entity TypedDicts, status enums and the role enum for the
Medicare broker call-center compliance API.

Field names are taken verbatim from the PRD's data model. Entities that carry
the common resource property set (``id`` + ``created_at`` + ``updated_at`` +
``version``) are typed with all four; ``PharmacyNetworkEntry`` is the one
declared exception and carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ─── Status enums ────────────────────────────────────────────

class AgencyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CarrierContractType(str, Enum):
    CONTRACTED = "CONTRACTED"
    MARKETING_ONLY = "MARKETING_ONLY"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgentStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    LICENSED = "LICENSED"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LicenseStatus(str, Enum):
    VALID = "VALID"
    LAPSED = "LAPSED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPOINTED = "APPOINTED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProductType(str, Enum):
    MA = "MA"
    MAPD = "MAPD"
    PDP = "PDP"
    SNP = "SNP"


class CaptureChannel(str, Enum):
    TELEPHONIC_RECORDED = "TELEPHONIC_RECORDED"
    WRITTEN = "WRITTEN"
    ELECTRONIC = "ELECTRONIC"


class ScopeStatus(str, Enum):
    CAPTURED = "CAPTURED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"


class CallStatus(str, Enum):
    RINGING = "RINGING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    AMENDED = "AMENDED"


class RecordingStatus(str, Enum):
    RECORDED = "RECORDED"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NetworkTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class DirectoryNetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EFFECTUATED = "EFFECTUATED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DisenrollmentStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ENROLLED = "ENROLLED"
    RAPID_DISENROLLED = "RAPID_DISENROLLED"
    STANDARD_DISENROLLED = "STANDARD_DISENROLLED"


class LedgerEntryType(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"
    CHARGEBACK = "CHARGEBACK"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


class LedgerEntryStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class InternalTotalVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class ComplaintType(str, Enum):
    MISREPRESENTATION = "MISREPRESENTATION"
    SOA_MISSING = "SOA_MISSING"
    DISCLAIMER_MISSING = "DISCLAIMER_MISSING"
    RECORDING_MISSING = "RECORDING_MISSING"
    UNAPPROVED_MARKETING = "UNAPPROVED_MARKETING"
    PLAN_MISREPRESENTATION = "PLAN_MISREPRESENTATION"
    DISENROLLMENT_DELAY = "DISENROLLMENT_DELAY"


class ComplaintSource(str, Enum):
    BENEFICIARY = "BENEFICIARY"
    CMS = "CMS"
    CARRIER = "CARRIER"
    SECRET_SHOPPER = "SECRET_SHOPPER"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class CoachingType(str, Enum):
    SOA_RETRAINING = "SOA_RETRAINING"
    DISCLAIMER_RETRAINING = "DISCLAIMER_RETRAINING"
    MARKETING_RULES = "MARKETING_RULES"
    PLAN_DETAIL_ACCURACY = "PLAN_DETAIL_ACCURACY"
    RECORDING_RETENTION = "RECORDING_RETENTION"


class CoachingTrigger(str, Enum):
    COMPLAINT = "COMPLAINT"
    SECRET_SHOPPER = "SECRET_SHOPPER"
    MANUAL = "MANUAL"


class CoachingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DIRECTOR_OF_SALES = "DirectorOfSales"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LICENSING_COORDINATOR = "LicensingCoordinator"
    COACH = "Coach"
    CARRIER_INTEGRATION = "CarrierIntegration"
    LICENSED_AGENT = "LicensedAgent"
    ANY = "Any"


# ─── Entity TypedDicts (common_fields: true) ─────────────────

class Agency(TypedDict, total=False):
    id: str
    name: str
    service_center_code: str
    aep_start_date: str
    aep_end_date: str
    aep_daily_submission_capacity: int
    recording_retention_days: int
    soa_retention_days: int
    soa_max_age_days: int
    rapid_disenrollment_day_limit: int
    max_live_calls_per_agent: int
    max_open_coaching_per_agent: int
    compliance_posture: str
    posture_since: str
    substantiated_complaint_rate: float
    loss_ratio: float
    open_complaint_count: int
    commission_balance_cents: float
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    legal_name: str
    naic_number: str
    contract_type: str
    initial_commission_rate_pct: float
    renewal_commission_rate_pct: float
    chargeback_clawback_pct: float
    ack_expected_within_days: int
    effectuation_expected_within_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    agency_id: str
    full_name: str
    national_producer_number: str
    hire_date: str
    status: str
    licensed_state_count: int
    certified_carrier_count: int
    appointed_carrier_count: int
    live_call_count: int
    active_enrollment_count: int
    chargeback_tier: int
    substantiated_complaint_count: int
    compliance_risk_score: float
    coaching_flag: bool
    open_coaching_count: int
    created_at: str
    updated_at: str
    version: int


class AgentStateLicense(TypedDict, total=False):
    id: str
    agent_id: str
    state_code: str
    license_number: str
    issued_on: str
    expires_on: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class CarrierAppointment(TypedDict, total=False):
    id: str
    agent_id: str
    carrier_id: str
    state_code: str
    requested_on: str
    appointed_on: str
    terminated_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierCertification(TypedDict, total=False):
    id: str
    agent_id: str
    carrier_id: str
    product_type: str
    certified_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    agency_id: str
    full_name: str
    medicare_beneficiary_id: str
    date_of_birth: str
    state_code: str
    county_code: str
    drug_list: List[Dict[str, Any]]
    provider_npis: List[str]
    enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class ScopeOfAppointment(TypedDict, total=False):
    id: str
    member_id: str
    agent_id: str
    capture_channel: str
    plan_types_authorized: List[str]
    captured_on: str
    expires_on: str
    retained_until: str
    consumed_by_enrollment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CallSession(TypedDict, total=False):
    id: str
    agent_id: str
    member_id: str
    scope_of_appointment_id: str
    started_at: str
    scheduled_end_at: str
    actual_end_at: Optional[str]
    recording_id: Optional[str]
    recording_retained_until: str
    recording_status: str
    disclaimer_script_code: Optional[str]
    disclaimer_delivered: bool
    marketing_rule_set_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    carrier_id: str
    plan_id_code: str
    plan_type: str
    state_code: str
    county_code: str
    monthly_premium_cents: int
    annual_drug_deductible_cents: int
    star_rating: float
    formulary_id: str
    pharmacy_network_id: str
    provider_directory_id: str
    enrolled_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FormularyDrug(TypedDict, total=False):
    id: str
    plan_id: str
    drug_name: str
    rxcui: str
    tier: int
    monthly_copay_cents: int
    prior_authorization_required: bool
    covered: bool
    quantity_limit_days: int
    created_at: str
    updated_at: str
    version: int


class PharmacyNetworkEntry(TypedDict, total=False):
    # common_fields: false — append-only pairing, no updated_at, no version
    id: str
    plan_id: str
    pharmacy_npi: str
    pharmacy_name: str
    network_tier: str
    cost_share_multiplier_pct: float
    created_at: str


class ProviderDirectoryEntry(TypedDict, total=False):
    id: str
    plan_id: str
    provider_npi: str
    provider_name: str
    specialty: str
    network_status: str
    accepting_new_patients: bool
    last_attested_on: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    call_session_id: str
    member_id: str
    plan_id: str
    agent_id: str
    scope_of_appointment_id: str
    carrier_id: str
    effective_date: str
    submitted_on: str
    acknowledged_on: Optional[str]
    effectuated_on: Optional[str]
    submission_status: str
    disenrollment_status: str
    disenrollment_date: Optional[str]
    disenrollment_reason: Optional[str]
    disenrolled_day_number: Optional[int]
    is_rapid_disenrollment: bool
    provisional_commission_cents: float
    final_commission_cents: float
    created_at: str
    updated_at: str
    version: int


class CommissionLedgerEntry(TypedDict, total=False):
    id: str
    enrollment_id: str
    carrier_reconciliation_id: str
    entry_type: str
    amount_cents: float
    period_month: str
    posted_on: str
    status: str
    clawback_pct_applied: float
    memo: str
    created_at: str
    updated_at: str
    version: int


class CarrierReconciliation(TypedDict, total=False):
    id: str
    carrier_id: str
    period_month: str
    carrier_reported_total_cents: int
    internal_total_cents: float
    variance_cents: float
    variance_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    agent_id: str
    complaint_type: str
    source: str
    severity: str
    filed_on: str
    shopper_score: Optional[int]
    soa_requested_correctly: Optional[bool]
    disclaimer_played: Optional[bool]
    approved_marketing_used: Optional[bool]
    status: str
    finding_code: Optional[str]
    substantiated_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoachingAssignment(TypedDict, total=False):
    id: str
    agent_id: str
    complaint_id: Optional[str]
    coaching_type: str
    triggered_by: str
    assigned_on: str
    due_on: str
    completed_on: Optional[str]
    overdue_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [name for name in dir() if not name.startswith("_")]
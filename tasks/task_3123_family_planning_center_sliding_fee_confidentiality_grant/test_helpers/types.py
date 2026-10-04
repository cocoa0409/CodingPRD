"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class AffiliateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CatalogEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AssessmentStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ProviderType(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    NP = "NP"
    RN = "RN"
    COUNSELOR = "COUNSELOR"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class EncounterClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EncounterBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIMED = "CLAIMED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ReferralReason(str, Enum):
    OUT_OF_SCOPE_STATE_LAW = "OUT_OF_SCOPE_STATE_LAW"
    OUT_OF_SCOPE_AFFILIATE = "OUT_OF_SCOPE_AFFILIATE"
    CAPACITY = "CAPACITY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class HoldScope(str, Enum):
    RECORD_VIEW = "RECORD_VIEW"
    BILLING_CORRESPONDENCE = "BILLING_CORRESPONDENCE"
    ALL = "ALL"


class IncomeBasis(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    SELF_DECLARED = "SELF_DECLARED"


class EncounterChannel(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"


class ValuationVariant(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"


class UserRole(str, Enum):
    GRANT_ADMINISTRATOR = "GrantAdministrator"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    CLINICIAN = "Clinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    CARE_COORDINATOR = "CareCoordinator"
    SUPPLY_COORDINATOR = "SupplyCoordinator"
    PRIVACY_OFFICER = "PrivacyOfficer"


class Affiliate(TypedDict, total=False):
    id: str
    affiliate_code: str
    state_code: str
    grant_cycle_open: bool
    low_income_priority_quota: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCatalogEntry(TypedDict, total=False):
    id: str
    affiliate_id: str
    service_code: str
    in_scope: bool
    telehealth_eligible: bool
    full_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeScheduleTier(TypedDict, total=False):
    id: str
    affiliate_id: str
    tier_code: str
    fpl_pct_min_inclusive: int
    fpl_pct_max_exclusive: int
    discount_pct: int
    nominal_copay_cents: int
    requires_documentation: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    affiliate_id: str
    external_ref: str
    date_of_birth: str
    is_minor: bool
    confidentiality_flag: bool
    insurance_policy_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HouseholdAssessment(TypedDict, total=False):
    id: str
    patient_id: str
    household_size: int
    annual_income_cents: int
    income_basis: str
    fpl_pct: int
    assigned_tier_code: str
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    affiliate_id: str
    display_name: str
    provider_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderLicense(TypedDict, total=False):
    id: str
    provider_id: str
    state_code: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    patient_id: str
    affiliate_id: str
    service_code: str
    provider_id: str
    channel: str
    patient_location_state: Optional[str]
    scheduled_start: str
    scheduled_end: str
    assessment_id: str
    patient_charge_cents: int
    clinical_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    encounter_id: str
    policy_id: Optional[str]
    confidential_suppression: bool
    billed_cents: int
    paid_cents: int
    recouped_cents: int
    net_receivable_cents: int
    submission_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContraceptiveStockLot(TypedDict, total=False):
    id: str
    affiliate_id: str
    device_code: str
    lot_number: str
    unit_cost_cents: int
    on_hand: int
    reserved_out: int
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class DeviceReservation(TypedDict, total=False):
    id: str
    encounter_id: str
    lot_id: str
    is_rapid_reinsertion: bool
    expulsion_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralOrder(TypedDict, total=False):
    id: str
    encounter_id: str
    requested_service_code: str
    receiving_org: str
    reason_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantReport(TypedDict, total=False):
    id: str
    affiliate_id: str
    period_start: str
    period_end: str
    encounter_count: int
    low_income_encounter_count: int
    minor_encounter_count: int
    device_value_cents: int
    valuation_variant: str
    low_income_quota_met: bool
    amendment_of: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivacyHold(TypedDict, total=False):
    id: str
    patient_id: str
    hold_start: str
    hold_end: str
    scope: str
    authorized_staff_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int

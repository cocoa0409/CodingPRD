"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this contract carries the common system-managed fields
id, created_at, updated_at, and version (the PRD states that no entity omits
updated_at or version), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ELIGIBILITY_CLERK = "EligibilityClerk"
    CARE_COORDINATOR = "CareCoordinator"
    NETWORK_MANAGER = "NetworkManager"
    TPA_ADMINISTRATOR = "TPAAdministrator"
    PROVIDER_REP = "ProviderRep"
    VETERAN = "Veteran"
    SYSTEM_PHARMACIST = "SystemPharmacist"


class ServiceCategory(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    SPECIALTY_CARE = "SPECIALTY_CARE"


class GeoClassification(str, Enum):
    URBAN = "URBAN"
    RURAL = "RURAL"


class ContractScheduling(str, Enum):
    TPA = "TPA"
    VAMC = "VAMC"


class SchedulingResponsibility(str, Enum):
    TPA = "TPA"
    VAMC = "VAMC"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CredentialingStatus(str, Enum):
    PENDING = "PENDING"
    CREDENTIALED = "CREDENTIALED"
    SUSPENDED = "SUSPENDED"
    DECREDENTIALED = "DECREDENTIALED"


class AssessmentStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class AuthorizationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    DOCS_SUSPENDED = "DOCS_SUSPENDED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExtensionRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExtensionDenialReason(str, Enum):
    DOCS_OVERDUE = "DOCS_OVERDUE"
    AUTH_CANCELLED = "AUTH_CANCELLED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TimelinessAnchor(str, Enum):
    AUTHORIZED_AT = "AUTHORIZED_AT"
    REQUESTED_DATE = "REQUESTED_DATE"


class DocumentationStatus(str, Enum):
    AWAITED = "AWAITED"
    RECEIVED = "RECEIVED"
    OVERDUE = "OVERDUE"
    ACCEPTED = "ACCEPTED"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PAID = "PAID"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class ClaimDenialReason(str, Enum):
    PROVIDER_DECREDENTIALED = "PROVIDER_DECREDENTIALED"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    DUPLICATE = "DUPLICATE"
    OTHER = "OTHER"


class PriorityBand(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class UrgentCareVisitStatus(str, Enum):
    RECORDED = "RECORDED"


class PrescriptionFillStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FILLED = "FILLED"
    REFUSED = "REFUSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class CareStation(TypedDict):
    id: str
    name: str
    latitude: float
    longitude: float
    primary_wait_days: int
    specialty_wait_days: int
    service_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ThirdPartyAdministrator(TypedDict):
    id: str
    name: str
    region_code: str
    contract_status: str
    adjudicated_events: int
    denied_events: int
    denial_rate: float
    created_at: str
    updated_at: str
    version: int


class CommunityProvider(TypedDict):
    id: str
    tpa_id: str
    name: str
    service_codes: List[str]
    contract_rates: Dict[str, int]
    contract_scheduling: str
    credentialing_status: str
    latitude: float
    longitude: float
    lifetime_paid_cents: int
    current_paid_cents: int
    reversed_cents: int
    created_at: str
    updated_at: str
    version: int


class Veteran(TypedDict):
    id: str
    full_name: str
    home_station_id: str
    priority_group: int
    home_latitude: float
    home_longitude: float
    created_at: str
    updated_at: str
    version: int


class EligibilityAssessment(TypedDict):
    id: str
    veteran_id: str
    service_code: str
    service_category: str
    geo_classification: str
    choice_requested: bool
    drive_time_minutes: float
    wait_days: int
    service_available: bool
    drive_standard_failed: bool
    wait_standard_failed: bool
    choice_granted: bool
    eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralAuthorization(TypedDict):
    id: str
    veteran_id: str
    assessment_id: str
    provider_id: str
    tpa_id: str
    service_code: str
    authorized_visits: int
    duration_days: int
    start_date: str
    end_date_exclusive: str
    extended_visits: int
    reserved_visits: int
    completed_visits: int
    remaining_visits: int
    scheduling_responsibility: str
    authorized_at: Optional[str]
    docs_suspension_return_state: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    referral_authorization_id: str
    requested_visits: int
    requested_extra_days: int
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    referral_authorization_id: str
    provider_id: str
    scheduled_start: str
    requested_date: str
    timeliness_anchor: str
    within_standard: bool
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalDocumentation(TypedDict):
    id: str
    appointment_id: str
    referral_authorization_id: str
    content_ref: Optional[str]
    status: str
    deadline_at: str
    rejection_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimServiceLine(TypedDict):
    service_code: str
    service_category: str
    units: int
    unit_billed_cents: int


class Claim(TypedDict):
    id: str
    referral_authorization_id: str
    provider_id: str
    tpa_id: str
    service_date: str
    service_lines: List[ClaimServiceLine]
    billed_total_cents: int
    paid_amount_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    resubmit_count: int
    reversed_reason: Optional[str]
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class UrgentCareVisit(TypedDict):
    id: str
    veteran_id: str
    facility_name: str
    visit_date: str
    fiscal_year: int
    priority_band: str
    visit_index_in_fy: int
    copay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrescriptionFillRequest(TypedDict):
    id: str
    urgent_care_visit_id: Optional[str]
    appointment_id: Optional[str]
    medication_name: str
    days_supply: int
    controlled_substance: bool
    status: str
    decided_at: Optional[str]
    refusal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int

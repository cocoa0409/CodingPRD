"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API is a full-shape resource: all fifteen carry the four
system-managed properties ``id``, ``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    NATIONAL_HQ_ADMIN = "NationalHQAdmin"
    REGIONAL_COORDINATOR = "RegionalCoordinator"
    SHELTER_MANAGER = "ShelterManager"
    VOLUNTEER = "Volunteer"
    CASEWORKER = "Caseworker"
    FINANCE_OFFICER = "FinanceOfficer"
    BLOOD_SERVICES_COORDINATOR = "BloodServicesCoordinator"
    CLIENT = "Client"


class ShelterPosture(str, Enum):
    PENDING_OPEN = "PENDING_OPEN"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CONSOLIDATING = "CONSOLIDATING"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class CredentialStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class DeploymentAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"
    RESTING = "RESTING"
    UNAVAILABLE = "UNAVAILABLE"


class DeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    ON_SHIFT = "ON_SHIFT"
    ROTATION_ENDED = "ROTATION_ENDED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_OUT = "CHECKED_OUT"
    TRANSFERRED = "TRANSFERRED"
    REUNIFIED = "REUNIFIED"


class ReunificationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    RECOVERY_PLANNING = "RECOVERY_PLANNING"
    REFERRED = "REFERRED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    INELIGIBLE = "INELIGIBLE"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DuplicationCheckResult(str, Enum):
    CLEAR = "CLEAR"
    PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
    DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"


class AssistanceType(str, Enum):
    HOUSING = "HOUSING"
    FOOD = "FOOD"
    MEDICAL = "MEDICAL"
    TRANSPORTATION = "TRANSPORTATION"
    UTILITY = "UTILITY"
    FUNERAL = "FUNERAL"
    OCCUPATIONAL = "OCCUPATIONAL"


class AssistanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBILITY_VERIFIED = "ELIGIBILITY_VERIFIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CARD_ISSUED = "CARD_ISSUED"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"


class CardStatus(str, Enum):
    NOT_ISSUED = "NOT_ISSUED"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    DONOR_RESTRICTED_DISASTER = "DONOR_RESTRICTED_DISASTER"
    DONOR_RESTRICTED_BLOOD = "DONOR_RESTRICTED_BLOOD"
    DONOR_RESTRICTED_LOCAL = "DONOR_RESTRICTED_LOCAL"


class OperationPhase(str, Enum):
    MOBILIZATION = "MOBILIZATION"
    ACTIVE = "ACTIVE"
    DEMOBILIZATION = "DEMOBILIZATION"
    CLOSED = "CLOSED"


class BloodDriveStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CostCategory(str, Enum):
    SHELTER_OPERATIONS = "SHELTER_OPERATIONS"
    FEEDING = "FEEDING"
    VOLUNTEER_TRAVEL = "VOLUNTEER_TRAVEL"
    FINANCIAL_ASSISTANCE = "FINANCIAL_ASSISTANCE"
    HEALTH_SERVICES = "HEALTH_SERVICES"
    BLOOD_COLLECTION = "BLOOD_COLLECTION"
    LOGISTICS = "LOGISTICS"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    REVERSAL = "REVERSAL"


class Region(TypedDict):
    id: str
    code: str
    name: str
    state_codes: List[str]
    coordinator_user_id: str
    volunteer_pool_target: int
    authorized_agency_codes: List[str]
    available_volunteer_count: int
    deployed_volunteer_count: int
    blood_continuity_index: float
    blood_continuity_status: str
    created_at: str
    updated_at: str
    version: int


class DisasterReliefOperation(TypedDict):
    id: str
    incident_code: str
    incident_type: str
    declared_at: str
    region_id: str
    phase: str
    open_shelter_count: int
    restricted_fund_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ShelterSite(TypedDict):
    id: str
    facility_name: str
    address_line: str
    region_id: str
    capacity_beds: int
    accessibility_rating: str
    functional_needs_support: bool
    generator_onsite: bool
    agreement_expires_at: str
    agreement_status: str
    capacity_verified_beds: int
    accessibility_verified: bool
    functional_needs_verified: bool
    last_inspection_at: Optional[str]
    inspection_result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShelterOperation(TypedDict):
    id: str
    shelter_site_id: str
    disaster_relief_operation_id: str
    opened_at: Optional[str]
    posture: str
    occupied_beds: int
    registered_client_count: int
    reunification_pending_count: int
    staffed_volunteer_count: int
    staffing_sufficiency: float
    meals_served_total: int
    feeding_cost_cents: int
    health_service_count: int
    operational_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    home_region_id: str
    qualified_role_codes: List[str]
    credential_status: str
    credential_refreshed_at: Optional[str]
    credential_expires_at: Optional[str]
    deployment_availability: str
    rotation_days_used_ytd: int
    created_at: str
    updated_at: str
    version: int


class VolunteerDeployment(TypedDict):
    id: str
    volunteer_id: str
    disaster_relief_operation_id: str
    shelter_operation_id: Optional[str]
    role_code: str
    travel_mode: str
    rotation_start_at: str
    rotation_days: int
    travel_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    volunteer_deployment_id: str
    shelter_operation_id: str
    functional_area: str
    shift_start_at: str
    shift_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    household_size: int
    region_id: str
    primary_client_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShelterRegistration(TypedDict):
    id: str
    shelter_operation_id: str
    client_id: str
    requested_bed_code: Optional[str]
    dormitory_bed_code: Optional[str]
    occupied_from_at: str
    occupied_until_at: Optional[str]
    functional_needs_flag: bool
    reunification_reference: Optional[str]
    reunification_status: str
    reunification_verified_by_user_id: Optional[str]
    health_service_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClientCase(TypedDict):
    id: str
    client_id: str
    disaster_relief_operation_id: str
    assigned_caseworker_id: str
    status: str
    eligibility_status: str
    eligibility_verified_by_user_id: Optional[str]
    recovery_plan_revision: int
    recovery_plan_summary: Optional[str]
    entitlement_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    client_case_id: str
    agency_code: str
    assistance_type: str
    estimated_value_cents: int
    status: str
    duplication_check_result: str
    created_at: str
    updated_at: str
    version: int


class AssistanceRequest(TypedDict):
    id: str
    client_case_id: str
    fund_pool_id: str
    assistance_type: str
    requested_amount_cents: int
    duplication_offset_cents: int
    approved_amount_cents: int
    status: str
    approved_by_user_id: Optional[str]
    card_number_masked: Optional[str]
    card_status: str
    redemption_deadline_at: Optional[str]
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundPool(TypedDict):
    id: str
    fund_code: str
    restriction_type: str
    region_id: Optional[str]
    total_received_cents: int
    committed_cents: int
    disbursed_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class CostLedgerEntry(TypedDict):
    id: str
    disaster_relief_operation_id: str
    fund_pool_id: str
    cost_category: str
    amount_cents: int
    entry_type: str
    incurred_at: str
    created_at: str
    updated_at: str
    version: int


class BloodDrive(TypedDict):
    id: str
    region_id: str
    site_name: str
    scheduled_start_at: str
    scheduled_end_at: str
    target_units: int
    collected_units: int
    usable_units: int
    status: str
    created_at: str
    updated_at: str
    version: int

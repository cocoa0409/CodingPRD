"""Domain types: entity TypedDicts, status enums, and the role enum.

Every resource carries the common system fields id, created_at, updated_at
and version (PRD common-resource-properties section).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ELIGIBILITY_APPLICANT = "EligibilityApplicant"
    VERIFICATION_OFFICER = "VerificationOfficer"
    MEMBER = "Member"
    BENEFITS_OFFICER = "BenefitsOfficer"
    PRODUCT_ADMINISTRATOR = "ProductAdministrator"
    PLATFORM_ADMIN = "PlatformAdmin"


class EligibilityCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    MORE_INFO_REQUIRED = "MORE_INFO_REQUIRED"


class BasisType(str, Enum):
    DIRECT_SERVICE = "DIRECT_SERVICE"
    FAMILY_DERIVATION = "FAMILY_DERIVATION"
    CADET_APPOINTMENT = "CADET_APPOINTMENT"


class ClaimedRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    WIDOW_WIDOWER = "WIDOW_WIDOWER"
    CHILD = "CHILD"
    STEPCHILD = "STEPCHILD"
    FORMER_SPOUSE = "FORMER_SPOUSE"


class EligibilityCategory(str, Enum):
    OFFICER_CADET = "OFFICER_CADET"
    ENLISTED_ACTIVE = "ENLISTED_ACTIVE"
    VETERAN_HONORABLE = "VETERAN_HONORABLE"
    FAMILY_SPOUSE = "FAMILY_SPOUSE"
    FAMILY_WIDOW = "FAMILY_WIDOW"
    FAMILY_CHILD = "FAMILY_CHILD"


class ServiceBranch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    COAST_GUARD = "COAST_GUARD"
    SPACE_FORCE = "SPACE_FORCE"
    NOAA_CORPS = "NOAA_CORPS"
    PHS_CORPS = "PHS_CORPS"


class ServiceComponent(str, Enum):
    ACTIVE_DUTY = "ACTIVE_DUTY"
    RESERVE = "RESERVE"
    NATIONAL_GUARD = "NATIONAL_GUARD"
    CADET = "CADET"


class DischargeCharacterization(str, Enum):
    HONORABLE = "HONORABLE"
    GENERAL_UNDER_HONORABLE = "GENERAL_UNDER_HONORABLE"
    OTHER_THAN_HONORABLE = "OTHER_THAN_HONORABLE"
    BAD_CONDUCT = "BAD_CONDUCT"
    DISHONORABLE = "DISHONORABLE"
    MEDICAL = "MEDICAL"
    ENTRY_LEVEL = "ENTRY_LEVEL"
    STILL_SERVING = "STILL_SERVING"


class DocType(str, Enum):
    DD214 = "DD214"
    NGB22 = "NGB22"
    MARRIAGE_CERTIFICATE = "MARRIAGE_CERTIFICATE"
    BIRTH_CERTIFICATE = "BIRTH_CERTIFICATE"
    ADOPTION_DECREE = "ADOPTION_DECREE"
    DIVORCE_DECREE = "DIVORCE_DECREE"
    DEATH_CERTIFICATE = "DEATH_CERTIFICATE"
    LEAVE_EARNINGS_STATEMENT = "LEAVE_EARNINGS_STATEMENT"
    ORDERS = "ORDERS"


class AuthenticityChannel(str, Enum):
    SELF_DECLARED = "SELF_DECLARED"
    ISSUER_CONFIRMED = "ISSUER_CONFIRMED"
    ARCHIVES_CONFIRMED = "ARCHIVES_CONFIRMED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECEASED = "DECEASED"
    REVOKED = "REVOKED"


class DeploymentPosture(str, Enum):
    NONE = "NONE"
    DEPLOYED = "DEPLOYED"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class AddrType(str, Enum):
    DOMESTIC_RESIDENCE = "DOMESTIC_RESIDENCE"
    MILITARY_APO_FPO_DPO = "MILITARY_APO_FPO_DPO"
    OVERSEAS_FOREIGN = "OVERSEAS_FOREIGN"


class DeploymentOrderStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    RATE_REDUCTION = "RATE_REDUCTION"
    CLAIM_DEFERRAL = "CLAIM_DEFERRAL"
    LEASE_TERMINATION = "LEASE_TERMINATION"


class ProtectionClaimStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ProductLine(str, Enum):
    BANKING = "BANKING"
    INSURANCE = "INSURANCE"
    INVESTMENT = "INVESTMENT"


class EntitlementStatus(str, Enum):
    OPEN = "OPEN"
    GRANDFATHERED = "GRANDFATHERED"
    CLOSED = "CLOSED"


class ClosureReason(str, Enum):
    MEMBER_LOSS = "MEMBER_LOSS"
    VOLUNTARY = "VOLUNTARY"
    GRANDFATHERED_RETIRE = "GRANDFATHERED_RETIRE"


class SurvivorCaseStatus(str, Enum):
    OPEN = "OPEN"
    GRANTED = "GRANTED"
    CLOSED = "CLOSED"


class EligibilityCase(TypedDict, total=False):
    id: str
    applicant_legal_name: str
    applicant_dob: str
    basis_type: str
    sponsor_member_id: Optional[str]
    claimed_relationship: Optional[str]
    eligibility_category: Optional[str]
    adoption_or_divorce_flag: bool
    member_id: Optional[str]
    verification_officer_id: Optional[str]
    record_reconstruction_officer_id: Optional[str]
    denial_reason: Optional[str]
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRecord(TypedDict, total=False):
    id: str
    case_id: str
    branch: str
    component: str
    rank_grade: str
    service_start_date: str
    service_end_date: Optional[str]
    discharge_characterization: str
    service_verified: bool
    service_days: int
    created_at: str
    updated_at: str
    version: int


class EvidenceDocument(TypedDict, total=False):
    id: str
    case_id: str
    doc_type: str
    issuing_authority: str
    issued_on: str
    covers_service_record_id: Optional[str]
    authenticity_channel: str
    content_hash: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    member_number: str
    legal_name: str
    dob: str
    case_id: str
    eligibility_category: str
    sponsor_member_id: Optional[str]
    claimed_relationship: Optional[str]
    household_id: Optional[str]
    lineage_depth: int
    status: str
    deployment_posture: str
    product_matrix_cache: dict
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    household_name: str
    primary_member_id: str
    aggregate_product_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddressAssignment(TypedDict, total=False):
    id: str
    member_id: str
    addr_type: str
    line1: str
    city: str
    region_code: str
    postal_code: str
    country_code: str
    effective_from: str
    effective_to: Optional[str]
    is_duty_station: bool
    created_at: str
    updated_at: str
    version: int


class DeploymentOrder(TypedDict, total=False):
    id: str
    member_id: str
    orders_number: str
    theater: str
    start_date: str
    end_date: Optional[str]
    scra_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionClaim(TypedDict, total=False):
    id: str
    member_id: str
    deployment_order_id: Optional[str]
    claim_type: str
    obligation_label: str
    base_rate_bps: Optional[int]
    monthly_interest_cents: Optional[int]
    periods_granted: Optional[int]
    total_relief_cents: Optional[int]
    approval_effective_date: Optional[str]
    approved_by_officer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductOffering(TypedDict, total=False):
    id: str
    product_code: str
    product_line: str
    product_name: str
    allowed_categories: List[str]
    requires_active_status: bool
    deployment_enhanced: bool
    is_active_flag: bool
    created_at: str
    updated_at: str
    version: int


class ProductEntitlement(TypedDict, total=False):
    id: str
    member_id: str
    product_offering_id: str
    opened_at: str
    closure_reason: Optional[str]
    grandfathered: bool
    exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurvivorSupportCase(TypedDict, total=False):
    id: str
    member_id: str
    beneficiary_member_id: str
    continuance_months: Optional[int]
    continuance_amount_cents: Optional[int]
    transfer_household_id: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int

"""Domain types: entity TypedDicts, status enums, role enum.

Per the PRD's common-resource-properties rule, most resources carry
id + created_at + updated_at + version; ReferralNote and OutcomeRecord carry
only id + created_at (both updated_at and version are absent on them).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_COORDINATOR = "NetworkCoordinator"
    CASE_WORKER = "CaseWorker"
    ORG_ADMIN = "OrgAdmin"
    FUNDER_ADMIN = "FunderAdmin"


class OrgType(str, Enum):
    CBO = "CBO"
    CLINIC = "CLINIC"
    FUNDER = "FUNDER"


class FunderType(str, Enum):
    HEALTH_PLAN = "HEALTH_PLAN"
    PUBLIC_AGENCY = "PUBLIC_AGENCY"
    NONE = "NONE"


class OrganizationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OfferingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class Gender(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    NONBINARY = "NONBINARY"
    UNDISCLOSED = "UNDISCLOSED"


class Race(str, Enum):
    AMERICAN_INDIAN = "AMERICAN_INDIAN"
    ASIAN = "ASIAN"
    BLACK = "BLACK"
    PACIFIC_ISLANDER = "PACIFIC_ISLANDER"
    WHITE = "WHITE"
    MULTIRACIAL = "MULTIRACIAL"
    UNDISCLOSED = "UNDISCLOSED"


class Ethnicity(str, Enum):
    HISPANIC = "HISPANIC"
    NON_HISPANIC = "NON_HISPANIC"
    UNDISCLOSED = "UNDISCLOSED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ConsentScope(str, Enum):
    FULL = "FULL"
    MINIMUM_NECESSARY = "MINIMUM_NECESSARY"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    ROUTED = "ROUTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    IN_SERVICE = "IN_SERVICE"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ReferralUrgency(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class OutcomeCode(str, Enum):
    DELIVERED = "DELIVERED"
    NOT_REACHED = "NOT_REACHED"
    CLIENT_DECLINED = "CLIENT_DECLINED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"


class NoteVisibility(str, Enum):
    NETWORK = "NETWORK"
    SENDER_ONLY = "SENDER_ONLY"
    RECEIVER_ONLY = "RECEIVER_ONLY"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"
    PAID = "PAID"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FAILED = "FAILED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"


class CareNetwork(TypedDict, total=False):
    id: str
    name: str
    coordinator_org_name: str
    max_reassignment_count: int
    auto_accept_window_hours: int
    unresolved_aging_days: int
    referral_expiry_days: int
    network_escrow_cents: int
    network_escrow_reserved_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceTaxonomyCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Organization(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    funder_type: str
    ein: str
    status: str
    suspension_reason: Optional[str]
    payable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceOffering(TypedDict, total=False):
    id: str
    organization_id: str
    category_code: str
    description: str
    min_client_age: int
    max_client_age: int
    eligible_zip_codes: List[str]
    eligible_genders: List[str]
    income_cap_annual_cents: Optional[int]
    capacity_total: int
    capacity_consumed: int
    capacity_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    zip_code: str
    gender: str
    annual_income_cents: Optional[int]
    race: str
    ethnicity: str
    language: str
    veteran_status: bool
    open_referral_count: int
    created_at: str
    updated_at: str
    version: int


class DataSharingAgreement(TypedDict, total=False):
    id: str
    party_a_org_id: str
    party_b_org_id: str
    effective_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consent(TypedDict, total=False):
    id: str
    client_id: str
    sender_org_id: str
    receiver_org_id: str
    scope: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    client_id: str
    sender_org_id: str
    receiver_org_id: str
    service_offering_id: str
    consent_id: str
    category_code: str
    urgency: str
    status: str
    service_started_at: Optional[str]
    reassignment_count: int
    aging_days: int
    reopen_count: int
    outcome_code: Optional[str]
    delivered_units: int
    created_at: str
    updated_at: str
    version: int


# ReferralNote is lean: id + created_at only, no updated_at / version.
class ReferralNote(TypedDict, total=False):
    id: str
    referral_id: str
    author_org_id: str
    body: str
    visibility: str
    created_at: str


# OutcomeRecord is lean: id + created_at only, no updated_at / version.
class OutcomeRecord(TypedDict, total=False):
    id: str
    referral_id: str
    outcome_code: str
    delivered_units: int
    reported_by_org_id: str
    reported_at: str
    billable: bool
    created_at: str


class ServiceRateCard(TypedDict, total=False):
    id: str
    funder_org_id: str
    category_code: str
    rate_cents_per_unit: int
    min_units: int
    tier2_rate_cents_per_unit: Optional[int]
    monthly_cap_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentClaim(TypedDict, total=False):
    id: str
    referral_id: str
    funder_org_id: str
    provider_org_id: str
    claimed_units: int
    reviewed_by_user_id: Optional[str]
    provisional_amount_cents: int
    approved_amount_cents: Optional[int]
    clawback_reserve_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    provider_org_id: str
    funder_org_id: str
    claim_ids: List[str]
    total_amount_cents: int
    status: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FunderReport(TypedDict, total=False):
    id: str
    funder_org_id: str
    period_start: str
    period_end: str
    baseline_snapshot_cents: int
    total_referrals: int
    delivered_count: int
    not_reached_count: int
    unresolved_count: int
    aging_count: int
    total_reimbursed_cents: int
    demographic_breakdown: Dict[str, Any]
    closure_rate_percent: float
    resolution_rate_percent: float
    status: str
    created_at: str
    updated_at: str
    version: int

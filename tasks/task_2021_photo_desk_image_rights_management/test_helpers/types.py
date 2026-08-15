"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    PHOTO_EDITOR = "PhotoEditor"
    PHOTOGRAPHER = "Photographer"
    RIGHTS_MANAGER = "RightsManager"
    ARCHIVIST = "Archivist"
    FINANCE_ADMIN = "FinanceAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class PhotographerType(str, Enum):
    STAFF = "STAFF"
    FREELANCE = "FREELANCE"


class PhotographerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StoryStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Decision(str, Enum):
    COMMISSION = "COMMISSION"
    WIRE_STOCK = "WIRE_STOCK"


class AssignmentStatus(str, Enum):
    COMMISSIONED = "COMMISSIONED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class SourceType(str, Enum):
    ASSIGNMENT = "ASSIGNMENT"
    WIRE = "WIRE"
    STOCK = "STOCK"


class ImageStatus(str, Enum):
    INGESTED = "INGESTED"
    CLEARED = "CLEARED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class RestrictionStatus(str, Enum):
    NONE = "NONE"
    RESTRICTED = "RESTRICTED"


class UsageScope(str, Enum):
    PRINT = "PRINT"
    DIGITAL = "DIGITAL"
    SOCIAL = "SOCIAL"
    SYNDICATION = "SYNDICATION"


class Territory(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"
    GLOBAL = "GLOBAL"


class PricingVariant(str, Enum):
    FIRST_USE = "FIRST_USE"
    REUSE = "REUSE"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReleaseSubjectType(str, Enum):
    MODEL = "MODEL"
    PROPERTY = "PROPERTY"


class ReleaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClaimType(str, Enum):
    UNLICENSED_USE = "UNLICENSED_USE"
    COPYRIGHT_DISPUTE = "COPYRIGHT_DISPUTE"
    MODEL_RELEASE_VIOLATION = "MODEL_RELEASE_VIOLATION"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    UNDER_REVIEW = "UNDER_REVIEW"
    SETTLEMENT_OFFERED = "SETTLEMENT_OFFERED"
    COUNTERED = "COUNTERED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ResolutionOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class PaymentMethod(str, Enum):
    GUARANTEE = "GUARANTEE"
    ROYALTY = "ROYALTY"


class PaymentRunStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity shapes (PRD §2.5 common fields; UsageRun is the ledger exception) ---

class Photographer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    photographer_type: str
    day_rate_cents: int
    per_image_fee_cents: int
    royalty_rate_per_use_cents: int
    rights_reversion_months: int
    status: str
    accrued_earnings_cents: int
    paid_out_cents: int
    created_at: str
    updated_at: str
    version: int


class StoryRequest(TypedDict, total=False):
    id: str
    headline: str
    slug: str
    needed_by: str
    budget_cents: int
    committed_cents: int
    decision: Optional[str]
    commissioned_assignment_id: Optional[str]
    sourced_image_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    story_request_id: str
    photographer_id: str
    brief: str
    shoot_start: str
    shoot_end: str
    min_image_count: int
    max_image_count: int
    day_count: int
    revision_count: int
    accepted_at: Optional[str]
    kill_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Image(TypedDict, total=False):
    id: str
    photographer_id: Optional[str]
    assignment_id: Optional[str]
    source_type: str
    agency_name: Optional[str]
    base_license_fee_cents: int
    caption: Optional[str]
    credit_line: Optional[str]
    keywords: List[str]
    has_identifiable_people: bool
    has_private_property: bool
    embargo_until: Optional[str]
    status: str
    restriction_status: str
    times_used: int
    first_published_at: Optional[str]
    rights_reversion_at: Optional[str]
    rights_reverted: bool
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    image_id: str
    story_request_id: Optional[str]
    usage_scope: str
    territory: str
    valid_from: str
    valid_to: str
    exclusive: bool
    pricing_variant: str
    fee_cents: int
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseRecord(TypedDict, total=False):
    id: str
    image_id: str
    subject_type: str
    subject_name: str
    document_ref: str
    signed_at: str
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageRun(TypedDict, total=False):
    # Immutable ledger entry: id + created_at only, NO updated_at / version (PRD §2.5)
    id: str
    image_id: str
    license_id: str
    channel: str
    story_slug: str
    published_at: str
    royalty_cents: int
    created_at: str


class InfringementClaim(TypedDict, total=False):
    id: str
    image_id: str
    claimant_name: str
    claim_type: str
    description: str
    claimed_amount_cents: int
    proposed_settlement_cents: Optional[int]
    settlement_amount_cents: Optional[int]
    photographer_clawback_cents: Optional[int]
    intaken_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[str]
    resolution_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentRun(TypedDict, total=False):
    id: str
    photographer_id: str
    period_start: str
    period_end: str
    method: str
    guarantee_amount_cents: int
    royalty_amount_cents: int
    clawback_cents: int
    total_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int

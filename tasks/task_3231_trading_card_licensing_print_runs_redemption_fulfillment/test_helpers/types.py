"""Domain types: entity TypedDicts, status enums and role enums.

Every one of the twelve platform resources carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.5), so every TypedDict below is complete
with all four system-managed properties.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly eleven recognised roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LICENSING_MANAGER = "LicensingManager"
    PRODUCT_MANAGER = "ProductManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    SIGNING_COORDINATOR = "SigningCoordinator"
    AUTHENTICATION_OFFICER = "AuthenticationOfficer"
    LICENSOR_APPROVER = "LicensorApprover"
    REDEMPTION_FULFILMENT_ANALYST = "RedemptionFulfilmentAnalyst"
    DISTRIBUTION_MANAGER = "DistributionManager"
    QUALITY_ANALYST = "QualityAnalyst"
    COLLECTOR_SUPPORT_SPECIALIST = "CollectorSupportSpecialist"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ProductLineStatus(str, Enum):
    PLANNING = "PLANNING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PACKED_OUT = "PACKED_OUT"


class CardSetStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PACKED_OUT = "PACKED_OUT"


class PrintRunStatus(str, Enum):
    """The compound print-run state of a card set (PRD §2.12)."""

    UNDECIDED = "UNDECIDED"
    LOCKED = "LOCKED"
    DISCLOSED = "DISCLOSED"
    UNDISCLOSED = "UNDISCLOSED"


class PackConfigurationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SigningSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STOCK_PREPARED = "STOCK_PREPARED"
    STOCK_SHIPPED = "STOCK_SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ArtworkApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PrintRunDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class RedemptionStatus(str, Enum):
    ISSUED = "ISSUED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CollectorNotificationStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SETTLED = "SETTLED"
    RESOLVED = "RESOLVED"


class DistributionAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    UTF = "UTF"
    SHIPPED = "SHIPPED"
    RECALLED = "RECALLED"


class QualityClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CREDITED = "CREDITED"


class CollectorComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Closed input enums
# ---------------------------------------------------------------------------
class ExclusivityScope(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class Tier(str, Enum):
    BASE = "BASE"
    INSERT = "INSERT"
    PREMIUM = "PREMIUM"


class SignerKind(str, Enum):
    PLAYER_ASSOCIATION = "PLAYER_ASSOCIATION"
    INDEPENDENT = "INDEPENDENT"


class ProjectionAuthority(str, Enum):
    SALES_HISTORY = "SALES_HISTORY"
    MARKET_DEMAND = "MARKET_DEMAND"
    BRAND_DIRECTIVE = "BRAND_DIRECTIVE"


class Channel(str, Enum):
    HOBBY = "HOBBY"
    MASS = "MASS"
    DIRECT = "DIRECT"


class ClaimType(str, Enum):
    MISPRINT = "MISPRINT"
    DAMAGE = "DAMAGE"
    MISSING_HIT = "MISSING_HIT"


class ClaimSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class BreachReason(str, Enum):
    UNDISCLOSED_PRINT_RUN = "UNDISCLOSED_PRINT_RUN"
    NO_REPLACEMENT_POLICY = "NO_REPLACEMENT_POLICY"


class ArtworkDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all twelve carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class License(TypedDict):
    id: str
    grantor_name: str
    exclusivity_scope: str
    term_starts_on: str
    term_ends_on: str
    approval_window_days: int
    rights_version: int
    status: str
    set_count: int
    approved_set_count: int
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    license_id: str
    line_name: str
    line_kind: str
    packs_per_box: int
    cards_per_pack: int
    boxes_per_case: int
    cases_printed: int
    run_planned_on: str
    sets_per_case: int
    allocated_cards: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CardSet(TypedDict):
    id: str
    product_line_id: str
    set_name: str
    set_tier: str
    rights_pinned_version: int
    print_run_quantity: int
    announced: bool
    serial_numbered: bool
    print_run_status: str
    autograph_planned_count: int
    autograph_secured_count: int
    autograph_redemptions_outstanding: int
    quality_claim_count: int
    settled_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class PackConfiguration(TypedDict):
    id: str
    card_set_id: str
    config_serial: int
    odd_value: int
    base_packs: int
    insert_packs: int
    premium_packs: int
    total_cards: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SigningSessionAllocationLine(TypedDict):
    card_set_id: str
    player_id: str
    quantity_delivered: int


class SigningSession(TypedDict):
    id: str
    signer_name: str
    signer_kind: str
    license_id: str
    scheduled_on: str
    ship_date: str
    total_allocated_count: int
    allocation_lines: List[SigningSessionAllocationLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class ArtworkApproval(TypedDict):
    id: str
    card_set_id: str
    artwork_code: str
    approver_id: str
    submitted_on: str
    decided_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintRunDecision(TypedDict):
    id: str
    card_set_id: str
    authority: str
    proposed_against_line_version: int
    demand_multiplier: float
    declared_quantity: int
    announced: bool
    final_quantity: int
    proposed_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    card_set_id: str
    redemption_code: str
    signer_name: str
    estimated_value_cents: int
    opened_on: str
    deadline_days: int
    status: str
    collector_notification_count: int
    created_at: str
    updated_at: str
    version: int


class CollectorNotification(TypedDict):
    id: str
    redemption_id: str
    notice_code: str
    notice_text: str
    opened_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionAllocation(TypedDict):
    id: str
    product_line_id: str
    channel: str
    quantity_allocated: int
    shipped_quantity: int
    effective_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict):
    id: str
    card_set_id: str
    claim_type: str
    severity: str
    affected_quantity: int
    filed_on: str
    status: str
    claim_weight: int
    created_at: str
    updated_at: str
    version: int


class CollectorComplaint(TypedDict):
    id: str
    card_set_id: str
    complaint_label: str
    breach_reason: str
    claim_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int
"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3).

All twelve resources carry the common system-managed fields of PRD §2.5
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    """The seven declared roles of PRD §2.1. All identities are opaque."""
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_LEAD = "ProductLead"
    SOURCING_MANAGER = "SourcingManager"
    CLAIMS_SCIENTIST = "ClaimsScientist"
    MEDIA_BUYER = "MediaBuyer"
    RETAIL_EXEC = "RetailExec"
    LEGAL_COUNSEL = "LegalCounsel"


class SeasonPosture(str, Enum):
    OPEN = "SEASON_OPEN"
    GUARDED = "SEASON_GUARDED"
    FROZEN = "SEASON_FROZEN"
    CLOSED = "SEASON_CLOSED"


class ExposureLevel(str, Enum):
    CLEAR = "CLEAR"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class ConceptStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    RESEARCHING = "RESEARCHING"
    CONCEPT_LOCKED = "CONCEPT_LOCKED"
    PROTOTYPE_CYCLING = "PROTOTYPE_CYCLING"
    ENGINEERING_LOCKED = "ENGINEERING_LOCKED"
    LAUNCH_KILLED = "LAUNCH_KILLED"


class KilledReason(str, Enum):
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    SCORED = "SCORED"
    EXPIRED = "EXPIRED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VariantLifecycle(str, Enum):
    DRAFT = "DRAFT"
    TOOLED = "TOOLED"
    DR_TESTING = "DR_TESTING"
    RETAIL_LIVE = "RETAIL_LIVE"
    REFRESH_CANDIDATE = "REFRESH_CANDIDATE"
    RETIRED = "RETIRED"


class ClaimClearance(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    SUBSTANTIATED = "SUBSTANTIATED"
    CHALLENGED = "CHALLENGED"


class Channel(str, Enum):
    AMAZON = "AMAZON"
    BIG_BOX = "BIG_BOX"
    CLUB = "CLUB"
    DTC = "DTC"
    SPECIALTY = "SPECIALTY"


class StudyStatus(str, Enum):
    RUNNING = "RUNNING"
    RESULTS_RECORDED = "RESULTS_RECORDED"
    SUBSTANTIATED = "SUBSTANTIATED"
    CHALLENGED = "CHALLENGED"


class MediaStatus(str, Enum):
    EDITING = "EDITING"
    AIRING = "AIRING"
    DECIDED_SCALE = "DECIDED_SCALE"
    KILLED = "KILLED"


class MediaDecision(str, Enum):
    SCALE = "SCALE"
    KILL = "KILL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    SHORTFALL_PENALIZED = "SHORTFALL_PENALIZED"


class ReplenishmentStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class CaseStatus(str, Enum):
    FILED = "FILED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    JUDGED_ADVERSE = "JUDGED_ADVERSE"
    JUDGED_FAVORABLE = "JUDGED_FAVORABLE"


class Severity(str, Enum):
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class JudgmentOutcome(str, Enum):
    ADVERSE = "ADVERSE"
    FAVORABLE = "FAVORABLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries the §2.5 common fields
# ---------------------------------------------------------------------------

class LaunchSeason(TypedDict, total=False):
    id: str
    season_code: str
    posture: str
    review_index: int
    frozen_at_review_index: Optional[int]
    guarded_since_review_index: Optional[int]
    last_review_at: Optional[str]
    penalty_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    crowding_base: int
    exposure_index: int
    exposure_level: str
    active_reserve_cents: int
    created_at: str
    updated_at: str
    version: int


class ResearchInsight(TypedDict):
    points: int
    observed_at: str


class ProductConcept(TypedDict, total=False):
    id: str
    category_id: str
    title: str
    status: str
    research_insights: List[ResearchInsight]
    research_momentum: float
    rounds_used: int
    killed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrototypeRound(TypedDict, total=False):
    id: str
    concept_id: str
    round_number: int
    status: str
    opened_at: str
    score: Optional[int]
    feedback: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FactoryPartner(TypedDict, total=False):
    id: str
    name: str
    capacity_units_total: int
    allocated_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ModelVariant(TypedDict, total=False):
    id: str
    concept_id: str
    factory_partner_id: Optional[str]
    model_number: str
    channel: str
    lifecycle: str
    claim_clearance: str
    tooled_at: Optional[str]
    retail_live_at: Optional[str]
    refresh_candidate_at: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimStudy(TypedDict, total=False):
    id: str
    variant_id: str
    claim_text: str
    conducted_by_user_id: str
    status: str
    our_metric: Optional[float]
    baseline_metric: Optional[float]
    sample_size: Optional[int]
    margin: Optional[float]
    substantiated_by_user_id: Optional[str]
    challenge_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    revenue_cents: int
    cancels_cents: int
    returns_cents: int


class MediaTest(TypedDict, total=False):
    id: str
    variant_id: str
    title: str
    media_spend_cents: int
    status: str
    projected_gross_cents: Optional[int]
    provisional_mer: Optional[float]
    order_lines: Optional[List[OrderLine]]
    settled_mer: Optional[float]
    aired_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailAgreement(TypedDict, total=False):
    id: str
    category_id: str
    retailer_name: str
    exclusive: bool
    window_start: str
    window_end: str
    min_launch_units: int
    status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaunchCommitment(TypedDict, total=False):
    id: str
    agreement_id: str
    variant_id: str
    committed_units: int
    need_by_date: str
    status: str
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    variant_id: str
    weekly_velocity: int
    on_hand_units: int
    in_transit_units: int
    case_pack_units: int
    quantity_units: int
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatentCase(TypedDict, total=False):
    id: str
    category_id: str
    case_number: str
    claim_cents: int
    severity: str
    filed_by_user_id: str
    status: str
    provisional_reserve_cents: int
    final_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "SeasonPosture",
    "ExposureLevel",
    "ConceptStatus",
    "KilledReason",
    "RoundStatus",
    "PartnerStatus",
    "VariantLifecycle",
    "ClaimClearance",
    "Channel",
    "StudyStatus",
    "MediaStatus",
    "MediaDecision",
    "AgreementStatus",
    "CommitmentStatus",
    "ReplenishmentStatus",
    "CaseStatus",
    "Severity",
    "JudgmentOutcome",
    "LaunchSeason",
    "Category",
    "ResearchInsight",
    "ProductConcept",
    "PrototypeRound",
    "FactoryPartner",
    "ModelVariant",
    "ClaimStudy",
    "OrderLine",
    "MediaTest",
    "RetailAgreement",
    "LaunchCommitment",
    "ReplenishmentOrder",
    "PatentCase",
]

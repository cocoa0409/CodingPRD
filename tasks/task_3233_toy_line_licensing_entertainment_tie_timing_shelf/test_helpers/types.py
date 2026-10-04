"""Domain types for the Toy Licensing API.

Entity TypedDicts, status enums, role enum. Every persisted resource carries
``id``, ``created_at``, ``updated_at`` and an integer ``version`` (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BRAND_MANAGER = "BrandManager"
    STUDIO_REP = "StudioRep"
    RETAILER_OPS = "RetailerOps"
    SAFETY_ENGINEER = "SafetyEngineer"


class StudioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ConfidentialityTier(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class PropertyCategory(str, Enum):
    FILM = "FILM"
    SERIES = "SERIES"


class PropertyLifecycle(str, Enum):
    CONFIDENTIAL = "CONFIDENTIAL"
    REVEALED = "REVEALED"
    RELEASED = "RELEASED"


class AgreementStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"


class BrandKind(str, Enum):
    LICENSED = "LICENSED"
    EVERGREEN = "EVERGREEN"


class ToyLineStatus(str, Enum):
    CONCEPT = "CONCEPT"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    TOOLED = "TOOLED"
    COMMITTED = "COMMITTED"
    ON_SHELF = "ON_SHELF"
    CLOSEOUT = "CLOSEOUT"
    RETIRED = "RETIRED"


class SafetyStatus(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    TESTING = "TESTING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TestType(str, Enum):
    MECHANICAL = "MECHANICAL"
    FLAMMABILITY = "FLAMMABILITY"
    CHEMICAL = "CHEMICAL"


class SafetyTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"


class ToolingOrderStatus(str, Enum):
    APPROVED = "APPROVED"
    SCRAPPED = "SCRAPPED"
    COMPLETE = "COMPLETE"


class LineReviewStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CONFIRMED = "CONFIRMED"


class LineReviewLifecycle(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    AT_RISK = "AT_RISK"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    SOLD = "SOLD"


class PenaltyStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    WAIVED = "WAIVED"


PACKAGING_CLAIMS = ["CHOKING_HAZARD_FREE", "FLAME_RESISTANT", "BPA_FREE"]


class Studio(TypedDict, total=False):
    id: str
    name: str
    confidentiality_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    studio_id: str
    title: str
    category: str
    reveal_date: str
    release_date: str
    shift_count: int
    lifecycle: str
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    property_id: str
    territory: str
    royalty_rate_pct: float
    advance_guarantee_cents: int
    annual_minimum_guarantee_cents: int
    start_date: str
    end_date: str
    approval_rights_required: bool
    status: str
    pending_royalty_rate_pct: Optional[float]
    pending_advance_guarantee_cents: Optional[int]
    pending_end_date: Optional[str]
    royalties_earned_cents: int
    recouped_cents: int
    guarantee_topups_cents: int
    quarters_closed: int
    created_at: str
    updated_at: str
    version: int


class ToyLine(TypedDict, total=False):
    id: str
    name: str
    brand_kind: str
    property_id: Optional[str]
    license_agreement_id: Optional[str]
    target_street_date: str
    status: str
    closeout_markdown_pct: Optional[float]
    closeout_recovery_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict, total=False):
    id: str
    toy_line_id: str
    name: str
    age_grade_months: int
    tested_age_grade_months: Optional[int]
    packaging_claims: List[str]
    claims_validated: bool
    moq_units: int
    unit_cost_cents: int
    tooling_cost_cents: int
    safety_status: str
    created_at: str
    updated_at: str
    version: int


class Factory(TypedDict, total=False):
    id: str
    name: str
    capacity_units_per_month: int
    tooling_lead_weeks: int
    created_at: str
    updated_at: str
    version: int


class ToolingOrder(TypedDict, total=False):
    id: str
    toy_line_id: str
    sku_id: str
    factory_id: str
    production_month: str
    units: int
    allocated_units: int
    tooling_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict, total=False):
    id: str
    name: str
    region: str
    credit_balance_cents: int
    violation_count: int
    created_at: str
    updated_at: str
    version: int


class LineReview(TypedDict, total=False):
    id: str
    retailer_id: str
    window_start: str
    window_end: str
    commitment_deadline: str
    shelf_slots_total: int
    shelf_slots_used: int
    status: str
    lifecycle: str
    created_at: str
    updated_at: str
    version: int


class AssortmentCommitment(TypedDict, total=False):
    id: str
    line_review_id: str
    sku_id: str
    committed_units: int
    unit_price_cents: int
    shelf_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    commitment_id: str
    planned_ship_date: str
    units: int
    street_date: str
    sold_units: int
    sold_at: Optional[str]
    status: str
    penalty_cents: int
    penalty_status: str
    created_at: str
    updated_at: str
    version: int


class SafetyTest(TypedDict, total=False):
    id: str
    sku_id: str
    test_type: str
    lab_name: str
    claimed_age_grade_months: int
    result_age_grade_months: int
    validated_claims: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int

"""Domain types for the Playground Equipment Manufacturing & Installation API.

Status enums, role names and entity TypedDicts, all named exactly as the PRD
names them.  Entities that carry the four common properties (id, created_at,
updated_at, version) list all four; the single append-only evidence entity
(InstallationInspection) carries only id and created_at.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1) — spelled exactly as the PRD requires.
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    MANUFACTURER_ADMIN = "ManufacturerAdmin"
    DESIGN_CONSULTANT = "DesignConsultant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT_REPRESENTATIVE = "ClientRepresentative"
    INSTALLER_OPERATOR = "InstallerOperator"
    SAFETY_AUDITOR = "SafetyAuditor"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StandardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ModelCertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class ModelLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEGACY = "LEGACY"
    DISCONTINUED = "DISCONTINUED"


class ComponentCategory(str, Enum):
    POST = "POST"
    DECK = "DECK"
    PLASTIC_SLIDE = "PLASTIC_SLIDE"
    METAL_CLIMBER = "METAL_CLIMBER"
    HARDWARE_KIT = "HARDWARE_KIT"


class AgeGroup(str, Enum):
    TODDLER_6_23M = "TODDLER_6_23M"
    PRESCHOOL_2_5 = "PRESCHOOL_2_5"
    SCHOOL_AGE_5_12 = "SCHOOL_AGE_5_12"


class SoilType(str, Enum):
    SANDY_LOAM = "SANDY_LOAM"
    GRAVEL = "GRAVEL"
    CLAY = "CLAY"


class SurfacingMaterial(str, Enum):
    ENGINEERED_WOOD_FIBER = "ENGINEERED_WOOD_FIBER"
    POURED_RUBBER = "POURED_RUBBER"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSULTATION = "CONSULTATION"
    RENDERED = "RENDERED"
    COMMUNITY_REVIEW = "COMMUNITY_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    CERTIFIED = "CERTIFIED"
    ORDERED = "ORDERED"
    INSTALLED = "INSTALLED"
    AUDITED = "AUDITED"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    COMPLIANT = "COMPLIANT"
    RETROFIT_REQUIRED = "RETROFIT_REQUIRED"
    NON_COMPLIANT = "NON_COMPLIANT"


class PlayAreaStatus(str, Enum):
    PLANNED = "PLANNED"
    ZONED = "ZONED"
    LOCKED = "LOCKED"


class PlacementStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    NEEDS_RECERTIFICATION = "NEEDS_RECERTIFICATION"


class RenderingStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class QuoteVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FIRM = "FIRM"


class QuoteStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COLLECTED = "COLLECTED"
    REFUNDED = "REFUNDED"


class ProductionStatus(str, Enum):
    CREATED = "CREATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PrepStatus(str, Enum):
    """Shared by kitting_status and bagging_status."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class CertificationLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    CERTIFIED = "CERTIFIED"
    MASTER = "MASTER"


class InstallerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class JobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    REWORK_IN_PROGRESS = "REWORK_IN_PROGRESS"
    AUDIT_PENDING = "AUDIT_PENDING"
    AUDIT_PASSED = "AUDIT_PASSED"
    AUDIT_FAILED = "AUDIT_FAILED"
    CANCELLED = "CANCELLED"


class InspectionKind(str, Enum):
    INSTALL_INSPECTION = "INSTALL_INSPECTION"
    POST_INSTALL_AUDIT = "POST_INSTALL_AUDIT"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CoverageVariant(str, Enum):
    PRORATED = "PRORATED"
    STEP = "STEP"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReworkAction(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"


class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class PlaygroundStandard(TypedDict):
    id: str
    code: str
    edition_year: int
    effective_from: str
    min_use_zone_clearance_cm: int
    max_fall_height_cm_toddler: int
    max_fall_height_cm_preschool: int
    max_fall_height_cm_school_age: int
    requires_accessible_route: bool
    status: str
    superseded_by_standard_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentModel(TypedDict):
    id: str
    sku: str
    category: str
    age_group: str
    deck_height_cm: int
    use_zone_footprint_cm: int
    color_options: List[str]
    unit_price_cents: int
    hardware_bag_count: int
    warranty_years: int
    parts_support_until_year: int
    accessible_transfer_ready: bool
    supersedes_model_id: Optional[str]
    certification_status: str
    certified_against_standard_id: Optional[str]
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class DesignProject(TypedDict):
    id: str
    client_name: str
    consultant_user_id: str
    site_length_cm: int
    site_width_cm: int
    site_soil_type: str
    budget_cents: int
    fundraising_deadline: str
    required_age_groups: List[str]
    accessible_route_required: bool
    design_status: str
    compliance_status: str
    revision_rounds: int
    installed_on: Optional[str]
    funds_collected_cents: int
    alloc_permit_freight_cents: int
    alloc_surfacing_cents: int
    alloc_structure_cents: int
    alloc_contingency_cents: int
    created_at: str
    updated_at: str
    version: int


class PlayArea(TypedDict):
    id: str
    project_id: str
    age_group: str
    axis_origin_cm: int
    axis_length_cm: int
    surfacing_material: str
    surfacing_depth_cm: int
    critical_fall_height_cm: int
    required_surfacing_depth_cm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComponentPlacement(TypedDict):
    id: str
    play_area_id: str
    component_model_id: str
    attached_to_placement_id: Optional[str]
    color_choice: str
    x_start_cm: int
    quantity: int
    use_zone_start_cm: int
    use_zone_end_cm: int
    status: str
    retrofit_model_id: Optional[str]
    retrofit_quantity: int
    retrofit_unit_price_cents: int
    retrofit_handling_cents: int
    retrofit_total_cents: int
    legacy_surcharge_applied: bool
    created_at: str
    updated_at: str
    version: int


class DesignRendering(TypedDict):
    id: str
    project_id: str
    pinned_standard_id: str
    round_number: int
    use_zone_snapshot: Dict[str, Any]
    yes_votes: int
    no_votes: int
    community_approval_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    rendering_id: str
    variant: str
    valid_until: str
    subtotal_cents: int
    freight_cents: int
    discount_cents: int
    total_cents: int
    priced_unit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundraisingPledge(TypedDict):
    id: str
    project_id: str
    amount_cents: int
    pledged_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturingOrder(TypedDict):
    id: str
    quote_id: str
    production_status: str
    kitting_status: str
    bagging_status: str
    kit_line_count: int
    hardware_bag_total: int
    instruction_package_revision: int
    created_at: str
    updated_at: str
    version: int


class CertifiedInstaller(TypedDict):
    id: str
    company_name: str
    certification_level: str
    certified_categories: List[str]
    crew_capacity_per_day: int
    certification_expires_on: str
    region_code: str
    status: str
    open_audit_failures: int
    committed_crew_days: int
    created_at: str
    updated_at: str
    version: int


class InstallationJob(TypedDict):
    id: str
    order_id: str
    installer_id: str
    scheduled_start_date: str
    scheduled_end_date: str
    crew_size: int
    status: str
    rework_cycles: int
    last_failed_inspection_kind: Optional[str]
    install_inspector_user_id: Optional[str]
    booked_crew_days: int
    created_at: str
    updated_at: str
    version: int


class InstallationInspection(TypedDict):
    """Immutable append-only evidence: only id and created_at, no updated_at
    and no version (PRD §2.4)."""

    id: str
    job_id: str
    kind: str
    result: str
    performed_by_user_id: str
    deficiency_count: int
    fall_height_measured_cm: int
    surfacing_depth_measured_cm: int
    sequence_number: int
    created_at: str


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    placement_id: str
    component_model_id: str
    claim_category: str
    quantity: int
    failure_date: str
    elapsed_years: int
    coverage_variant: str
    covered_pct: int
    reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int

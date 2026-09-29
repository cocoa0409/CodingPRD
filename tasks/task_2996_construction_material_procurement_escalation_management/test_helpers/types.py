"""Domain types for the Construction Material Procurement & Escalation Management API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    BUYOUT_MANAGER = "BuyoutManager"
    SUPPLIER_REP = "SupplierRep"
    PROJECT_EXECUTIVE = "ProjectExecutive"
    DESIGN_ENGINEER = "DesignEngineer"
    OWNER_REP = "OwnerRep"


# ─── Enumerations (PRD §3) ─────────────────────────────────────────────────

class CommodityIndexCode(str, Enum):
    PPI_STEEL_MILL = "PPI_STEEL_MILL"
    PPI_COPPER_WIRE = "PPI_COPPER_WIRE"
    PPI_LUMBER = "PPI_LUMBER"
    PPI_CEMENT = "PPI_CEMENT"
    PPI_SWITCHGEAR = "PPI_SWITCHGEAR"


class PackageStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    SOURCING = "SOURCING"
    BOUGHT_OUT = "BOUGHT_OUT"
    SOURCING_STALLED = "SOURCING_STALLED"
    CLOSED = "CLOSED"


class RffRiskBand(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ExposureBand(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class QuoteStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CONVERTED = "CONVERTED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    LAPSED = "LAPSED"


class CommitmentStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class DeliveryPosture(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED_FOR_FAB = "RELEASED_FOR_FAB"
    FABRICATING = "FABRICATING"
    STORED_OFFSITE = "STORED_OFFSITE"
    STORAGE_NONCOMPLIANT = "STORAGE_NONCOMPLIANT"
    DELIVERED = "DELIVERED"


class EscalationVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ArrangementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class DocumentationStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class DocType(str, Enum):
    BAILMENT_AGREEMENT = "BAILMENT_AGREEMENT"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"
    LIEN_WAIVER = "LIEN_WAIVER"
    INVENTORY_TAG_PHOTO = "INVENTORY_TAG_PHOTO"


class SubstitutionDriver(str, Enum):
    VALUE_ENGINEERING = "VALUE_ENGINEERING"
    DISRUPTION_CONTINGENCY = "DISRUPTION_CONTINGENCY"
    AVAILABILITY = "AVAILABILITY"


class SubstitutionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RESCINDED = "RESCINDED"


class SubstitutionDisposition(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class ChangeOrderStatus(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    OWNER_APPROVED = "OWNER_APPROVED"
    OWNER_REJECTED = "OWNER_REJECTED"


class ChangeOrderDisposition(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisruptionEventType(str, Enum):
    TARIFF_IMPOSED = "TARIFF_IMPOSED"
    PLANT_SHUTDOWN = "PLANT_SHUTDOWN"
    PORT_CONGESTION = "PORT_CONGESTION"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class DisruptionStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"


# ─── Entity shapes (PRD §2.4, §3) ──────────────────────────────────────────
# Resources carrying id + created_at + updated_at + version.

class Project(TypedDict):
    id: str
    name: str
    contract_number: str
    owner_name: str
    schedule_data_date: str
    escalation_contingency_budget: float
    estimated_total_cost: float
    committed_total_cost: float
    buyout_variance: float
    bought_out_variance: float
    escalation_contingency_committed: float
    escalation_contingency_remaining: float
    change_order_recovered_amount: float
    created_at: str
    updated_at: str
    version: int


class MaterialPackage(TypedDict):
    id: str
    project_id: str
    scope_code: str
    description: str
    commodity_index_code: str
    estimated_cost: float
    baseline_estimated_cost: float
    required_onsite_date: str
    fabrication_duration_days: int
    baseline_fabrication_duration_days: int
    delivery_transit_days: int
    submittal_review_days: int
    lead_time_days: int
    release_for_fabrication_date: str
    is_long_lead: bool
    float_days: int
    rff_risk_band: str
    open_quote_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    legal_name: str
    country_of_origin: str
    is_domestic: bool
    declared_tariff_rate_pct: float
    open_disruption_count: int
    exposure_score_snapshot: float
    exposure_band_snapshot: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    material_package_id: str
    supplier_id: str
    supersedes_quote_id: Optional[str]
    base_price: float
    received_at: str
    price_hold_days: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EscalationAgreement(TypedDict):
    id: str
    quote_id: str
    index_code: str
    baseline_index_period: str
    baseline_index_value: Optional[float]
    deadband_pct: float
    cap_pct: float
    contractor_share_pct: float
    price_hold_through: str
    proposed_terms_note: Optional[str]
    counter_note: Optional[str]
    round_number: int
    executed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only published configuration: id + created_at only, no updated_at, no version.
class IndexReading(TypedDict):
    id: str
    index_code: str
    period: str
    value: float
    published_at: str
    created_at: str


class PurchaseCommitment(TypedDict):
    id: str
    quote_id: str
    material_package_id: str
    escalation_agreement_id: Optional[str]
    po_number: str
    committed_base_cost: float
    is_early_buyout: bool
    requires_storage_arrangement: bool
    commitment_status: str
    delivery_posture: str
    released_for_fab_at: Optional[str]
    delivered_at: Optional[str]
    escalation_variant: str
    escalation_accrued: float
    escalation_index_period: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OffsiteStorageArrangement(TypedDict):
    id: str
    purchase_commitment_id: str
    warehouse_name: str
    warehouse_address: str
    stored_value: float
    monthly_storage_rate_pct: float
    stored_from: str
    planned_release_date: str
    documentation_status: str
    verified_doc_type_count: int
    carrying_cost_accrued: float
    carrying_cost_frozen_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageDocument(TypedDict):
    id: str
    storage_arrangement_id: str
    doc_type: str
    reference_number: str
    effective_date: str
    expires_at: str
    coverage_amount: float
    verified: bool
    revoked: bool
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    material_package_id: str
    proposed_supplier_id: str
    disruption_event_id: Optional[str]
    driver: str
    proposed_product: str
    cost_delta: float
    schedule_delta_days: int
    submitted_by_user_id: str
    engineer_conditions: Optional[str]
    revision_round: int
    applied_cost_delta: float
    applied_schedule_delta_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrderRequest(TypedDict):
    id: str
    purchase_commitment_id: str
    claimed_amount: float
    narrative: str
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    gross_documented_amount: float
    admin_fee_pct: float
    admin_fee_amount: float
    substantiated_amount: float
    owner_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisruptionEvent(TypedDict):
    id: str
    supplier_id: str
    event_type: str
    tariff_rate_pct: float
    effective_date: str
    description: str
    status: str
    mitigated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    current_utc: str
    expired_quote_ids: List[str]
    lapsed_agreement_ids: List[str]
    voided_commitment_ids: List[str]
    stalled_package_ids: List[str]

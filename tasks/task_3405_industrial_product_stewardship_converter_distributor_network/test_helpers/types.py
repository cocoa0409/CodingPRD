"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_MANAGER = "ProductManager"
    REGULATORY_MANAGER = "RegulatoryManager"
    CHANNEL_MANAGER = "ChannelManager"
    QUALITY_AUDITOR = "QualityAuditor"
    TECHNICAL_ENGINEER = "TechnicalEngineer"
    FINANCE_CONTROLLER = "FinanceController"
    CONVERTER = "Converter"
    DISTRIBUTOR = "Distributor"


class RestrictionClass(str, Enum):
    STANDARD = "STANDARD"
    REPORTABLE = "REPORTABLE"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"


class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DisclosureLevel(str, Enum):
    EXEMPT = "EXEMPT"
    DECLARATION = "DECLARATION"
    FULL_DISCLOSURE = "FULL_DISCLOSURE"


class ClearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ConverterStatus(str, Enum):
    APPLIED = "APPLIED"
    AUDIT_RECORDED = "AUDIT_RECORDED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class Capability(str, Enum):
    SLITTING = "SLITTING"
    DIE_CUTTING = "DIE_CUTTING"
    LAMINATION = "LAMINATION"


class SubstrateClass(str, Enum):
    METAL = "METAL"
    POLYMER = "POLYMER"
    GLASS = "GLASS"
    COMPOSITE = "COMPOSITE"


class ApplicationCaseStatus(str, Enum):
    OPEN = "OPEN"
    LAB_BOOKED = "LAB_BOOKED"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"


class TestStandard(str, Enum):
    NOMINAL = "NOMINAL"
    APPLICATION_DERATED = "APPLICATION_DERATED"


class AgreementTier(str, Enum):
    CONVERTER_AUTHORIZED = "CONVERTER_AUTHORIZED"
    DISTRIBUTOR_PREFERRED = "DISTRIBUTOR_PREFERRED"
    STANDARD = "STANDARD"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class PartnerType(str, Enum):
    CONVERTER = "CONVERTER"
    DISTRIBUTOR = "DISTRIBUTOR"


class RebateProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RebateAccrualStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    CLAIMED = "CLAIMED"
    PAID = "PAID"


class PhaseOutStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    REFORMULATING = "REFORMULATING"
    QUALIFYING = "QUALIFYING"
    ENFORCED = "ENFORCED"


class CounterfeitReportStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED_COUNTERFEIT = "CONFIRMED_COUNTERFEIT"
    CLEARED_GENUINE = "CLEARED_GENUINE"
    INCONCLUSIVE = "INCONCLUSIVE"


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    declaration_threshold_ppm: int
    full_disclosure_threshold_ppm: int
    review_sla_days: int
    created_at: str
    updated_at: str
    version: int


class Substance(TypedDict, total=False):
    id: str
    cas_number: str
    name: str
    restriction_class: str
    created_at: str
    updated_at: str
    version: int


class Formulation(TypedDict, total=False):
    id: str
    product_code: str
    name: str
    base_polymer_family: str
    status: str
    revision_number: int
    successor_of_id: Optional[str]
    active_clearance_count: int
    discontinued_at: Optional[str]
    ltb_deadline: Optional[str]
    last_ship_date: Optional[str]
    ltb_pool_quantity: Optional[int]
    ltb_pool_remaining: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Immutable join row (PRD §2.5): carries id + created_at only; no updated_at/version.
class FormulationComponent(TypedDict, total=False):
    id: str
    formulation_id: str
    substance_id: str
    concentration_ppm: int
    created_at: str


class JurisdictionClearance(TypedDict, total=False):
    id: str
    formulation_id: str
    jurisdiction_id: str
    disclosure_package_level: str
    required_disclosure_level: str
    status: str
    submission_count: int
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Converter(TypedDict, total=False):
    id: str
    name: str
    home_territory_code: str
    status: str
    quality_audit_score: Optional[int]
    audit_standard: Optional[str]
    audited_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict, total=False):
    id: str
    name: str
    home_territory_code: str
    created_at: str
    updated_at: str
    version: int


class ConverterAuthorization(TypedDict, total=False):
    id: str
    converter_id: str
    capability: str
    territory_code: str
    valid_from: str
    valid_to: str
    created_at: str
    updated_at: str
    version: int


class ApplicationCase(TypedDict, total=False):
    id: str
    formulation_id: str
    customer_ref: str
    substrate_class: str
    application_description: Optional[str]
    status: str
    failure_count: int
    bench_id: Optional[str]
    bench_date: Optional[str]
    bench_hours: Optional[float]
    peel_strength_n_per_25mm: Optional[float]
    test_temp_c: Optional[int]
    test_standard: Optional[str]
    pass_threshold_applied: Optional[float]
    created_at: str
    updated_at: str
    version: int


class VolumeBreakpoint(TypedDict):
    min_qty: int
    extra_discount_pct: float


class PriceAgreement(TypedDict, total=False):
    id: str
    formulation_id: str
    jurisdiction_id: str
    converter_id: Optional[str]
    distributor_id: Optional[str]
    tier: str
    base_price_cents: int
    volume_breakpoints: List[VolumeBreakpoint]
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    agreement_id: str
    converter_id: Optional[str]
    distributor_id: Optional[str]
    formulation_id: str
    ship_to_jurisdiction_id: str
    quantity: int
    requested_ship_date: str
    intended_capability: Optional[str]
    lot_code: Optional[str]
    unit_price_cents: int
    line_total_cents: int
    is_ltb_order: bool
    fulfillment_status: str
    compliance_status: str
    shipped_at: Optional[str]
    flagged_by_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebateTier(TypedDict):
    threshold_qty: int
    rate_pct: float


class RebateProgram(TypedDict, total=False):
    id: str
    formulation_id: str
    partner_type: str
    converter_id: Optional[str]
    distributor_id: Optional[str]
    period_start: str
    period_end: str
    rebate_tiers: List[RebateTier]
    budget_cap_cents: int
    status: str
    created_by: str
    paid_out_cents: int
    created_at: str
    updated_at: str
    version: int


class RebateAccrual(TypedDict, total=False):
    id: str
    program_id: str
    converter_id: Optional[str]
    distributor_id: Optional[str]
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    excluded_order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PhaseOutProgram(TypedDict, total=False):
    id: str
    substance_id: str
    jurisdiction_codes: List[str]
    trigger_concentration_ppm: int
    status: str
    successor_formulation_id: Optional[str]
    qualified_customers: List[str]
    qualified_customer_count: int
    created_at: str
    updated_at: str
    version: int


class CounterfeitReport(TypedDict, total=False):
    id: str
    formulation_id: str
    lot_code: str
    channel_description: str
    implicated_converter_id: Optional[str]
    reporter_role: str
    status: str
    investigator_note: Optional[str]
    created_at: str
    updated_at: str
    version: int

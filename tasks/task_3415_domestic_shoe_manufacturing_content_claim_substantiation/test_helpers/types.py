"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the standard common fields
(id, created_at, updated_at, version) per PRD section on common
resource properties.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SOURCING_MANAGER = "SourcingManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    FACTORY_MANAGER = "FactoryManager"
    CUSTOM_PROGRAM_CUSTOMER = "CustomProgramCustomer"


class FactoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LocationType(str, Enum):
    DOMESTIC = "DOMESTIC"
    OVERSEAS = "OVERSEAS"


class ModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductionPolicy(str, Enum):
    DOMESTIC_ONLY = "DOMESTIC_ONLY"
    IMPORT_ONLY = "IMPORT_ONLY"
    DUAL_SOURCE = "DUAL_SOURCE"


class ComponentType(str, Enum):
    UPPER = "UPPER"
    MIDSOLE = "MIDSOLE"
    OUTSOLE = "OUTSOLE"
    INSOLE = "INSOLE"
    LACES = "LACES"
    EYELETS = "EYELETS"
    ADHESIVE = "ADHESIVE"
    THREAD = "THREAD"
    OTHER = "OTHER"


class SourcingRequirement(str, Enum):
    DOMESTIC_REQUIRED = "DOMESTIC_REQUIRED"
    DOMESTIC_PREFERRED = "DOMESTIC_PREFERRED"
    IMPORT_ALLOWED = "IMPORT_ALLOWED"


class RunType(str, Enum):
    STOCK = "STOCK"
    CUSTOM_BATCH = "CUSTOM_BATCH"
    GOVERNMENT = "GOVERNMENT"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    MATERIAL_RESERVED = "MATERIAL_RESERVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QUALITY_HOLD = "QUALITY_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReportVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class ReportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    MADE_IN_USA = "MADE_IN_USA"
    MADE_IN_USA_OF_IMPORTED_MATERIALS = "MADE_IN_USA_OF_IMPORTED_MATERIALS"
    ASSEMBLED_IN_USA = "ASSEMBLED_IN_USA"
    IMPORTED = "IMPORTED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBSTANTIATED = "SUBSTANTIATED"
    PUBLISHED = "PUBLISHED"
    CHALLENGED = "CHALLENGED"
    REVOKED = "REVOKED"


class DocType(str, Enum):
    SUPPLIER_ORIGIN_CERT = "SUPPLIER_ORIGIN_CERT"
    ASSEMBLY_LABOR_RECORD = "ASSEMBLY_LABOR_RECORD"
    COST_BREAKDOWN = "COST_BREAKDOWN"
    CUSTOMS_ENTRY = "CUSTOMS_ENTRY"


class DocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Operation(str, Enum):
    STITCHING = "STITCHING"
    LASTING = "LASTING"
    ASSEMBLY = "ASSEMBLY"


class CertStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    REMEDIATION = "REMEDIATION"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class ShiftDirection(str, Enum):
    TO_DOMESTIC = "TO_DOMESTIC"
    TO_IMPORT = "TO_IMPORT"


class ContractStatus(str, Enum):
    AWARDED = "AWARDED"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    COMPLIANCE_AUDIT = "COMPLIANCE_AUDIT"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class BomLine(TypedDict):
    component_id: str
    quantity_per_pair: float
    sourcing_requirement: str
    planned_unit_cost_cents: int
    planned_is_domestic: bool


class ConsumedLot(TypedDict):
    lot_id: str
    component_id: str
    units_consumed: int
    unit_cost_cents: int
    is_domestic: bool


class Certification(TypedDict):
    operation: str
    level: int
    cert_status: str


class Factory(TypedDict):
    id: str
    factory_name: str
    location_type: str
    government_cleared: bool
    weekly_capacity_units: int
    line_count: int
    labor_rate_cents_per_minute: int
    overhead_cents_per_pair: int
    status: str
    skill_coverage_certified_pct: float
    skill_coverage_pipeline_pct: float
    created_at: str
    updated_at: str
    version: int


class ShoeModel(TypedDict):
    id: str
    style_code: str
    production_policy: str
    base_price_cents: int
    import_cost_basis_cents: int
    bom_lines: List[BomLine]
    standard_stitching_minutes: int
    standard_lasting_minutes: int
    standard_assembly_minutes: int
    domestic_unit_cost_cents: Optional[int]
    domestic_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict):
    id: str
    component_name: str
    component_type: str
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict):
    id: str
    component_id: str
    supplier_name: str
    is_domestic: bool
    quantity_received: int
    quantity_remaining: int
    unit_cost_cents: int
    received_at: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    model_id: str
    factory_id: str
    run_type: str
    planned_units: int
    line_index: int
    start_day: str
    end_day: str
    iso_week: str
    actual_stitching_minutes: Optional[int]
    actual_lasting_minutes: Optional[int]
    actual_assembly_minutes: Optional[int]
    consumed_lots: List[ConsumedLot]
    certified_unit_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DomesticContentReport(TypedDict):
    id: str
    run_id: str
    variant: str
    material_cost_cents: int
    domestic_material_cost_cents: int
    labor_cost_cents: int
    overhead_cost_cents: int
    domestic_value_cents: int
    total_cost_cents: int
    us_content_pct: float
    final_assembly_domestic: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomOrder(TypedDict):
    id: str
    model_id: str
    buyer_ref: str
    colorway: str
    size: str
    monogram: Optional[str]
    quantity_units: int
    quoted_price_cents: Optional[int]
    production_run_id: Optional[str]
    production_status: str
    created_at: str
    updated_at: str
    version: int


class LabelClaim(TypedDict):
    id: str
    model_id: str
    claim_type: str
    report_id: Optional[str]
    substantiated_at: Optional[str]
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceDocument(TypedDict):
    id: str
    doc_type: str
    claim_id: Optional[str]
    material_lot_id: Optional[str]
    production_run_id: Optional[str]
    issuer: str
    valid_from: str
    valid_until: str
    uploaded_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    factory_id: str
    full_name: str
    status: str
    certifications: List[Certification]
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    worker_id: str
    operation: str
    target_level: int
    attempt_count: int
    last_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityAllocation(TypedDict):
    id: str
    factory_id: str
    iso_week: str
    total_reserved_units: int
    domestic_reserved_units: int
    import_reserved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GovContract(TypedDict):
    id: str
    contract_number: str
    model_id: str
    factory_id: str
    awarded_units: int
    fulfillment_start: str
    fulfillment_end: str
    fulfilled_units: int
    audit_passed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int

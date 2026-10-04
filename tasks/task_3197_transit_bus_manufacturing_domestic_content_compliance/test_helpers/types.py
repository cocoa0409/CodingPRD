"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    CONFIG_ENGINEER = "ConfigEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SUPPLIER_REP = "SupplierRep"
    AUDITOR = "Auditor"
    PRODUCTION_PLANNER = "ProductionPlanner"
    AGENCY_INSPECTOR = "AgencyInspector"
    WARRANTY_ADMIN = "WarrantyAdmin"
    AGENCY_ADMIN = "AgencyAdmin"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class OptionOrderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"


class BusConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    FROZEN = "FROZEN"
    OBSOLETE = "OBSOLETE"


class SupplierDocStatus(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProductionSlotStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class KitStatus(str, Enum):
    NOT_KITTED = "NOT_KITTED"
    KITTED = "KITTED"


class PartsKitStatus(str, Enum):
    STAGING = "STAGING"
    COMPLETE = "COMPLETE"
    CONSUMED = "CONSUMED"


class BusUnitStatus(str, Enum):
    ORDERED = "ORDERED"
    ENGINEERED = "ENGINEERED"
    IN_PRODUCTION = "IN_PRODUCTION"
    BUILT = "BUILT"
    PLANT_INSPECTION = "PLANT_INSPECTION"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    PAID = "PAID"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    CLOSED = "CLOSED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartsStockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class PropulsionType(str, Enum):
    DIESEL = "DIESEL"
    CNG = "CNG"
    HEV = "HEV"
    BEV = "BEV"
    FCEV = "FCEV"


class ComponentCategory(str, Enum):
    PROPULSION = "PROPULSION"
    BODY = "BODY"
    AXLE = "AXLE"
    ELECTRICAL = "ELECTRICAL"
    FARE = "FARE"
    ACCESSIBILITY = "ACCESSIBILITY"


class EscalationIndex(str, Enum):
    PPI_1413 = "PPI_1413"
    CPI_U = "CPI_U"


class CertificateVariant(str, Enum):
    COST_BASED = "COST_BASED"
    COMPONENT_COUNT = "COMPONENT_COUNT"


class AuditType(str, Enum):
    PRE_AWARD = "PRE_AWARD"
    POST_DELIVERY = "POST_DELIVERY"


class LineId(str, Enum):
    LINE_A = "LINE_A"
    LINE_B = "LINE_B"


class AssemblyLocation(str, Enum):
    US_MAIN = "US_MAIN"
    US_ANNEX = "US_ANNEX"


class InspectionType(str, Enum):
    PLANT = "PLANT"
    DELIVERY = "DELIVERY"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Agency(TypedDict, total=False):
    id: str
    name: str
    agency_code: str
    federally_funded: bool
    fleet_transition_target_pct: float
    transition_target_year: int
    zev_ratio: float
    projected_zev_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    agency_id: str
    base_quantity: int
    base_unit_price_cents: int
    base_contract_year: int
    escalation_index: str
    option_years: int
    option_specs: List[Dict[str, Any]]
    awarded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionOrder(TypedDict, total=False):
    id: str
    contract_id: str
    option_year: int
    quantity: int
    propulsion_type: str
    exercised_unit_price_cents: Optional[int]
    status: str
    exercise_deadline: str
    created_at: str
    updated_at: str
    version: int


class BusConfiguration(TypedDict, total=False):
    id: str
    contract_id: str
    propulsion_type: str
    seating_layout: Dict[str, Any]
    fare_equipment: Dict[str, Any]
    accessibility_features: List[str]
    component_ids: List[str]
    seat_count: int
    freeze_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    name: str
    category: str
    unit_cost_cents: int
    is_domestic: bool
    supplier_doc_status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceCertificate(TypedDict, total=False):
    id: str
    bus_unit_id: str
    domestic_content_pct: float
    threshold_pct: float
    variant: str
    issued_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditRecord(TypedDict, total=False):
    id: str
    contract_id: str
    audit_type: str
    auditor_id: str
    scope_bus_count: int
    findings_count: int
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict, total=False):
    id: str
    line_id: str
    start_ts: str
    end_ts: str
    bus_unit_id: Optional[str]
    kit_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsKit(TypedDict, total=False):
    id: str
    bus_unit_id: str
    component_ids: List[str]
    completeness_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BusUnit(TypedDict, total=False):
    id: str
    contract_id: str
    bus_configuration_id: str
    option_order_id: Optional[str]
    serial_number: str
    assembly_location: str
    payment_status: str
    status: str
    delivered_at: Optional[str]
    acceptance_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict, total=False):
    # Append-only observation: id + created_at only, no updated_at / version.
    id: str
    bus_unit_id: str
    inspection_type: str
    inspector_id: str
    result: str
    defects: List[str]
    created_at: str


class WarrantyClaim(TypedDict, total=False):
    id: str
    bus_unit_id: str
    reported_at: str
    defect_code: str
    component_id: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    agency_id: str
    propulsion_type: str
    scheduled_date: str
    attendee_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsStock(TypedDict, total=False):
    id: str
    agency_id: str
    component_id: str
    quantity: int
    reserved_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int

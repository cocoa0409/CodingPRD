"""Domain types for the Donated Medicine Allocation API.

Entity shapes mirror the PRD: every resource carries the common envelope
(id, created_at, updated_at, version) plus its own fields. Status and class
enums enumerate the exact values the PRD names.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Status enums ───────────────────────────────────────────────────────────


class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class ProductClass(str, Enum):
    STANDARD = "STANDARD"
    COLD_CHAIN = "COLD_CHAIN"
    CONTROLLED = "CONTROLLED"
    RESTRICTED_USE = "RESTRICTED_USE"


class DosageForm(str, Enum):
    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    VIAL = "VIAL"
    AMPOULE = "AMPOULE"
    SYRUP = "SYRUP"
    CREAM = "CREAM"
    DEVICE = "DEVICE"


class UnitOfMeasure(str, Enum):
    UNIT = "UNIT"
    VIAL = "VIAL"
    PACK = "PACK"
    BOX = "BOX"


class LotPosture(str, Enum):
    RELEASABLE = "RELEASABLE"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"


class SiteType(str, Enum):
    FREE_CLINIC = "FREE_CLINIC"
    FQHC = "FQHC"
    RURAL_HEALTH_CENTER = "RURAL_HEALTH_CENTER"
    DISASTER_RESPONDER = "DISASTER_RESPONDER"
    HOSPITAL_CHARITY = "HOSPITAL_CHARITY"


class QualificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    PHARMACY = "PHARMACY"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"
    DEA = "DEA"
    WHOLESALER = "WHOLESALER"
    IMPORT = "IMPORT"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AllocationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AllocationDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class AllocationLineStatus(str, Enum):
    RESERVED = "RESERVED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class ShipmentStatus(str, Enum):
    PACKING = "PACKING"
    AWAITING_CUSTOMS_DOCS = "AWAITING_CUSTOMS_DOCS"
    READY_TO_DISPATCH = "READY_TO_DISPATCH"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    CANCELLED = "CANCELLED"


class CustomsDeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class EmergencyEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    STAND_DOWN = "STAND_DOWN"
    CLOSED = "CLOSED"


class ModuleIntendedUse(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    TRAUMA = "TRAUMA"
    CHOLERA = "CHOLERA"
    MATERNAL = "MATERNAL"
    COLD_CHAIN_VACCINE = "COLD_CHAIN_VACCINE"


class ModuleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    CONSUMED = "CONSUMED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ValuationMethod(str, Enum):
    ACQUISITION_COST = "ACQUISITION_COST"
    WHOLESALE_REFERENCE = "WHOLESALE_REFERENCE"


class DistributionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ── Entity shapes (all carry the common envelope) ──────────────────────────


class ManufacturerDonor(TypedDict, total=False):
    id: str
    legal_name: str
    country_code: str
    dea_registration_no: Optional[str]
    tax_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict, total=False):
    id: str
    donor_id: str
    ndc_code: str
    product_name: str
    product_class: str
    dosage_form: str
    unit_of_measure: str
    quantity_received: int
    quantity_available: int
    quantity_quarantined: int
    quantity_committed: int
    quantity_shipped: int
    quantity_expired: int
    expiration_date: str
    storage_temp_min_c: float
    storage_temp_max_c: float
    restricted_use_conditions: List[str]
    requires_cold_chain: bool
    is_controlled: bool
    unit_acquisition_value_usd: float
    unit_wholesale_value_usd: float
    lot_posture: str
    intake_recorded_at: str
    created_at: str
    updated_at: str
    version: int


class RecipientSite(TypedDict, total=False):
    id: str
    organization_name: str
    site_type: str
    country_code: str
    is_international: bool
    cold_storage_capacity_l: int
    has_dea_registration: bool
    monthly_patient_volume: int
    underserved_index: float
    qualification_status: str
    qualified_at: Optional[str]
    active_license_count: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    site_id: str
    license_type: str
    issuing_authority: str
    license_number: str
    expires_on: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRequest(TypedDict, total=False):
    id: str
    site_id: str
    requested_by_user_id: str
    ndc_code: str
    quantity_requested: int
    justification_text: str
    emergency_event_id: Optional[str]
    status: str
    need_score: Optional[float]
    quantity_approved: int
    created_at: str
    updated_at: str
    version: int


class AllocationDecision(TypedDict, total=False):
    id: str
    request_id: str
    reviewer_user_id: str
    decided_at: Optional[str]
    rationale: str
    status: str
    lines: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict, total=False):
    id: str
    decision_id: str
    lot_id: str
    quantity: int
    status: str
    reservation_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    site_id: str
    allocation_decision_id: str
    carrier_name: str
    is_international: bool
    requires_cold_chain: bool
    temperature_band_min_c: Optional[float]
    temperature_band_max_c: Optional[float]
    packed_with_cold_shipper: bool
    customs_declaration_id: Optional[str]
    status: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomsDeclaration(TypedDict, total=False):
    id: str
    shipment_id: str
    hs_code: str
    declared_value_usd: Optional[float]
    import_license_id: str
    destination_country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyEvent(TypedDict, total=False):
    id: str
    event_name: str
    severity: int
    affected_country_codes: List[str]
    declared_at: str
    surge_window_ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepositionedModule(TypedDict, total=False):
    id: str
    module_code: str
    intended_use: str
    holding_country_code: str
    quantity_on_hand: int
    reserved_for_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationSnapshot(TypedDict, total=False):
    id: str
    snapshot_period: str
    donor_id: str
    method: str
    total_value_usd: float
    lot_count: int
    generated_at: str
    created_at: str
    updated_at: str
    version: int


class DistributionReport(TypedDict, total=False):
    id: str
    site_id: str
    shipment_id: str
    reporting_period: str
    units_distributed: int
    patients_reached: int
    wastage_units: int
    submitted_by_user_id: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int

"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DATA_ACQUISITION_MANAGER = "DataAcquisitionManager"
    PRIVACY_OFFICER = "PrivacyOfficer"
    SUPPLIER_OPERATOR = "SupplierOperator"
    MANUFACTURER_CLIENT = "ManufacturerClient"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierType(str, Enum):
    PHARMACY = "PHARMACY"
    DISTRIBUTOR = "DISTRIBUTOR"
    CLAIM_PROCESSOR = "CLAIM_PROCESSOR"


class DataDomain(str, Enum):
    RETAIL_SCRIPTS = "RETAIL_SCRIPTS"
    DISTRIBUTION_SHIPMENTS = "DISTRIBUTION_SHIPMENTS"
    CLAIMS_ADJUDICATION = "CLAIMS_ADJUDICATION"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class HashAlgorithm(str, Enum):
    SHA256 = "SHA256"
    SHA512 = "SHA512"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    DEIDENTIFIED = "DEIDENTIFIED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REPROCESSED = "REPROCESSED"
    QUARANTINED = "QUARANTINED"


class PrescriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Specialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    ONCOLOGY = "ONCOLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    PRIMARY_CARE = "PRIMARY_CARE"


class OptOutStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    LIFTED = "LIFTED"


class ProjectionVariant(str, Enum):
    PROJECTION_WEIGHTED = "PROJECTION_WEIGHTED"
    PROJECTION_DENSITY = "PROJECTION_DENSITY"


class CellStatus(str, Enum):
    CURRENT = "CURRENT"
    PENDING_RESTATEMENT = "PENDING_RESTATEMENT"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SlaVariant(str, Enum):
    PERIOD_WEIGHTED = "PERIOD_WEIGHTED"
    DELIVERY_WEIGHTED = "DELIVERY_WEIGHTED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPILED = "COMPILED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"
    REISSUED = "REISSUED"


class AuditPurpose(str, Enum):
    AUDIT_COMPLIANCE = "AUDIT_COMPLIANCE"
    REIDENTIFICATION = "REIDENTIFICATION"


class AuditOutcome(str, Enum):
    CLEAN = "CLEAN"
    REIDENTIFICATION_ATTEMPTED = "REIDENTIFICATION_ATTEMPTED"


class AuditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- common_fields entities (id + created_at + updated_at + version) ---------

class ManufacturerClient(TypedDict):
    id: str
    name: str
    status: str
    entitlement_cells_total: int
    entitlement_cells_balance: int
    created_at: str
    updated_at: str
    version: int


class DataSupplier(TypedDict):
    id: str
    name: str
    supplier_type: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataAcquisitionAgreement(TypedDict):
    id: str
    supplier_id: str
    data_domain: str
    exclusivity_start_date: str
    exclusivity_end_date: str
    royalty_budget_cents: int
    royalty_spent_cents: int
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DataFeedBatch(TypedDict):
    id: str
    agreement_id: str
    period_code: str
    record_count: int
    deidentification_profile_id: Optional[str]
    deid_qa_score: Optional[float]
    royalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict):
    id: str
    full_name: str
    npi: str
    state_code: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrescriberOptOut(TypedDict):
    id: str
    prescriber_id: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectionMethodology(TypedDict):
    id: str
    name: str
    default_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectionCell(TypedDict):
    id: str
    methodology_id: str
    geography_code: str
    specialty: str
    period_code: str
    sample_units: int
    market_outlets: int
    sampled_outlets: int
    market_population: int
    sampled_population: int
    specialty_uptake_index: float
    supplier_ids: List[str]
    estimate_units: Optional[int]
    restatement_delta_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportProduct(TypedDict):
    id: str
    client_id: str
    methodology_id: str
    name: str
    prescriber_ids: List[str]
    base_fee_cents: int
    cell_fee_base_cents: int
    cell_fee_multiplier: float
    volume_discount_pct: float
    support_fee_pct: float
    monthly_license_fee_cents: int
    deliverable_prescriber_count: int
    pinned_methodology_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportDeliveryPeriod(TypedDict):
    id: str
    product_id: str
    period_code: str
    period_end_date: str
    total_due_deliveries: int
    breach_count: Optional[int]
    sla_variant: Optional[str]
    sla_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportDelivery(TypedDict):
    id: str
    period_id: str
    period_code: str
    status: str
    compiled_cell_ids: List[str]
    included_prescriber_ids: List[str]
    fee_cents: Optional[int]
    recall_count: int
    must_recompile: bool
    created_at: str
    updated_at: str
    version: int


class ClientAuditEvent(TypedDict):
    id: str
    client_id: str
    window_start_date: str
    window_end_date: str
    purpose: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- append-only entities (id + created_at only; no updated_at, no version) --

class DeidentificationProfile(TypedDict):
    id: str
    name: str
    k_anonymity_threshold: int
    salt_version: str
    hash_algorithm: str
    created_at: str


class JurisdictionRule(TypedDict):
    id: str
    state_code: str
    restrict_prescriber_identifiable: bool
    effective_from: str
    effective_to: Optional[str]
    created_at: str

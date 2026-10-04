"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CONTRACTOR = "Contractor"
    DISTRIBUTOR = "Distributor"
    CLAIMANT = "Claimant"
    INSPECTOR = "Inspector"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"


class CertificationTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CertificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ComponentType(str, Enum):
    SHINGLE = "SHINGLE"
    UNDERLAYMENT = "UNDERLAYMENT"
    STARTER = "STARTER"
    RIDGE_CAP = "RIDGE_CAP"
    VENTILATION = "VENTILATION"
    OTHER = "OTHER"


class Manufacturer(str, Enum):
    GAF = "GAF"
    OTHER = "OTHER"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class CoverageClass(str, Enum):
    DRAFT = "DRAFT"
    QUALIFYING_SYSTEM = "QUALIFYING_SYSTEM"
    MIXED_MANUFACTURER = "MIXED_MANUFACTURER"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    INSPECTION_REQUESTED = "INSPECTION_REQUESTED"
    INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class EvidenceType(str, Enum):
    PHOTO = "PHOTO"
    CORE_SAMPLE = "CORE_SAMPLE"
    DOCUMENT = "DOCUMENT"


class Determination(str, Enum):
    MANUFACTURER_DEFECT = "MANUFACTURER_DEFECT"
    INSTALLATION_ERROR = "INSTALLATION_ERROR"
    MIXED = "MIXED"
    NO_DEFECT = "NO_DEFECT"


class InspectionOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class RemedyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ComplaintCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    COMMUNICATION = "COMMUNICATION"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    CONTRACT_DISPUTE = "CONTRACT_DISPUTE"


class LeadAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RETURNED = "RETURNED"


class ScheduleUsed(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    ENHANCED_PLUS = "ENHANCED_PLUS"


class Contractor(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    license_expiry: str
    insurance_expiry: str
    territory_codes: List[str]
    status: str
    workmanship_score: int
    complaint_score_24mo: int
    lifetime_substantiated_count: int
    outstanding_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    title: str
    credits: int
    validity_months: int
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    contractor_id: str
    course_id: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    contractor_id: str
    tier: str
    status: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentCatalogItem(TypedDict, total=False):
    id: str
    sku: str
    component_type: str
    manufacturer: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    id: str
    certification_id: str
    homeowner_name: str
    property_postal_code: str
    install_date: str
    activated_at: Optional[str]
    coverage_tier: Optional[str]
    coverage_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrationComponent(TypedDict, total=False):
    id: str
    registration_id: str
    catalog_sku: str
    component_type: str
    manufacturer: str
    material_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    evidence_type: str
    note: str
    submitted_at: str


class WarrantyClaim(TypedDict, total=False):
    id: str
    registration_id: str
    description: str
    claim_labor_cost_cents: int
    evidence: List[EvidenceItem]
    photo_count: int
    determination: Optional[str]
    filed_at: str
    filing_workmanship_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionOrder(TypedDict, total=False):
    id: str
    claim_id: str
    inspector_id: Optional[str]
    service_date: Optional[str]
    findings: Optional[str]
    confirms_defect: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemedyAllocation(TypedDict, total=False):
    id: str
    claim_id: str
    determination: str
    completed_years: int
    schedule_used: str
    material_pct: int
    prorated_material_pool_cents: int
    material_covered_cents: int
    homeowner_material_share_cents: int
    labor_covered_cents: int
    contractor_liability_cents: int
    workmanship_delta_applied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    contractor_id: str
    category: str
    filed_at: str
    substantiated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict, total=False):
    id: str
    name: str
    territory_codes: List[str]
    lead_pool_total: int
    lead_pool_available: int
    created_at: str
    updated_at: str
    version: int


class LeadAssignment(TypedDict, total=False):
    id: str
    distributor_id: str
    contractor_id: str
    territory_code: str
    required_tier: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int

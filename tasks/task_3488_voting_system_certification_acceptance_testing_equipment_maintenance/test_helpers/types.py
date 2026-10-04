"""Domain types: entity TypedDicts, status enums, role enum.

Field lists follow the PRD resource descriptions. AcceptanceTest and
CustodyTransfer are immutable records: they carry only ``id`` and
``created_at`` of the standard system fields, so their TypedDicts omit
``updated_at`` and ``version`` (PRD: "Both updated_at and version are absent
from these two resources").
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CERTIFICATION_AUTHORITY = "CertificationAuthority"
    VENDOR_REP = "VendorRep"
    LAB_AGENT = "LabAgent"
    ELECTION_OFFICIAL = "ElectionOfficial"
    AUDITOR = "Auditor"
    PUBLIC_REQUESTER = "PublicRequester"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class HardwareClass(str, Enum):
    OPTICAL_SCANNER = "OPTICAL_SCANNER"
    BALLOT_MARKING_DEVICE = "BALLOT_MARKING_DEVICE"
    CENTRAL_TABULATOR = "CENTRAL_TABULATOR"


class VotingSystemStatus(str, Enum):
    REGISTERED = "REGISTERED"
    FIELDED = "FIELDED"
    RETIRED = "RETIRED"


class AccreditationScope(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    DUAL = "DUAL"


class TestLaboratoryStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"


class GuidelinesBaseline(str, Enum):
    VVSG_1_1 = "VVSG_1_1"
    VVSG_2_0 = "VVSG_2_0"


class CampaignStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_TEST = "IN_TEST"
    DEFICIENCIES_FILED = "DEFICIENCIES_FILED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CertificateScope(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class OfficialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProcurementStatus(str, Enum):
    PLACED = "PLACED"
    DELIVERED = "DELIVERED"
    ACCEPTANCE_TESTING = "ACCEPTANCE_TESTING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AcceptanceTestType(str, Enum):
    HARDWARE_DIAGNOSTIC = "HARDWARE_DIAGNOSTIC"
    BALLOT_SCAN_CALIBRATION = "BALLOT_SCAN_CALIBRATION"
    LOGIC_VERIFICATION = "LOGIC_VERIFICATION"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ElectionDefinitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROGRAMMED = "PROGRAMMED"
    LA_PASSED = "LA_PASSED"
    LOCKED = "LOCKED"
    CANVASSING = "CANVASSING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaperCoating(str, Enum):
    UNCOATED = "UNCOATED"
    COATED = "COATED"


class LogicAccuracyTestStatus(str, Enum):
    CONDUCTED = "CONDUCTED"
    CERTIFIED = "CERTIFIED"
    CHALLENGED = "CHALLENGED"


class OperationalStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    IN_SERVICE = "IN_SERVICE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class CustodyStatus(str, Enum):
    SECURED = "SECURED"
    UNSEALED = "UNSEALED"


class WorkType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    BATTERY_REPLACEMENT = "BATTERY_REPLACEMENT"
    REPAIR = "REPAIR"
    CALIBRATION = "CALIBRATION"
    RESEAL = "RESEAL"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ComponentCode(str, Enum):
    BALLOT_LAYOUT_ENGINE = "BALLOT_LAYOUT_ENGINE"
    TABULATION_FIRMWARE = "TABULATION_FIRMWARE"
    ELECTION_MANAGEMENT_UI = "ELECTION_MANAGEMENT_UI"
    AUDIT_LOG_SERVICE = "AUDIT_LOG_SERVICE"
    SECURITY_MODULE = "SECURITY_MODULE"


class ModificationClassification(str, Enum):
    DE_MINIMIS = "DE_MINIMIS"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"


class SoftwareModificationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DE_MINIMIS_APPROVED = "DE_MINIMIS_APPROVED"
    RECERTIFICATION_PENDING = "RECERTIFICATION_PENDING"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AuditType(str, Enum):
    RISK_LIMITING = "RISK_LIMITING"
    COMPLIANCE = "COMPLIANCE"
    FULL_RECOUNT = "FULL_RECOUNT"


class AuditStatus(str, Enum):
    INITIATED = "INITIATED"
    FINDINGS_FILED = "FINDINGS_FILED"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"
    CLOSED_ESCALATED = "CLOSED_ESCALATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class VotingSystem(TypedDict):
    id: str
    vendor_name: str
    model_name: str
    software_baseline_version: str
    hardware_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestLaboratory(TypedDict):
    id: str
    lab_code: str
    lab_name: str
    accreditation_scope: str
    max_concurrent_campaigns: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationCampaign(TypedDict):
    id: str
    voting_system_id: str
    lab_id: str
    guidelines_baseline: str
    state_code: Optional[str]
    status: str
    resubmission_count: int
    open_critical_count: int
    open_major_count: int
    open_minor_count: int
    conformity_screen_bp: int
    conformity_final_bp: int
    last_submitted_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    voting_system_id: str
    campaign_id: str
    scope: str
    state_code: Optional[str]
    guidelines_baseline: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    name: str
    state_code: str
    budget_total_cents: int
    available_cents: int
    encumbered_cents: int
    spent_cents: int
    created_at: str
    updated_at: str
    version: int


class ElectionOfficial(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    badge_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Procurement(TypedDict):
    id: str
    jurisdiction_id: str
    voting_system_id: str
    certificate_id: str
    certificate_version_pinned: int
    quantity: int
    unit_price_cents: int
    total_price_cents: int
    cert_hold: bool
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcceptanceTest(TypedDict):
    # Immutable record: id + created_at only (no updated_at, no version).
    id: str
    created_at: str
    procurement_id: str
    test_type: str
    critical_defects: int
    major_defects: int
    minor_defects: int
    deficiency_index: int
    result: str


class ElectionDefinition(TypedDict):
    id: str
    jurisdiction_id: str
    procurement_id: str
    name: str
    election_date: str
    precinct_count: int
    ballot_layout: Optional[Dict[str, Any]]
    layout_revision: int
    paper_weight_gsm: Optional[int]
    paper_thickness_microns: Optional[int]
    paper_coating: Optional[str]
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LogicAccuracyTest(TypedDict):
    id: str
    election_definition_id: str
    conducted_by: str
    certified_by: Optional[str]
    expected_tallies: Dict[str, int]
    scanned_tallies: Dict[str, int]
    total_expected: int
    total_discrepancy: int
    discrepancy_bp: int
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    jurisdiction_id: str
    voting_system_id: str
    serial_number: str
    operational_status: str
    custody_status: str
    current_custodian_id: str
    battery_cycles: int
    storage_excursion_count: int
    pre_maintenance_status: Optional[str]
    calibrated_paper_weight_gsm: Optional[int]
    calibrated_paper_thickness_microns: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict):
    id: str
    equipment_unit_id: str
    work_type: str
    scheduled_start: str
    scheduled_end: str
    calibration_paper_weight_gsm: Optional[int]
    calibration_paper_thickness_microns: Optional[int]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustodyTransfer(TypedDict):
    # Immutable record: id + created_at only (no updated_at, no version).
    id: str
    created_at: str
    equipment_unit_id: str
    from_official_id: str
    to_official_id: str
    seal_number: str
    seal_intact: bool
    transferred_at: str


class SoftwareModification(TypedDict):
    id: str
    voting_system_id: str
    description: str
    component_codes: List[str]
    classification: Optional[str]
    lead_time_days: Optional[int]
    submitted_at: str
    classified_at: Optional[str]
    effective_at: Optional[str]
    new_baseline_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PostElectionAudit(TypedDict):
    id: str
    election_definition_id: str
    audit_type: str
    critical_findings: int
    major_findings: int
    minor_findings: int
    report_public: bool
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int

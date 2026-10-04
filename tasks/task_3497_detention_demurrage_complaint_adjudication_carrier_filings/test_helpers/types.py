"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COMMISSION_ADMIN = "CommissionAdmin"
    COMMISSION_DOCKET = "CommissionDocket"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    OMBUDS_OFFICER = "OmbudsOfficer"
    ADMINISTRATIVE_LAW_JUDGE = "AdministrativeLawJudge"
    ENFORCEMENT_COUNSEL = "EnforcementCounsel"
    CARRIER_REP = "CarrierRep"
    SHIPPER_REP = "ShipperRep"


class OrgType(str, Enum):
    VOCC = "VOCC"
    MTO = "MTO"
    NVOCC = "NVOCC"
    OFF = "OFF"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ChargeScope(str, Enum):
    DETENTION = "DETENTION"
    DEMURRAGE = "DEMURRAGE"
    GENERAL = "GENERAL"


class AccrualMethod(str, Enum):
    CALENDAR = "CALENDAR"
    WORKING_DAY = "WORKING_DAY"


class ChangeType(str, Enum):
    NEW = "NEW"
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementType(str, Enum):
    VESSEL_SHARING = "VESSEL_SHARING"
    RATE_DISCUSSION = "RATE_DISCUSSION"
    EQUIPMENT_POOLING = "EQUIPMENT_POOLING"
    SPACE_CHARTER = "SPACE_CHARTER"


class ReviewStatus(str, Enum):
    AWAITING_REVIEW = "AWAITING_REVIEW"
    EFFECTIVE = "EFFECTIVE"


class LicenseType(str, Enum):
    NVOCC = "NVOCC"
    OFF = "OFF"


class LicenseStatus(str, Enum):
    PENDING_BOND = "PENDING_BOND"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BondStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class ChargeBasis(str, Enum):
    TARIFF = "TARIFF"
    SERVICE_CONTRACT = "SERVICE_CONTRACT"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisputeReason(str, Enum):
    LATE_ISSUANCE = "LATE_ISSUANCE"
    INCORRECT_PARTY = "INCORRECT_PARTY"
    MISSING_ELEMENTS = "MISSING_ELEMENTS"
    CHARGE_EXCEEDS_PUBLISHED = "CHARGE_EXCEEDS_PUBLISHED"
    OTHER = "OTHER"


class DisputeResolution(str, Enum):
    PENDING = "PENDING"
    UPHELD_WAIVED = "UPHELD_WAIVED"
    UPHELD_REDUCED = "UPHELD_REDUCED"
    DENIED = "DENIED"


class RequestedResolution(str, Enum):
    WAIVE = "WAIVE"
    REDUCE = "REDUCE"
    DENY = "DENY"


class ComplaintStatus(str, Enum):
    DOCKETED = "DOCKETED"
    OMBUDS = "OMBUDS"
    RESOLVED_INFORMAL = "RESOLVED_INFORMAL"
    ADJUDICATION_OPEN = "ADJUDICATION_OPEN"
    ADJUDICATION_DECIDED = "ADJUDICATION_DECIDED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class ReparationMethod(str, Enum):
    OUT_OF_POCKET = "OUT_OF_POCKET"
    FLUIDITY_WEIGHTED = "FLUIDITY_WEIGHTED"


class ProceedingBasis(str, Enum):
    UNREASONABLE_PRACTICE = "UNREASONABLE_PRACTICE"
    TARIFF_VIOLATION = "TARIFF_VIOLATION"
    UNLICENSED_ACTIVITY = "UNLICENSED_ACTIVITY"
    AGREEMENT_VIOLATION = "AGREEMENT_VIOLATION"


class ProceedingStatus(str, Enum):
    NOTICE_ISSUED = "NOTICE_ISSUED"
    DETERMINED = "DETERMINED"
    DISMISSED = "DISMISSED"


class Determination(str, Enum):
    VIOLATION_FOUND = "VIOLATION_FOUND"
    NO_VIOLATION = "NO_VIOLATION"


class CarrierOrganization(TypedDict, total=False):
    id: str
    org_name: str
    org_type: str
    status: str
    compliance_score: int
    cumulative_civil_penalties_cents: int
    created_at: str
    updated_at: str
    version: int


class ShipperAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    total_recovery_cents: int
    created_at: str
    updated_at: str
    version: int


class TariffPublication(TypedDict, total=False):
    id: str
    carrier_id: str
    tariff_code: str
    charge_scope: str
    free_time_days: int
    per_diem_rate_cents: int
    accrual_method: str
    change_type: str
    notice_period_days: int
    effective_date: str
    filed_at: str
    publication_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    carrier_id: str
    contract_reference: str
    shipper_id: str
    agreed_at: str
    duration_months: int
    minimum_quantity_commitment: int
    negotiated_free_time_days: int
    negotiated_per_diem_rate_cents: int
    negotiated_accrual_method: str
    filed_at: str
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class CarrierAgreement(TypedDict, total=False):
    id: str
    agreement_number: str
    agreement_type: str
    member_carrier_ids: List[str]
    filed_by_carrier_id: str
    filed_at: str
    waiting_period_ends_at: str
    review_status: str
    monitoring_reports: List[dict]
    market_concentration_hhi: Optional[float]
    competitive_concern_flag: bool
    created_at: str
    updated_at: str
    version: int


class SuretyBond(TypedDict, total=False):
    bond_ref: str
    surety_name: str
    coverage_cents: int
    drawn_cents: int
    available_cents: int
    bond_status: str


class OTILicense(TypedDict, total=False):
    id: str
    organization_id: str
    license_type: str
    license_status: str
    required_bond_cents: int
    surety_bonds: List[SuretyBond]
    total_available_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class DemurrageDetentionInvoice(TypedDict, total=False):
    id: str
    carrier_id: str
    invoice_number: str
    charge_basis: str
    tariff_id: Optional[str]
    service_contract_id: Optional[str]
    billed_party_shipper_id: str
    container_number: str
    port_code: str
    availability_date: str
    return_date: str
    last_accrual_date: str
    government_hold_days: int
    appointment_unavailable_days: int
    free_time_days: int
    per_diem_rate_cents: int
    accrual_method: str
    billable_days: int
    amount_cents: int
    issued_at: str
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceDispute(TypedDict, total=False):
    id: str
    invoice_id: str
    dispute_reason: str
    filed_at: str
    response_due_at: str
    responded_at: Optional[str]
    requested_resolution: Optional[str]
    resolution: str
    response_was_late: bool
    resolved_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    shipper_id: str
    respondent_carrier_id: str
    subject_invoice_ids: List[str]
    reparations_claimed_cents: int
    incentive_principle_score: int
    complaint_status: str
    ombuds_officer_id: Optional[str]
    ombuds_rounds: int
    informal_settlement_cents: Optional[int]
    presiding_judge_id: Optional[str]
    reparation_method: Optional[str]
    reparations_awarded_cents: int
    decided_at: Optional[str]
    appeal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementProceeding(TypedDict, total=False):
    id: str
    target_carrier_id: str
    basis: str
    opened_by_counsel_id: str
    proceeding_status: str
    determination: Optional[str]
    violation_count: Optional[int]
    willful: Optional[bool]
    repeat_offender: Optional[bool]
    penalty_cents: Optional[int]
    score_delta: Optional[int]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortCongestionReport(TypedDict, total=False):
    """Append-only data-collection record: carries ONLY id + created_at
    (no updated_at, no version) per PRD §2.5."""
    id: str
    port_code: str
    terminal_code: str
    week_start: str
    berth_occupancy_hours: int
    gate_closures_hours: int
    vessel_dwell_hours_avg: float
    created_at: str

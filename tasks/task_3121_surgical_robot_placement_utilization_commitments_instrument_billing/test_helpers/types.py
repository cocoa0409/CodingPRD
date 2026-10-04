"""Domain types: status enums, role enum and entity TypedDicts.

Every resource declared by the PRD carries the standard system-managed quartet
(`id`, `created_at`, `updated_at`, `version`), so each TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Status enums ────────────────────────────────────────────────────────────

class AccountStatus(str, Enum):
    PROSPECT = "PROSPECT"
    READINESS = "READINESS"
    CONTRACTED = "CONTRACTED"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"


class AccountPosture(str, Enum):
    ACTIVE = "ACTIVE"
    ONBOARDING_GATE = "ONBOARDING_GATE"
    EXPANSION_BLOCKED = "EXPANSION_BLOCKED"


class ReadinessStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"


class ConfigurationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ArrangementType(str, Enum):
    PURCHASE = "PURCHASE"
    LEASE = "LEASE"
    USAGE_BASED = "USAGE_BASED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ComplianceStatus(str, Enum):
    MEETS_COMMITMENT = "MEETS_COMMITMENT"
    SHORTFALL_WARNING = "SHORTFALL_WARNING"
    SHORTFALL_CHARGEABLE = "SHORTFALL_CHARGEABLE"
    NON_COMPLIANT = "NON_COMPLIANT"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


class SystemStatus(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    SERVICE_ACTION_REQUIRED = "SERVICE_ACTION_REQUIRED"
    DECOMMISSIONED = "DECOMMISSIONED"


class TrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SIMULATION_COMPLETE = "SIMULATION_COMPLETE"
    PROCTORING = "PROCTORING"
    SIMULATION_INCOMPLETE = "SIMULATION_INCOMPLETE"
    CREDENTIALED = "CREDENTIALED"


class EvidenceStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EvidenceType(str, Enum):
    CREDENTIAL_LETTER = "CREDENTIAL_LETTER"
    PRIVILEGE_ATTESTATION = "PRIVILEGE_ATTESTATION"
    PROCTOR_SIGNOFF_SET = "PROCTOR_SIGNOFF_SET"


class UtilizationBand(str, Enum):
    UNDERUTILIZED = "UNDERUTILIZED"
    BASELINE = "BASELINE"
    HIGH = "HIGH"
    EXPANSION_READY = "EXPANSION_READY"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BILLED = "BILLED"


class ProcedureFamily(str, Enum):
    UROLOGY = "UROLOGY"
    GYNECOLOGY = "GYNECOLOGY"
    GENERAL_SURGERY = "GENERAL_SURGERY"
    THORACIC = "THORACIC"
    COLORECTAL = "COLORECTAL"


class CoverageTier(str, Enum):
    COMPREHENSIVE = "COMPREHENSIVE"
    STANDARD = "STANDARD"
    LIMITED = "LIMITED"
    PARTS_ONLY = "PARTS_ONLY"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    LOANER_PENDING = "LOANER_PENDING"
    LOANER_DISPATCHED = "LOANER_DISPATCHED"
    SERVICE_ACTION_REQUIRED = "SERVICE_ACTION_REQUIRED"
    RESOLVED = "RESOLVED"


class ReservationStatus(str, Enum):
    PROGRAMMED = "PROGRAMMED"
    ACTIVATED = "ACTIVATED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"
    RECLAIMED = "RECLAIMED"


class DeploymentStatus(str, Enum):
    PROGRAMMED = "PROGRAMMED"
    DELIVERED = "DELIVERED"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExpansionReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TransferStatus(str, Enum):
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ServiceLineTier(str, Enum):
    """Observed service-line depth labels, indexed 0..4."""

    OBSERVATIONAL = "OBSERVATIONAL"
    ESTABLISHED = "ESTABLISHED"
    DEVELOPING = "DEVELOPING"
    ADVANCED = "ADVANCED"
    REFERENCE = "REFERENCE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGIONAL_SALES_DIRECTOR = "RegionalSalesDirector"
    CLINICAL_OPERATIONS_LEAD = "ClinicalOperationsLead"
    HOSPITAL_PROCUREMENT_OFFICER = "HospitalProcurementOfficer"
    SERVICE_ENGINEER = "ServiceEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    IDN_COORDINATOR = "IDNCoordinator"
    ACCOUNT_OWNER = "AccountOwner"
    SURGEON = "Surgeon"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ──────────

class HospitalAccount(TypedDict, total=False):
    id: str
    account_name: str
    idn_group_code: str
    region_code: str
    account_status: str
    account_posture: str
    placement_cap: int
    service_line_tier: str
    dormant_since_utc: Optional[str]
    hospital_owner_user_id: str
    created_at: str
    updated_at: str
    version: int


class SiteReadinessReview(TypedDict, total=False):
    id: str
    hospital_account_id: str
    review_round: int
    site_code: str
    operating_room_length_cm: int
    operating_room_width_cm: int
    table_throw_radius_cm: int
    ceiling_clearance_cm: int
    has_dedicated_power_circuit: bool
    has_dark_fiber_run: bool
    evaluated_configuration_id: str
    readiness_status: str
    construction_uplift_fee_cents: int
    conditional_clearance_count: int
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SystemConfiguration(TypedDict, total=False):
    id: str
    model_code: str
    base_placement_fee_cents: int
    max_instrument_lives: int
    feature_entitlements: List[dict]
    requires_dark_fiber: bool
    requires_dedicated_power_circuit: bool
    integration_tier: int
    min_operating_room_length_cm: int
    min_operating_room_width_cm: int
    min_table_throw_radius_cm: int
    min_ceiling_clearance_cm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementAgreement(TypedDict, total=False):
    id: str
    hospital_account_id: str
    system_configuration_id: str
    site_readiness_review_id: str
    arrangement_type: str
    base_monthly_fee_cents: int
    minimum_procedures_per_cycle: int
    interval_months: int
    placement_fee_cents: int
    lease_monthly_amount_cents: int
    usage_rate_basis_points: int
    committed_cases: int
    cycle_start_utc: Optional[str]
    cycle_end_utc: Optional[str]
    shortfall_procedures: int
    synthesized_system_id: Optional[str]
    synthesized_system_version: Optional[int]
    synthesized_service_contract_id: Optional[str]
    net_placement_fee_cents: Optional[int]
    last_shortfall_fee_cents: int
    is_shortfall_waived: bool
    compliance_status: str
    agreement_status: str
    acceptance_expires_utc: Optional[str]
    activated_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RobotSystem(TypedDict, total=False):
    id: str
    hospital_account_id: str
    system_configuration_id: str
    placement_agreement_id: str
    site_readiness_review_id: str
    serial_number: str
    service_status: str
    installed_software_release_index: int
    entitled_feature_codes: List[str]
    current_utilization_cycle_id: Optional[str]
    instrument_lives_remaining: int
    expansion_eligible: bool
    created_at: str
    updated_at: str
    version: int


class SurgeonTrainingRecord(TypedDict, total=False):
    id: str
    hospital_account_id: str
    surgeon_name: str
    surgeon_npi: str
    training_status: str
    simulation_modules_completed: int
    required_proctored_cases: int
    proctored_cases_completed: int
    proctor_approval_pending: bool
    credential_expires_utc: Optional[str]
    evidence_required_after_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialingEvidence(TypedDict, total=False):
    id: str
    surgeon_training_record_id: str
    hospital_account_id: str
    evidence_type: str
    issued_utc: str
    expires_utc: str
    evidence_status: str
    created_at: str
    updated_at: str
    version: int


class UtilizationCycle(TypedDict, total=False):
    id: str
    robot_system_id: str
    placement_agreement_id: str
    cycle_start_utc: str
    cycle_end_utc: str
    scheduled_case_count: int
    completed_case_count: int
    utilization_band: str
    same_hour_conflict_count: int
    reporting_period_index: int
    created_at: str
    updated_at: str
    version: int


class ProcedureCase(TypedDict, total=False):
    id: str
    robot_system_id: str
    hospital_account_id: str
    placement_agreement_id: str
    training_record_id: str
    procedure_family: str
    case_started_at: str
    duration_minutes: int
    instrument_load: int
    is_emergency: bool
    approved_instrument_load: int
    instrument_billing_cents: int
    commitment_cycle_index: int
    case_status: str
    created_at: str
    updated_at: str
    version: int


class LoanerSystemDispatch(TypedDict, total=False):
    id: str
    robot_system_id: str
    loaner_serial_number: str
    dispatch_window_start_utc: str
    dispatch_window_end_utc: str
    reservation_status: str
    reclaim_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    robot_system_id: str
    coverage_tier: str
    service_tier_index: int
    response_time_commitment_hours: int
    contract_start_utc: str
    contract_months: int
    contract_end_utc: str
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class IncidentServiceRequest(TypedDict, total=False):
    id: str
    robot_system_id: str
    incident_started_at: str
    resolved_at_utc: Optional[str]
    incident_severity: str
    response_due_at_utc: str
    request_status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SoftwareRelease(TypedDict, total=False):
    id: str
    system_configuration_id: str
    release_index: int
    feature_codes: List[str]
    deployed: bool
    created_at: str
    updated_at: str
    version: int


class SoftwareReleaseDeployment(TypedDict, total=False):
    id: str
    robot_system_id: str
    software_release_id: str
    deployment_status: str
    scheduled_window_start_utc: str
    scheduled_window_end_utc: str
    entitlement_snapshot: List[str]
    created_at: str
    updated_at: str
    version: int


class ExpansionReview(TypedDict, total=False):
    id: str
    hospital_account_id: str
    placement_agreement_id: str
    eligible_system_id: Optional[str]
    eligible_system_utilization: int
    requires_prior_reporting_period: bool
    review_status: str
    decided_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilisationConsumptionLedger(TypedDict, total=False):
    id: str
    hospital_account_id: str
    donor_idn_group_code: str
    consumed_procedure_units: int
    supplied_procedure_units: int
    remaining_credit_units: int
    maximum_procedure_commitment: int
    created_at: str
    updated_at: str
    version: int


class UtilisationTransferTransaction(TypedDict, total=False):
    id: str
    source_account_id: str
    destination_account_id: str
    procedure_units: int
    transfer_window_start_utc: str
    transfer_window_end_utc: str
    transaction_status: str
    reversal_reason: Optional[str]
    settlement_certified_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int
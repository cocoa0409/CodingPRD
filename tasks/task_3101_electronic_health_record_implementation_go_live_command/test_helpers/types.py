"""Domain types: entity TypedDicts, status enums and the role enum.

Derived from the PRD's resource definitions. Entities that carry the standard
common-field treatment declare ``id``, ``created_at``, ``updated_at`` and
``version``; the append-only ``InterfaceMessage`` declares only ``id`` and
``created_at``.
"""

from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    """The fourteen recognised operational capacities."""

    IMPLEMENTATION_DIRECTOR = "ImplementationDirector"
    IMPLEMENTATION_ANALYST = "ImplementationAnalyst"
    BUILD_ANALYST = "BuildAnalyst"
    TEST_LEAD = "TestLead"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    CREDENTIALED_TRAINER = "CredentialedTrainer"
    CONVERSION_ANALYST = "ConversionAnalyst"
    ORDER_RECONCILER = "OrderReconciler"
    REVENUE_CYCLE_ANALYST = "RevenueCycleAnalyst"
    INTERFACE_ENGINEER = "InterfaceEngineer"
    CUTOVER_LEAD = "CutoverLead"
    COMMAND_CENTER_LEAD = "CommandCenterLead"
    TRIAGE_COMMANDER = "TriageCommander"
    OPTIMIZATION_LEAD = "OptimizationLead"


# ---------------------------------------------------------------------------
# Status / state enumerations
# ---------------------------------------------------------------------------

class ImplementationStatus(str, Enum):
    PLANNING = "PLANNING"
    BUILD_IN_PROGRESS = "BUILD_IN_PROGRESS"
    VALIDATION_IN_PROGRESS = "VALIDATION_IN_PROGRESS"
    CUTOVER_READY = "CUTOVER_READY"
    GO_LIVE_ACTIVE = "GO_LIVE_ACTIVE"
    COMMAND_CENTER_ACTIVE = "COMMAND_CENTER_ACTIVE"
    STABILIZED = "STABILIZED"
    POST_LIVE_OPTIMIZATION = "POST_LIVE_OPTIMIZATION"
    ARCHIVED = "ARCHIVED"


class ReadinessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"


class FacilityStatus(str, Enum):
    SITE_REGISTERED = "SITE_REGISTERED"
    BUILD_CONFIGURED = "BUILD_CONFIGURED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    VALIDATED = "VALIDATED"
    CUTOVER_READY = "CUTOVER_READY"
    LIVE = "LIVE"
    STABILIZED = "STABILIZED"
    STABILIZATION_AT_RISK = "STABILIZATION_AT_RISK"


class FacilityType(str, Enum):
    ACUTE_CARE = "ACUTE_CARE"
    CRITICAL_ACCESS = "CRITICAL_ACCESS"
    AMBULATORY = "AMBULATORY"
    SPECIALTY = "SPECIALTY"


class ConversionScope(str, Enum):
    FULL_RECORD = "FULL_RECORD"
    DEMOGRAPHICS_ONLY = "DEMOGRAPHICS_ONLY"
    SCHEDULING_ONLY = "SCHEDULING_ONLY"


class DepartmentStatus(str, Enum):
    BUILD_PENDING = "BUILD_PENDING"
    BUILD_COMPLETE = "BUILD_COMPLETE"
    TRAINING_IN_PROGRESS = "TRAINING_IN_PROGRESS"
    READY_FOR_GO_LIVE = "READY_FOR_GO_LIVE"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    LIVE = "LIVE"


class BuildItemStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_BUILD = "IN_BUILD"
    BUILD_COMPLETE = "BUILD_COMPLETE"
    IN_TESTING = "IN_TESTING"
    VALIDATION_COMPLETE = "VALIDATION_COMPLETE"
    BUILD_REJECTED = "BUILD_REJECTED"


class BuildClassification(str, Enum):
    FOUNDATION_ADOPTED = "FOUNDATION_ADOPTED"
    FOUNDATION_ADAPTED = "FOUNDATION_ADAPTED"
    LOCAL_CUSTOM = "LOCAL_CUSTOM"


class StaffStatus(str, Enum):
    REGISTERED = "REGISTERED"
    TRAINING_ASSIGNED = "TRAINING_ASSIGNED"
    TRAINED = "TRAINED"
    PROFICIENCY_VERIFIED = "PROFICIENCY_VERIFIED"
    CREDENTIALED = "CREDENTIALED"
    PROFICIENCY_FAILED = "PROFICIENCY_FAILED"


class StaffType(str, Enum):
    PROVIDER = "PROVIDER"
    NURSE = "NURSE"
    ALLIED_HEALTH = "ALLIED_HEALTH"
    REGISTRATION = "REGISTRATION"
    BILLING = "BILLING"
    ANALYST = "ANALYST"


class TrainingAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class CredentialedTrainerStatus(str, Enum):
    PENDING_OBSERVATION = "PENDING_OBSERVATION"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CertificationLevel(str, Enum):
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"


class ProficiencyExamStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    NO_SHOW = "NO_SHOW"


class ScenarioStatus(str, Enum):
    DEFINED = "DEFINED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ScenarioClass(str, Enum):
    UNIT = "UNIT"
    INTEGRATED = "INTEGRATED"
    CHARGE_CAPTURE_TO_CLAIM = "CHARGE_CAPTURE_TO_CLAIM"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    IN_REMEDIATION = "IN_REMEDIATION"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"
    REOPENED = "REOPENED"


class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class ConversionBatchStatus(str, Enum):
    STAGED = "STAGED"
    VALIDATING = "VALIDATING"
    LOADED = "LOADED"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class PayloadClass(str, Enum):
    PATIENT_DEMOGRAPHICS = "PATIENT_DEMOGRAPHICS"
    APPOINTMENTS = "APPOINTMENTS"
    ORDERS = "ORDERS"
    BALANCES = "BALANCES"


class OrderType(str, Enum):
    MEDICATION = "MEDICATION"
    LAB = "LAB"
    IMAGING = "IMAGING"
    PROCEDURE = "PROCEDURE"


class ClinicalState(str, Enum):
    CONVERTED = "CONVERTED"
    RECONCILED = "RECONCILED"
    PAPER_BACKFILL_REQUIRED = "PAPER_BACKFILL_REQUIRED"


class BillingState(str, Enum):
    UNPOSTED = "UNPOSTED"
    CHARGE_POSTED = "CHARGE_POSTED"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_ACCEPTED = "CLAIM_ACCEPTED"
    CLAIM_DENIED = "CLAIM_DENIED"
    CLAIM_PAID = "CLAIM_PAID"


class InterfaceChannelStatus(str, Enum):
    DEFINED = "DEFINED"
    BUILDING = "BUILDING"
    IN_MESSAGE_VALIDATION = "IN_MESSAGE_VALIDATION"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class ChannelType(str, Enum):
    LAB = "LAB"
    IMAGING = "IMAGING"
    PHARMACY = "PHARMACY"
    DEVICE = "DEVICE"


class MessageFormat(str, Enum):
    HL7_V2 = "HL7_V2"
    FHIR = "FHIR"
    DICOM = "DICOM"
    CSV = "CSV"


class MessageValidationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CutoverTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class TaskClass(str, Enum):
    DOWNTIME_PREP = "DOWNTIME_PREP"
    ORDER_RECONCILIATION = "ORDER_RECONCILIATION"
    PAPER_BACKFILL = "PAPER_BACKFILL"
    DRESS_REHEARSAL = "DRESS_REHEARSAL"
    GO_NO_GO_DECISION = "GO_NO_GO_DECISION"


class TicketTriageState(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    IN_RESOLUTION = "IN_RESOLUTION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    REASSIGNED = "REASSIGNED"


class SupportRole(str, Enum):
    AT_THE_ELBOW = "AT_THE_ELBOW"
    TRIAGE_COMMANDER = "TRIAGE_COMMANDER"
    APPLICATION_ANALYST = "APPLICATION_ANALYST"
    CHARGE_CAPTURE_SPECIALIST = "CHARGE_CAPTURE_SPECIALIST"


class OptimizationItemStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

# common_fields: true — carries id + created_at + updated_at + version
class EhrImplementation(TypedDict):
    id: str
    program_name: str
    vendor_release: str
    go_live_target_utc: str
    status: str
    readiness_posture: str
    current_epoch_index: int
    readiness_score: float
    optimistic_readiness_score: float
    net_trainer_count: int
    order_reconciliation_balance: int
    command_center_activated_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    ehr_implementation_id: str
    name: str
    facility_type: str
    bed_count: int
    rollout_wave: int
    conversion_scope: str
    converted_patient_count: int
    conversion_variance_index: float
    revenue_cycle_stabilization_index: float
    status: str
    is_live: bool
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    facility_id: str
    ehr_implementation_id: str
    department_code: str
    application_scope: List[str]
    required_staff_count: int
    proficiency_cleared_count: int
    proficiency_cleared_ratio: float
    proficiency_gate_open: bool
    build_blocking_defect_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SystemBuildItem(TypedDict):
    id: str
    department_id: str
    ehr_implementation_id: str
    application_code: str
    build_classification: str
    customization_depth: int
    local_custom_fields: List[str]
    customization_risk_points: float
    test_cycles_passed: int
    open_defect_count: int
    rejection_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict):
    id: str
    ehr_implementation_id: str
    full_name: str
    staff_type: str
    primary_facility_id: str
    department_id: str
    preceptor_staff_id: Optional[str]
    hired_on: str
    accumulated_training_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict):
    id: str
    staff_id: str
    ehr_implementation_id: str
    curriculum_code: str
    application_code: str
    required_hours: float
    completed_hours: float
    completion_pct: float
    due_utc: str
    waiver_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CredentialedTrainer(TypedDict):
    id: str
    staff_id: str
    ehr_implementation_id: str
    application_code: str
    certification_level: str
    observation_hours: float
    certified_utc: Optional[str]
    expires_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProficiencyExam(TypedDict):
    id: str
    staff_id: str
    ehr_implementation_id: str
    application_code: str
    proctored_by_trainer_id: str
    exam_score: Optional[float]
    passing_score: float
    attempt_number: int
    next_attempt_eligible_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestScenario(TypedDict):
    id: str
    system_build_item_id: str
    ehr_implementation_id: str
    scenario_class: str
    step_count: int
    executed_epoch: Optional[int]
    open_defect_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestDefect(TypedDict):
    id: str
    test_scenario_id: str
    ehr_implementation_id: str
    defect_code: str
    severity: str
    blocks_go_live: bool
    resolution_epoch: Optional[int]
    attempt_count: int
    aging_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DataConversionBatch(TypedDict):
    id: str
    facility_id: str
    ehr_implementation_id: str
    payload_class: str
    attempt_epoch: int
    source_count: int
    reconciled_count: int
    variance_count: int
    variance_penalty_points: float
    applied_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientOrder(TypedDict):
    id: str
    facility_id: str
    ehr_implementation_id: str
    patient_mrn: str
    order_type: str
    encounter_utc: str
    legacy_charge_cents: int
    balance_cents: int
    provisional_charge_cents: float
    final_charge_cents: float
    charge_variance_cents: float
    paper_backfill_count: int
    clinical_state: str
    billing_state: str
    created_at: str
    updated_at: str
    version: int


class InterfaceChannel(TypedDict):
    id: str
    ehr_implementation_id: str
    channel_type: str
    external_system: str
    message_format: str
    throughput_per_hour: int
    max_latency_minutes: float
    validated_message_count: int
    rejected_message_count: int
    interface_message_validation_pass_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class InterfaceMessage(TypedDict):
    id: str
    interface_channel_id: str
    ehr_implementation_id: str
    message_code: str
    direction: str
    received_utc: str
    latency_minutes: float
    validation_status: str
    validation_error_code: Optional[str]
    created_at: str


class CutoverTask(TypedDict):
    id: str
    facility_id: str
    ehr_implementation_id: str
    task_class: str
    sequence_index: int
    planned_start_utc: str
    planned_end_utc: str
    duration_minutes: float
    block_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommandCenterTicket(TypedDict):
    id: str
    ehr_implementation_id: str
    facility_id: str
    department_id: Optional[str]
    target_ref: str
    severity: str
    at_the_elbow_zone: str
    linked_test_defect_id: Optional[str]
    reported_utc: str
    resolution_sla_minutes: int
    triage_state: str
    created_at: str
    updated_at: str
    version: int


class StaffingShift(TypedDict):
    id: str
    ehr_implementation_id: str
    staff_id: str
    facility_id: str
    support_role: str
    start_utc: str
    end_utc: str
    handoff_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OptimizationBacklogItem(TypedDict):
    id: str
    department_id: str
    ehr_implementation_id: str
    title: str
    effort_points: int
    requested_epoch: int
    scheduled_epoch: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
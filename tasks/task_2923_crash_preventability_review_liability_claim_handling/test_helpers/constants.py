"""Domain constants for the crash preventability review and liability claim API.

Every value here is taken from the product requirements document so that tests
express expected outcomes in domain language instead of bare literals.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# The service clock starts at exactly this instant on a fresh database and only
# moves when the clock endpoint is called.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles and operator identities
# ---------------------------------------------------------------------------

ROLE_SAFETY_ADMIN = "SafetyAdmin"
ROLE_DISPATCHER = "Dispatcher"
ROLE_DRIVER = "Driver"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_SAFETY_MANAGER = "SafetyManager"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"
ROLE_CLAIMS_MANAGER = "ClaimsManager"
ROLE_AUDITOR = "Auditor"

ALL_ROLES = (
    ROLE_SAFETY_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_SAFETY_MANAGER,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_CLAIMS_MANAGER,
    ROLE_AUDITOR,
)

# Opaque operator identifiers. Only the Driver role is entity backed, so these
# strings are never existence checked by the service.
OPERATOR_IDS = {
    "safety_admin": "sa-001",
    "dispatcher": "disp-001",
    "committee_member_one": "cm-001",
    "committee_member_two": "cm-002",
    "committee_member_three": "cm-003",
    "safety_manager_decider": "sm-001",
    "safety_manager_appeals": "sm-002",
    "claims_adjuster": "adj-001",
    "claims_manager": "cmgr-001",
    "auditor": "aud-001",
}

UNKNOWN_ROLE = "FleetSupervisor"

# Well formed UUIDs that are never minted by any test, used to probe the
# existence checks.
ABSENT_UUIDS = tuple(
    "00000000-0000-4000-8000-{:012d}".format(n) for n in range(1, 71)
)

# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

RISK_TIER_CRITICAL = "CRITICAL"
RISK_TIER_ELEVATED = "ELEVATED"
RISK_TIER_STANDARD = "STANDARD"

RISK_TIER_CRITICAL_MIN_RATE = 3.000
RISK_TIER_ELEVATED_MIN_RATE = 1.500

STAFFING_POSTURE_CRITICAL = "CRITICAL"
STAFFING_POSTURE_STRAINED = "STRAINED"
STAFFING_POSTURE_OK = "OK"

# Suspended-to-active ratio thresholds, held as exact rationals.
STAFFING_CRITICAL_RATIO = (1, 2)
STAFFING_STRAINED_RATIO = (1, 5)

TENURE_UNDER_12_MONTHS = "UNDER_12_MONTHS"
TENURE_MONTHS_12_TO_36 = "MONTHS_12_TO_36"
TENURE_OVER_36_MONTHS = "OVER_36_MONTHS"

TENURE_MONTHS_12_TO_36_MIN_DAYS = 365
TENURE_OVER_36_MONTHS_MIN_DAYS = 1096

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

DRIVER_STATUS_ACTIVE = "ACTIVE"
DRIVER_STATUS_SUSPENDED_PENDING_ACTION = "SUSPENDED_PENDING_ACTION"
DRIVER_STATUS_RETRAINING_REQUIRED = "RETRAINING_REQUIRED"
DRIVER_STATUS_TERMINATED = "TERMINATED"

ACTION_TIER_NONE = "NONE"
ACTION_TIER_COACHING = "COACHING"
ACTION_TIER_RETRAINING = "RETRAINING"
ACTION_TIER_SUSPENSION = "SUSPENSION"
ACTION_TIER_TERMINATION_REVIEW = "TERMINATION_REVIEW"

# Points contributed by one preventable crash, before decay.
SEVERITY_POINTS = {
    "MINOR": 2,
    "MODERATE": 4,
    "SEVERE": 8,
    "CATASTROPHIC": 12,
}

# Decay multipliers by age of the crash in whole days.
DECAY_FULL = 1.0
DECAY_HALF = 0.5
DECAY_ZERO = 0.0
DECAY_HALF_MIN_DAYS = 365
DECAY_ZERO_MIN_DAYS = 730

ACTION_TIER_THRESHOLDS = (
    (12.0, ACTION_TIER_TERMINATION_REVIEW),
    (8.0, ACTION_TIER_SUSPENSION),
    (4.0, ACTION_TIER_RETRAINING),
    (1.0, ACTION_TIER_COACHING),
)

RETRAINING_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
RETRAINING_STATUS_PENDING = "PENDING"
RETRAINING_STATUS_COMPLETED = "COMPLETED"

# ---------------------------------------------------------------------------
# Crash
# ---------------------------------------------------------------------------

SEVERITY_MINOR = "MINOR"
SEVERITY_MODERATE = "MODERATE"
SEVERITY_SEVERE = "SEVERE"
SEVERITY_CATASTROPHIC = "CATASTROPHIC"

ROUTE_CLASS_LOCAL = "LOCAL"
ROUTE_CLASS_REGIONAL = "REGIONAL"
ROUTE_CLASS_LINEHAUL = "LINEHAUL"
ALL_ROUTE_CLASSES = (ROUTE_CLASS_LOCAL, ROUTE_CLASS_REGIONAL, ROUTE_CLASS_LINEHAUL)

TOW_REASON_NONE = "NONE"
TOW_REASON_CONVENIENCE = "CONVENIENCE"
TOW_REASON_DISABLING_DAMAGE = "DISABLING_DAMAGE"

REPORTING_STATUS_PENDING_FILING = "PENDING_FILING"
REPORTING_STATUS_FILED = "FILED"
REPORTING_STATUS_LATE_FILED = "LATE_FILED"
REPORTING_STATUS_NOT_REQUIRED = "NOT_REQUIRED"

PREVENTABILITY_REPORTED = "REPORTED"
PREVENTABILITY_UNDER_REVIEW = "UNDER_REVIEW"
PREVENTABILITY_PREVENTABLE = "PREVENTABLE"
PREVENTABILITY_NON_PREVENTABLE = "NON_PREVENTABLE"

# Recordability codes in their pinned emission order.
RECORDABILITY_CODE_ORDER = (
    "FATALITY",
    "INJURY_TRANSPORTED",
    "DISABLING_TOW",
    "HAZMAT_RELEASE",
)

REPORT_WINDOW_HOURS_HAZMAT = 24
REPORT_WINDOW_HOURS_STANDARD = 72

EVIDENCE_POSTURE_COMPLETE = "COMPLETE"
EVIDENCE_POSTURE_PARTIAL = "PARTIAL"
EVIDENCE_POSTURE_COMPROMISED = "COMPROMISED"

# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

EVIDENCE_TELEMATICS = "TELEMATICS_SNAPSHOT"
EVIDENCE_FORWARD_CAMERA = "FORWARD_CAMERA"
EVIDENCE_DRIVER_FACING_CAMERA = "DRIVER_FACING_CAMERA"
EVIDENCE_ELD_LOG = "ELD_LOG"
EVIDENCE_SCENE_PHOTO = "SCENE_PHOTO"

ALL_EVIDENCE_KINDS = (
    EVIDENCE_TELEMATICS,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_DRIVER_FACING_CAMERA,
    EVIDENCE_ELD_LOG,
    EVIDENCE_SCENE_PHOTO,
)

# Evidence kinds a crash of each severity must have preserved and bracketing.
REQUIRED_EVIDENCE_KINDS = {
    SEVERITY_MINOR: (EVIDENCE_TELEMATICS,),
    SEVERITY_MODERATE: (EVIDENCE_TELEMATICS, EVIDENCE_FORWARD_CAMERA),
    SEVERITY_SEVERE: (EVIDENCE_TELEMATICS, EVIDENCE_FORWARD_CAMERA, EVIDENCE_ELD_LOG),
    SEVERITY_CATASTROPHIC: (
        EVIDENCE_TELEMATICS,
        EVIDENCE_FORWARD_CAMERA,
        EVIDENCE_ELD_LOG,
    ),
}

PRESERVATION_REQUESTED = "REQUESTED"
PRESERVATION_PRESERVED = "PRESERVED"
PRESERVATION_PURGED_BEFORE_HOLD = "PURGED_BEFORE_HOLD"
PRESERVATION_RELEASED = "RELEASED"

# ---------------------------------------------------------------------------
# Review case and committee ballots
# ---------------------------------------------------------------------------

REVIEW_STATE_DRAFT = "DRAFT"
REVIEW_STATE_DELIBERATION = "DELIBERATION"
REVIEW_STATE_DECIDED = "DECIDED"
REVIEW_STATE_CLOSED_FINAL = "CLOSED_FINAL"

DETERMINATION_PENDING = "PENDING"
DETERMINATION_PREVENTABLE = "PREVENTABLE"
DETERMINATION_NON_PREVENTABLE = "NON_PREVENTABLE"

DECISION_BASIS_NOT_APPLICABLE = "NOT_APPLICABLE"
DECISION_BASIS_UNWEIGHTED_MAJORITY = "UNWEIGHTED_MAJORITY"
DECISION_BASIS_WEIGHTED_CRITERIA = "WEIGHTED_CRITERIA"

# Ballot criteria and their declared weights.
CRITERION_WEIGHTS = {
    "speed_and_spacing": 0.30,
    "hazard_recognition": 0.25,
    "regulatory_compliance": 0.20,
    "vehicle_condition_precheck": 0.15,
    "evasive_action": 0.10,
}

CRITERION_ORDER = (
    "speed_and_spacing",
    "hazard_recognition",
    "regulatory_compliance",
    "vehicle_condition_precheck",
    "evasive_action",
)

MECHANICAL_CRITERION = "vehicle_condition_precheck"

# Denominator used when the mechanical criterion is renormalised away.
WEIGHT_DENOMINATOR_FULL = 1.00
WEIGHT_DENOMINATOR_NO_MECHANICAL = 0.85

CRITERION_SCORE_MIN = 0
CRITERION_SCORE_MAX = 4

WEIGHTED_PREVENTABLE_THRESHOLD = 2.50

COMMITTEE_QUORUM = 3

BALLOT_DISPOSITION_PREVENTABLE = "PREVENTABLE"
BALLOT_DISPOSITION_NON_PREVENTABLE = "NON_PREVENTABLE"
BALLOT_DISPOSITION_ABSTAIN = "ABSTAIN"

APPEAL_CODE_NEW_EVIDENCE = "NEW_EVIDENCE"
APPEAL_CODE_PROCEDURAL = "PROCEDURAL"
APPEAL_CODE_CRITERIA_MISAPPLICATION = "CRITERIA_MISAPPLICATION"

APPEAL_WINDOW_DAYS = 14
APPEAL_MAX_ROUNDS = 1

# ---------------------------------------------------------------------------
# Disciplinary action
# ---------------------------------------------------------------------------

ACTION_TYPE_COACHING = "COACHING"
ACTION_TYPE_RETRAINING = "RETRAINING"
ACTION_TYPE_SUSPENSION = "SUSPENSION"
ACTION_TYPE_TERMINATION_RECOMMENDATION = "TERMINATION_RECOMMENDATION"

ACTION_STATE_ISSUED = "ISSUED"
ACTION_STATE_COMPLETED = "COMPLETED"
ACTION_STATE_VOIDED = "VOIDED"

SUSPENSION_BUFFER_HOURS = 24

EMPLOYMENT_DECISION_CONTINUE = "CONTINUE"
EMPLOYMENT_DECISION_SEPARATE = "SEPARATE"

# ---------------------------------------------------------------------------
# Claim, litigation risk and reserves
# ---------------------------------------------------------------------------

CLAIM_HANDLING_SETUP = "SETUP"
CLAIM_HANDLING_NEGOTIATION = "NEGOTIATION"
CLAIM_HANDLING_SETTLEMENT_COMPLETE = "SETTLEMENT_COMPLETE"
CLAIM_HANDLING_CLOSED = "CLOSED"

RESERVE_STATUS_PROVISIONAL = "PROVISIONAL"
RESERVE_STATUS_REVISED = "REVISED"
RESERVE_STATUS_FINAL = "FINAL"

COUNSEL_TYPE_NONE = "NONE"
COUNSEL_TYPE_PANEL = "PANEL"
COUNSEL_TYPE_IN_HOUSE = "IN_HOUSE"
COUNSEL_TYPE_LEAD_TRIAL = "LEAD_TRIAL"

# Litigation risk score contributions.
EMPLOYMENT_DECISION_PENDING = "PENDING"

RISK_PREVENTABILITY_POINTS = {
    PREVENTABILITY_PREVENTABLE: 30,
    PREVENTABILITY_UNDER_REVIEW: 10,
    PREVENTABILITY_REPORTED: 5,
    PREVENTABILITY_NON_PREVENTABLE: 0,
}

RISK_POSTURE_POINTS = {
    EVIDENCE_POSTURE_COMPROMISED: 25,
    EVIDENCE_POSTURE_PARTIAL: 5,
    EVIDENCE_POSTURE_COMPLETE: 0,
}

RISK_FATALITY_POINTS = 20
RISK_HAZMAT_POINTS = 10
RISK_GREEN_DRIVER_POINTS = 5
RISK_REPRESENTED_BI_POINTS = 15
RISK_SCORE_CAP = 100

COUNSEL_REQUIRED_THRESHOLD = 55

# Reserve multiplier bands keyed by the inclusive lower bound of the score.
RESERVE_MULTIPLIER_BANDS = (
    (80, 1.60),
    (55, 1.35),
    (25, 1.15),
    (0, 1.00),
)

# Provisional gross exposure inputs, in cents.
SEVERITY_RESERVE_BASE_CENTS = {
    SEVERITY_MINOR: 500_000,
    SEVERITY_MODERATE: 2_500_000,
    SEVERITY_SEVERE: 12_000_000,
    SEVERITY_CATASTROPHIC: 45_000_000,
}

INJURY_TRANSPORTED_UNIT_CENTS = 3_500_000
FATALITY_UNIT_CENTS = 90_000_000

COUNSEL_EXPENSE_RATE = 0.18
RESERVE_FLOOR_CENTS = 250_000

RESERVE_BASIS_PROVISIONAL_REFRESH = "PROVISIONAL_REFRESH"
RESERVE_BASIS_DEMAND_BASED = "DEMAND_BASED"

# ---------------------------------------------------------------------------
# Policy tower, demands and negotiation
# ---------------------------------------------------------------------------

LAYER_KIND_SIR = "SIR"
LAYER_KIND_PRIMARY = "PRIMARY"
LAYER_KIND_EXCESS = "EXCESS"

DEMAND_STATE_DEMANDED = "DEMANDED"
DEMAND_STATE_OFFER_OUTSTANDING = "OFFER_OUTSTANDING"
DEMAND_STATE_COUNTER_OUTSTANDING = "COUNTER_OUTSTANDING"
DEMAND_STATE_SETTLED = "SETTLED"
DEMAND_STATE_CLOSED_PAID = "CLOSED_PAID"

CLAIMANT_TYPE_PROPERTY = "THIRD_PARTY_PROPERTY"
CLAIMANT_TYPE_BODILY_INJURY = "THIRD_PARTY_BODILY_INJURY"

ROUND_OUTCOME_OPEN = "OPEN"
ROUND_OUTCOME_COUNTERED = "COUNTERED"
ROUND_OUTCOME_ACCEPTED = "ACCEPTED"
ROUND_OUTCOME_SUPERSEDED = "SUPERSEDED"

# Allocated loss adjustment expense rates keyed on indemnity alone.
ALAE_RATE_BANDS = (
    (25_000_000, 0.15),
    (5_000_000, 0.12),
    (0, 0.08),
)

RESCISSION_WINDOW_HOURS = 168

# ---------------------------------------------------------------------------
# Subrogation
# ---------------------------------------------------------------------------

SUBROGATION_STATE_DRAFT = "DRAFT"
SUBROGATION_STATE_READY_TO_PURSUE = "READY_TO_PURSUE"
SUBROGATION_STATE_RECOVERED = "RECOVERED"
SUBROGATION_STATE_DENIED = "DENIED"
SUBROGATION_STATE_WRITTEN_OFF = "WRITTEN_OFF"

SUBROGATION_RESOLUTION_RECOVERED = "RECOVERED"
SUBROGATION_RESOLUTION_DENIED = "DENIED"
SUBROGATION_RESOLUTION_WRITTEN_OFF = "WRITTEN_OFF"

AT_FAULT_PERCENTAGE_MIN = 1
AT_FAULT_PERCENTAGE_MAX = 100

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

ANALYTICS_WINDOW_DAYS = 365

ANALYTICS_BASIS_AS_DETERMINED = "AS_DETERMINED"
ANALYTICS_BASIS_AS_REPORTED = "AS_REPORTED"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Common field groups
# ---------------------------------------------------------------------------

VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")

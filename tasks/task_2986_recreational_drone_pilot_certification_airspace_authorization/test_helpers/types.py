"""Entity type definitions and status vocabularies for the Drone Operations Service.

Every enumeration below mirrors a member set declared in the PRD. Status values,
role spellings and enum members are copied exactly as the PRD spells them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1 - spelled exactly as they must appear in X-User-Role)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    PILOT = "Pilot"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AIRSPACE_AUTHORITY = "AirspaceAuthority"
    SAFETY_REVIEWER = "SafetyReviewer"
    WAIVER_APPROVER = "WaiverApprover"
    INVESTIGATION_OFFICER = "InvestigationOfficer"


# ---------------------------------------------------------------------------
# Pilot
# ---------------------------------------------------------------------------


class PilotStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    KNOWLEDGE_PENDING = "KNOWLEDGE_PENDING"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OperatorCategory(str, Enum):
    RECREATIONAL = "RECREATIONAL"
    COMMERCIAL = "COMMERCIAL"


class CurrencyBasis(str, Enum):
    RECREATIONAL_BASIS = "RECREATIONAL_BASIS"
    COMMERCIAL_BASIS = "COMMERCIAL_BASIS"


# ---------------------------------------------------------------------------
# Knowledge test / certification
# ---------------------------------------------------------------------------


class KnowledgeTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TestCode(str, Enum):
    # The leading `Test` in the name is domain vocabulary (a knowledge test code),
    # not a pytest class; this keeps the collector from trying to gather it.
    __test__ = False

    TRUST_RECREATIONAL = "TRUST_RECREATIONAL"
    PART107_COMMERCIAL = "PART107_COMMERCIAL"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Aircraft / remote-ID module
# ---------------------------------------------------------------------------


class RegistrationStatus(str, Enum):
    PENDING_REGISTRATION = "PENDING_REGISTRATION"
    REGISTERED = "REGISTERED"
    GROUNDED = "GROUNDED"
    DEREGISTERED = "DEREGISTERED"


class SystemGroundingReason(str, Enum):
    """The two grounding_reason values the service itself writes."""

    OWNER_SUSPENDED = "OWNER_SUSPENDED"
    OWNER_REVOKED = "OWNER_REVOKED"


class ModuleStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    EXPIRED = "EXPIRED"


class BroadcastProtocol(str, Enum):
    WIFI_NAN = "WIFI_NAN"
    BLUETOOTH_LE = "BLUETOOTH_LE"


class ModuleOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Airspace
# ---------------------------------------------------------------------------


class ZoneClassCode(str, Enum):
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    G = "G"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Waiver / safety case
# ---------------------------------------------------------------------------


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CLEARED = "CLEARED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class WaiverType(str, Enum):
    OVER_PEOPLE = "OVER_PEOPLE"
    NIGHT = "NIGHT"
    BVLOS = "BVLOS"


class SafetyCaseReviewStatus(str, Enum):
    PENDING = "PENDING"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CLEARED = "CLEARED"


class AirRiskClass(str, Enum):
    ARC_A = "ARC_A"
    ARC_B = "ARC_B"
    ARC_C = "ARC_C"
    ARC_D = "ARC_D"


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------


class CoverageStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"
    EXPIRED = "EXPIRED"


class PolicyOutcome(str, Enum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Flight / preflight check
# ---------------------------------------------------------------------------


class FlightStatus(str, Enum):
    PLANNED = "PLANNED"
    PREFLIGHT_CLEARED = "PREFLIGHT_CLEARED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvestigationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OperationCategory(str, Enum):
    RECREATIONAL = "RECREATIONAL"
    COMMERCIAL = "COMMERCIAL"


class SystemCancellationReason(str, Enum):
    """The two cancellation_reason values written by the cascades."""

    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    COVERAGE_INSUFFICIENT = "COVERAGE_INSUFFICIENT"


class PreflightResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class BlockingFinding(str, Enum):
    AIRCRAFT_NOT_REGISTERED = "AIRCRAFT_NOT_REGISTERED"
    AUTHORIZATION_NOT_APPROVED = "AUTHORIZATION_NOT_APPROVED"
    CURRENCY_LAPSED = "CURRENCY_LAPSED"
    REMOTE_ID_INVALID = "REMOTE_ID_INVALID"
    TFR_TOTAL_BAN = "TFR_TOTAL_BAN"
    TFR_UNACKNOWLEDGED = "TFR_UNACKNOWLEDGED"
    WAIVER_MISSING = "WAIVER_MISSING"


# ---------------------------------------------------------------------------
# Accident report
# ---------------------------------------------------------------------------


class ReportStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class InjuryLevel(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


# ---------------------------------------------------------------------------
# Entity representations
#
# Every persisted resource carries `id` and `created_at`, and almost every one
# additionally carries `updated_at` and `version`. `PreflightCheck` is the single
# exception: it is an immutable audit artefact carrying only `id` and
# `created_at`, so neither `updated_at` nor `version` appears in its shape.
# ---------------------------------------------------------------------------


class Pilot(TypedDict):
    id: str
    full_name: str
    email: str
    operator_category: str
    status: str
    certified_at: Optional[str]
    currency_expires_at: Optional[str]
    currency_basis: str
    last_completed_flight_end: Optional[str]
    suspension_reason: Optional[str]
    risk_score: int
    knowledge_attempt_count: int
    open_waiver_count: int
    created_at: str
    updated_at: str
    version: int


class KnowledgeTest(TypedDict):
    id: str
    pilot_id: str
    test_code: str
    scheduled_at: str
    attempt_number: int
    status: str
    raw_score: Optional[int]
    passed: Optional[bool]
    graded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    pilot_id: str
    originating_test_id: str
    supersedes_certification_id: Optional[str]
    certificate_number: str
    category: str
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    owner_pilot_id: str
    model: str
    serial_number: str
    takeoff_weight_g: int
    max_altitude_ft: int
    remote_id_required: bool
    registration_status: str
    registration_number: Optional[str]
    grounding_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemoteIdModule(TypedDict):
    id: str
    aircraft_id: str
    module_serial: str
    broadcast_protocol: str
    firmware_version: str
    broadcast_sample_ref: Optional[str]
    status: str
    verified_at: Optional[str]
    verified_until: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AirspaceZone(TypedDict):
    id: str
    designator: str
    class_code: str
    class_ceiling_ft: int
    requires_authorization: bool
    max_concurrent_authorizations: int
    structure_relief_eligible: bool
    reserved_slot_count: int
    created_at: str
    updated_at: str
    version: int


class TemporaryFlightRestriction(TypedDict):
    id: str
    zone_id: str
    reason: str
    effective_from: str
    effective_until: str
    max_permitted_altitude_ft: Optional[int]
    status: str
    published_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class AirspaceAuthorization(TypedDict):
    id: str
    pilot_id: str
    aircraft_id: str
    zone_id: str
    waiver_id: Optional[str]
    requested_ceiling_ft: int
    granted_ceiling_ft: Optional[int]
    window_start: str
    window_end: str
    status: str
    approved_by_user_id: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    pilot_id: str
    aircraft_id: str
    waiver_type: str
    requested_ceiling_ft: int
    operation_description: str
    status: str
    revision_round: int
    granted_ceiling_ft: Optional[int]
    valid_until: Optional[str]
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyCase(TypedDict):
    id: str
    waiver_id: str
    mitigation_summary: str
    ground_risk_class: int
    air_risk_class: str
    contingency_procedures: str
    sail_level: int
    review_status: str
    reviewer_findings: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    pilot_id: str
    insurer_name: str
    policy_number: str
    coverage_limit_cents: int
    deductible_cents: int
    effective_from: str
    effective_until: str
    indemnification_clause_accepted: bool
    coverage_status: str
    open_reserved_cents_total: int
    settled_cents_total: int
    remaining_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    pilot_id: str
    aircraft_id: str
    zone_id: str
    authorization_id: Optional[str]
    waiver_id: Optional[str]
    covering_policy_id: Optional[str]
    operation_category: str
    planned_start: str
    planned_end: str
    planned_max_altitude_ft: int
    launch_latitude: float
    launch_longitude: float
    over_people: bool
    night_operation: bool
    beyond_visual_line_of_sight: bool
    status: str
    investigation_status: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    logged_minutes: int
    max_altitude_reached_ft: Optional[int]
    altitude_exceedance: bool
    incident_occurred: Optional[bool]
    incident_summary: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreflightCheck(TypedDict):
    """Immutable audit artefact: only `id` and `created_at`, no `updated_at`, no `version`."""

    id: str
    flight_id: str
    checked_at: str
    result: str
    blocking_findings: List[str]
    active_tfr_ids: List[str]
    acknowledged_tfr_ids: List[str]
    airspace_class_code: str
    effective_ceiling_ft: int
    created_at: str


class AccidentReport(TypedDict):
    id: str
    flight_id: str
    policy_id: Optional[str]
    occurred_at: str
    injury_level: str
    reported_property_damage_cents: int
    narrative: str
    status: str
    remediation_round: int
    remediation_findings: Optional[str]
    reserved_cents: int
    damage_line_items: Optional[List[Dict[str, Any]]]
    settlement_cents: Optional[int]
    probable_cause: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CurrencyProjection(TypedDict):
    projected_expires_at: Optional[str]
    basis_applied: str
    base_expiry: Optional[str]
    recency_expiry: Optional[str]
    days_remaining: int
    lapse_due: bool


class FlightSummary(TypedDict):
    completed_flight_count: int
    total_logged_minutes: int
    max_altitude_reached_ft: int
    incident_flight_count: int
    exceedance_flight_count: int
    average_duration_minutes: float
    window_start: str
    window_end: str


class ClockState(TypedDict):
    current_utc: str
    previous_utc: str

"""Domain types: entity TypedDicts, status enums, role enum.

All ten addressable resources carry `id`, `created_at`, `updated_at` and
`version` (PRD 2.5).  Embedded objects (proxy credential grants, video session
records, documented contraindications) are not addressable and carry none of
those four properties.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ED_PHYSICIAN = "EdPhysician"
    NEUROLOGIST = "Neurologist"
    TRANSFER_COORDINATOR = "TransferCoordinator"
    QUALITY_ABSTRACTOR = "QualityAbstractor"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    CERTIFICATION_REVIEWER = "CertificationReviewer"


ALL_ROLE_NAMES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enums (PRD 3.1 - 3.9)
# ---------------------------------------------------------------------------
class FacilityType(str, Enum):
    HUB_PRIMARY = "HUB_PRIMARY"
    SPOKE = "SPOKE"
    THROMBECTOMY_CAPABLE = "THROMBECTOMY_CAPABLE"


class CertificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class EquipmentReadinessPosture(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class EmsRoutingPosture(str, Enum):
    ROUTINE = "ROUTINE"
    DIVERT_ADVISORY = "DIVERT_ADVISORY"
    BYPASS = "BYPASS"


class ReadinessComponent(str, Enum):
    CT_SCANNER = "CT_SCANNER"
    VIDEO_CART = "VIDEO_CART"


class ReadinessResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CoverageTier(str, Enum):
    TIER_1_FULL = "TIER_1_FULL"
    TIER_2_CONSULT_ONLY = "TIER_2_CONSULT_ONLY"


class PrivilegeScope(str, Enum):
    CONSULT_ONLY = "CONSULT_ONLY"
    CONSULT_AND_THROMBOLYSIS = "CONSULT_AND_THROMBOLYSIS"


class ProxyCredentialStatus(str, Enum):
    GRANTED = "GRANTED"
    EXPIRED = "EXPIRED"


class OnCallState(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_CALL = "ON_CALL"
    IN_CONSULT = "IN_CONSULT"
    UNAVAILABLE = "UNAVAILABLE"


class LkwPrecision(str, Enum):
    EXACT = "EXACT"
    ESTIMATED = "ESTIMATED"
    UNKNOWN_WAKE_UP = "UNKNOWN_WAKE_UP"


class ArrivalMode(str, Enum):
    EMS = "EMS"
    WALK_IN = "WALK_IN"
    INTERFACILITY_TRANSFER = "INTERFACILITY_TRANSFER"


class ThrombolyticWindowClass(str, Enum):
    WITHIN_3H = "WITHIN_3H"
    WITHIN_4_5H = "WITHIN_4_5H"
    EXTENDED_UNKNOWN = "EXTENDED_UNKNOWN"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"


class CaseStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    IMAGING_COMPLETE = "IMAGING_COMPLETE"
    CONSULT_IN_PROGRESS = "CONSULT_IN_PROGRESS"
    ELIGIBILITY_DETERMINED = "ELIGIBILITY_DETERMINED"
    THROMBOLYSIS_ADMINISTERED = "THROMBOLYSIS_ADMINISTERED"
    TRANSFER_INITIATED = "TRANSFER_INITIATED"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class CaseDisposition(str, Enum):
    PENDING = "PENDING"
    TREATED_LOCAL = "TREATED_LOCAL"
    DRIP_AND_SHIP = "DRIP_AND_SHIP"
    TRANSFER_ONLY = "TRANSFER_ONLY"
    NO_TREATMENT = "NO_TREATMENT"


class ThrombolyticAgent(str, Enum):
    ALTEPLASE = "ALTEPLASE"
    TENECTEPLASE = "TENECTEPLASE"


class ConsultStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    ESCALATED_UNFILLED = "ESCALATED_UNFILLED"
    CANCELLED = "CANCELLED"


class VideoQuality(str, Enum):
    HD = "HD"
    SD = "SD"
    AUDIO_ONLY = "AUDIO_ONLY"


class ConsultRecommendation(str, Enum):
    THROMBOLYSIS = "THROMBOLYSIS"
    TRANSFER_THROMBECTOMY = "TRANSFER_THROMBECTOMY"
    BOTH_DRIP_AND_SHIP = "BOTH_DRIP_AND_SHIP"
    NO_INTERVENTION = "NO_INTERVENTION"


class DocumentationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    DOCUMENTED = "DOCUMENTED"
    AMENDED = "AMENDED"


class DeterminationStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE_WITH_RELATIVE_OVERRIDE = "ELIGIBLE_WITH_RELATIVE_OVERRIDE"


class ContraindicationSeverity(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"


class TransferMode(str, Enum):
    DRIP_AND_SHIP = "DRIP_AND_SHIP"
    TRANSFER_ONLY = "TRANSFER_ONLY"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    HANDOFF_COMPLETE = "HANDOFF_COMPLETE"
    CANCELLED = "CANCELLED"


class DeviationType(str, Enum):
    DTI_EXCEEDED = "DTI_EXCEEDED"
    DTN_EXCEEDED = "DTN_EXCEEDED"
    DIDO_EXCEEDED = "DIDO_EXCEEDED"
    CONSULT_UNFILLED = "CONSULT_UNFILLED"
    MISSING_CONTRAINDICATION_DOC = "MISSING_CONTRAINDICATION_DOC"
    INVALID_VIDEO_SESSION = "INVALID_VIDEO_SESSION"
    LKW_WINDOW_VIOLATION = "LKW_WINDOW_VIOLATION"


class DeviationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SENTINEL = "SENTINEL"


class DeviationSource(str, Enum):
    SYSTEM_DETECTED = "SYSTEM_DETECTED"
    MANUAL = "MANUAL"


class DeviationStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class DeviationOutcome(str, Enum):
    SUBSTANTIATE = "SUBSTANTIATE"
    DISMISS = "DISMISS"


class MeasureCode(str, Enum):
    STK_4_THROMBOLYTIC_THERAPY = "STK_4_THROMBOLYTIC_THERAPY"
    STK_DTI_45 = "STK_DTI_45"
    STK_DTN_60 = "STK_DTN_60"
    STK_TELESTROKE_RESPONSE = "STK_TELESTROKE_RESPONSE"


class AbstractionVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class AbstractionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    RETRACTED = "RETRACTED"


class ExclusionReason(str, Enum):
    NONE = "NONE"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    ABORTED_CASE = "ABORTED_CASE"
    DOCUMENTED_ABSOLUTE_CONTRAINDICATION = "DOCUMENTED_ABSOLUTE_CONTRAINDICATION"
    TRANSFER_ONLY = "TRANSFER_ONLY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ReportDecision(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"


class RateVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


# ---------------------------------------------------------------------------
# Embedded objects (PRD 2.5) - no id, no updated_at, no version
# ---------------------------------------------------------------------------
class ProxyCredentialGrant(TypedDict):
    neurologist_id: str
    privilege_scope: str
    expires_at: str
    status: str
    granted_at: str


class VideoSessionRecord(TypedDict):
    started_at: str
    ended_at: Optional[str]
    video_quality: str
    disconnect_count: int
    duration_seconds: int
    session_valid: bool


class DocumentedContraindication(TypedDict):
    code: str
    severity: str
    documented_evidence: Optional[str]
    recorded_by_user_id: str
    recorded_at: str


# ---------------------------------------------------------------------------
# Addressable resources (PRD 2.5) - all carry the four common properties
# ---------------------------------------------------------------------------
class StrokeCenter(TypedDict):
    id: str
    name: str
    facility_type: str
    state_code: str
    ems_region_code: str
    certification_status: str
    ct_scanner_ready: bool
    video_cart_ready: bool
    equipment_readiness_posture: str
    open_case_count: int
    ems_routing_posture: str
    public_dtn_compliance_pct: Optional[float]
    public_report_published_at: Optional[str]
    suspension_reason: Optional[str]
    consecutive_denied_report_count: int
    created_at: str
    updated_at: str
    version: int


class SpokeAgreement(TypedDict):
    id: str
    hub_center_id: str
    spoke_center_id: str
    coverage_tier: str
    max_concurrent_consults: int
    effective_from: str
    effective_until: str
    status: str
    proxy_credentials: List[ProxyCredentialGrant]
    active_consult_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Neurologist(TypedDict):
    id: str
    full_name: str
    home_center_id: str
    licensed_state_codes: List[str]
    board_certified: bool
    roster_rank: int
    concurrent_consult_limit: int
    on_call_state: str
    active_consult_count: int
    last_consult_completed_at: Optional[str]
    completed_consult_count: int
    created_at: str
    updated_at: str
    version: int


class CodeStrokeCase(TypedDict):
    id: str
    center_id: str
    patient_ref: str
    door_at: str
    lkw_precision: str
    last_known_well_at: Optional[str]
    arrival_mode: str
    activation_at: str
    imaging_at: Optional[str]
    needle_at: Optional[str]
    door_to_imaging_minutes: Optional[int]
    door_to_needle_minutes: Optional[int]
    lkw_to_needle_minutes: Optional[int]
    thrombolytic_window_class: Optional[str]
    status: str
    disposition: str
    activated_by_user_id: str
    thrombolytic_agent: Optional[str]
    thrombolytic_dose_mg: Optional[float]
    abort_reason: Optional[str]
    deviation_count: int
    created_at: str
    updated_at: str
    version: int


class TelestrokeConsult(TypedDict):
    id: str
    case_id: str
    agreement_id: str
    assigned_neurologist_id: Optional[str]
    requested_privilege_scope: str
    status: str
    requested_at: str
    assigned_at: Optional[str]
    accepted_at: Optional[str]
    completed_at: Optional[str]
    response_latency_seconds: Optional[int]
    decline_count: int
    routing_attempt_count: int
    excluded_neurologist_ids: List[str]
    video_sessions: List[VideoSessionRecord]
    valid_video_session_count: int
    recommendation: Optional[str]
    nihss_score: Optional[int]
    last_decline_reason: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ThrombolyticChecklist(TypedDict):
    id: str
    case_id: str
    overridden_by_neurologist_id: Optional[str]
    documentation_status: str
    determination_status: str
    confirmed_inclusion_item_codes: List[str]
    confirmed_inclusion_item_count: int
    contraindications: List[DocumentedContraindication]
    absolute_contraindication_count: int
    relative_contraindication_count: int
    screening_eligibility_score: float
    attested_eligibility_score: Optional[float]
    override_justification: Optional[str]
    determined_at: Optional[str]
    amendment_count: int
    last_amendment_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferDecision(TypedDict):
    id: str
    case_id: str
    origin_center_id: str
    destination_center_id: str
    mode: str
    transport_eta_minutes: int
    status: str
    destination_posture_at_proposal: str
    congestion_factor: float
    adjusted_transport_minutes: int
    projected_door_in_door_out_minutes: int
    door_in_door_out_minutes: Optional[int]
    handoff_packet_items: List[str]
    handoff_packet_complete: bool
    proposed_at: str
    accepted_at: Optional[str]
    handoff_completed_at: Optional[str]
    decline_reason: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtocolDeviation(TypedDict):
    id: str
    case_id: str
    deviation_type: str
    severity: str
    narrative: str
    source: str
    status: str
    opened_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_round: int
    info_request: Optional[str]
    additional_info: Optional[str]
    debrief_completed: bool
    debrief_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityMeasureAbstraction(TypedDict):
    id: str
    case_id: str
    report_id: Optional[str]
    measure_code: str
    variant: str
    numerator_flag: bool
    denominator_included: bool
    exclusion_reason: str
    status: str
    abstracted_by_user_id: str
    attested_by_user_id: Optional[str]
    attestation_note: Optional[str]
    retraction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationReport(TypedDict):
    id: str
    center_id: str
    period_start: str
    period_end: str
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    included_abstraction_count: int
    closed_case_count_in_period: int
    dtn_60_compliance_pct: float
    dti_45_compliance_pct: float
    telestroke_response_compliance_pct: float
    mean_dtn_excess_pct: Optional[float]
    rate_variant: str
    substantiated_major_count: int
    substantiated_sentinel_count: int
    composite_certification_score: float
    decision: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    published_at: Optional[str]
    superseded_by_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int

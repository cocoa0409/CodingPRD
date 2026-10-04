"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class CarrierClass(str, Enum):
    I = "I"
    II = "II"
    III = "III"


class RevenueAdequacyStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"


class ComplianceStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"


class Finding(str, Enum):
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"


class RateComplaintStatus(str, Enum):
    FILED = "FILED"
    EVIDENTIARY_PHASE = "EVIDENTIARY_PHASE"
    DECIDED = "DECIDED"
    REOPENED = "REOPENED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class MarketDominance(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class DecisionOutcome(str, Enum):
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"
    DISMISSED = "DISMISSED"


class AwardStatus(str, Enum):
    NONE = "NONE"
    GRANTED = "GRANTED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REVERSED = "REVERSED"


class Track(str, Enum):
    THREE_BENCHMARK = "THREE_BENCHMARK"
    SIMPLIFIED_SAC = "SIMPLIFIED_SAC"
    FULL_SAC = "FULL_SAC"


class SubmissionType(str, Enum):
    SAC_STUDY = "SAC_STUDY"
    THREE_BENCHMARK_PACKET = "THREE_BENCHMARK_PACKET"
    REBUTTAL = "REBUTTAL"


class SubmittedByParty(str, Enum):
    SHIPPER = "SHIPPER"
    CARRIER = "CARRIER"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ServiceComplaintStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class IssueType(str, Enum):
    DELAY = "DELAY"
    EMBARGO = "EMBARGO"
    CAR_SUPPLY = "CAR_SUPPLY"
    FAILURE_TO_DELIVER = "FAILURE_TO_DELIVER"


class EsoStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LIFTED = "LIFTED"


class MergerStatus(str, Enum):
    COMMENT_PERIOD = "COMMENT_PERIOD"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    MONITORING = "MONITORING"
    MOOT = "MOOT"


class AbandonmentStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    TRAIL_PENDING = "TRAIL_PENDING"
    TRAIL_CONVERTED = "TRAIL_CONVERTED"
    CONSUMMATED = "CONSUMMATED"


class PublicConvenienceFinding(str, Enum):
    SERVED = "SERVED"
    NOT_SERVED = "NOT_SERVED"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOARD_ADJUDICATOR = "BoardAdjudicator"
    SHIPPER = "Shipper"
    CARRIER_OPERATOR = "CarrierOperator"


class Carrier(TypedDict, total=False):
    id: str
    carrier_code: str
    legal_name: str
    carrier_class: str
    base_route_miles: int
    active_route_miles: int
    abandoned_route_miles: int
    trail_use_route_miles: int
    revenue_adequacy_status: str
    compliance_standing: str
    reparation_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class RevenueAdequacyFinding(TypedDict, total=False):
    id: str
    carrier_id: str
    fiscal_year: int
    operating_revenue_cents: int
    operating_expense_cents: int
    net_investment_cents: int
    current_year_roi_bps: int
    five_year_avg_roi_bps: int
    finding: str
    created_at: str
    updated_at: str
    version: int


class RateComplaint(TypedDict, total=False):
    id: str
    shipper_id: str
    carrier_id: str
    commodity: str
    challenged_rate_cents_per_ton: int
    alleged_variable_cost_cents_per_ton: int
    annual_tons: int
    relief_sought_cents: int
    contested_fiscal_year: int
    track: str
    alleged_rvc_ratio: float
    adjudicated_rvc_ratio: Optional[float]
    market_dominance: str
    status: str
    decision_outcome: Optional[str]
    prescribed_rate_cents_per_ton: Optional[int]
    relief_granted_cents: Optional[int]
    award_granted_cents: int
    award_paid_cents: int
    award_outstanding_cents: int
    award_status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceSubmission(TypedDict, total=False):
    id: str
    rate_complaint_id: str
    submission_type: str
    submitted_by_party: str
    reference_rate_cents_per_ton: int
    verified_variable_cost_cents_per_ton: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceComplaint(TypedDict, total=False):
    id: str
    shipper_id: str
    carrier_id: str
    issue_type: str
    territory_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyServiceOrder(TypedDict, total=False):
    id: str
    carrier_id: str
    service_complaint_id: str
    directive: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MergerApplication(TypedDict, total=False):
    id: str
    acquiring_carrier_id: str
    target_carrier_id: str
    transaction_value_cents: int
    competition_preservation_score: int
    service_reliability_score: int
    shipper_impact_score: int
    public_interest_score: float
    comment_close_at: str
    service_review_hold: bool
    status: str
    conditions_imposed: List[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAssurancePlan(TypedDict, total=False):
    id: str
    merger_application_id: str
    plan_name: str
    commitments: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AbandonmentApplication(TypedDict, total=False):
    id: str
    carrier_id: str
    line_segment_ref: str
    segment_miles: int
    public_convenience_finding: Optional[str]
    status: str
    nitu_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReciprocalSwitchingPetition(TypedDict, total=False):
    id: str
    shipper_id: str
    incumbent_carrier_id: str
    interchange_code: str
    facility_distance_miles: int
    evidence_service_complaint_id: str
    service_start_date: str
    service_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int

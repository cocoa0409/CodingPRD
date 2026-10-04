"""Domain types for the model-law / accreditation / filings API.

Entity TypedDicts, status enums, and the role enum. Every resource carries the
four common properties the contract pins (``id``, ``created_at``, ``updated_at``,
``version``); per-entity fields are declared on top of those. Fields that the
server may legitimately report as null (``published_at`` before publication, the
on-site scoring block before findings are issued, ``latest_rbc_ratio`` before a
filing validates, allocation fields before a call closes) are typed ``Optional``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from typing import TypedDict

# --- Generic aliases ---------------------------------------------------------
# A JSON object as decoded from a response body or handed to a request body.
JsonObject = Dict[str, Any]
JsonList = List[Any]

# The two request headers every authenticated call carries.
Headers = Dict[str, str]

# Query-string parameters for a list endpoint.
Params = Dict[str, Any]

# ``validate_paginated`` hands back the row list and the pagination block together.
PaginatedResult = Tuple[JsonList, JsonObject]

# Identifiers are server-minted UUID strings with no type prefix.
ResourceId = str

# ISO 8601 UTC instants. System timestamps carry three fractional digits;
# clock-sourced domain timestamps render exactly as the logical clock reads.
Instant = str

OptionalId = Optional[ResourceId]


# --- Roles (contract section on access control) ------------------------------
class UserRole(str, Enum):
    ASSOCIATION_STAFF = "AssociationStaff"
    ACTUARY = "Actuary"
    STATE_REGULATOR = "StateRegulator"
    INSURER_USER = "InsurerUser"
    PRODUCER_USER = "ProducerUser"
    REVIEW_TEAM_LEAD = "ReviewTeamLead"


# --- Status enums ------------------------------------------------------------
class ModelActStatus(str, Enum):
    DRAFTING = "DRAFTING"
    EXPOSURE_OPEN = "EXPOSURE_OPEN"
    BALLOTING = "BALLOTING"
    ADOPTED = "ADOPTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ActType(str, Enum):
    MODEL_LAW = "MODEL_LAW"
    MODEL_REGULATION = "MODEL_REGULATION"


class ExposureDraftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Vote(str, Enum):
    YEA = "YEA"
    NAY = "NAY"
    ABSTAIN = "ABSTAIN"


class BallotStatus(str, Enum):
    CAST = "CAST"
    VOID = "VOID"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AdoptionStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED_SIMILAR = "CERTIFIED_SIMILAR"
    CERTIFIED_VARIED = "CERTIFIED_VARIED"
    REJECTED_NOT_SIMILAR = "REJECTED_NOT_SIMILAR"
    SUPERSEDED = "SUPERSEDED"


class VariationClass(str, Enum):
    SUBSTANTIALLY_SIMILAR = "SUBSTANTIALLY_SIMILAR"
    SUBSTANTIVE_VARIATIONS = "SUBSTANTIVE_VARIATIONS"
    NOT_SIMILAR = "NOT_SIMILAR"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    FINAL_PASS = "FINAL_PASS"
    FINAL_FAIL = "FINAL_FAIL"


class ReviewOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_COVERAGE = "AUTO_COVERAGE"


class ProposedOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InsurerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_SUPERVISION = "UNDER_SUPERVISION"


class ActionLevel(str, Enum):
    NONE = "NONE"
    COMPANY_ACTION = "COMPANY_ACTION"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    AUTHORIZED_CONTROL = "AUTHORIZED_CONTROL"
    MANDATORY_CONTROL = "MANDATORY_CONTROL"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    EDITS_FAILED = "EDITS_FAILED"
    SUPERSEDED = "SUPERSEDED"


class PeriodQuarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    ANNUAL = "ANNUAL"


class LicenseClass(str, Enum):
    LIFE = "LIFE"
    HEALTH = "HEALTH"
    PROPERTY_CASUALTY = "PROPERTY_CASUALTY"
    PERSONAL_LINES = "PERSONAL_LINES"


class LicenseStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StandardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# --- Entity TypedDicts -------------------------------------------------------
class ModelAct(TypedDict, total=False):
    id: ResourceId
    model_code: str
    version_label: str
    title: str
    act_type: str
    committee_name: str
    is_core: bool
    status: str
    published_at: Optional[Instant]
    votes_cast: int
    favorable_votes: int
    created_at: Instant
    updated_at: Instant
    version: int


class ExposureDraft(TypedDict, total=False):
    id: ResourceId
    model_act_id: ResourceId
    exposure_number: int
    comment_window_start: Instant
    comment_window_end: Instant
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class MemberBallot(TypedDict, total=False):
    id: ResourceId
    model_act_id: ResourceId
    state_code: str
    vote: str
    status: str
    cast_at: Instant
    created_at: Instant
    updated_at: Instant
    version: int


class State(TypedDict, total=False):
    id: ResourceId
    code: str
    name: str
    accreditation_status: str
    consecutive_fail_count: int
    core_act_coverage_pct: float
    created_at: Instant
    updated_at: Instant
    version: int


class StateAdoption(TypedDict, total=False):
    id: ResourceId
    model_act_id: ResourceId
    state_code: str
    adopted_citation: str
    enacted_on: Instant
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class AccreditationReview(TypedDict, total=False):
    id: ResourceId
    state_id: ResourceId
    period_start: Instant
    period_end: Instant
    team_lead_id: Optional[str]
    self_assessment_compliant: int
    self_assessment_total: int
    desk_score: Optional[float]
    findings_compliant: Optional[int]
    findings_total: Optional[int]
    onsite_score: Optional[float]
    proposed_outcome: Optional[str]
    origin: str
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class Insurer(TypedDict, total=False):
    id: ResourceId
    naic_code: str
    name: str
    domicile_state_code: str
    status: str
    latest_rbc_ratio: Optional[float]
    latest_action_level: Optional[str]
    created_at: Instant
    updated_at: Instant
    version: int


class FinancialFiling(TypedDict, total=False):
    id: ResourceId
    insurer_id: ResourceId
    period_year: int
    period_quarter: str
    valuation_standard_code: str
    valuation_standard_version_label: Optional[str]
    reported_surplus_cents: int
    asset_risk_cents: int
    underwriting_risk_cents: int
    other_risk_cents: int
    status: str
    edit_failures: List[str]
    created_at: Instant
    updated_at: Instant
    version: int


class RBCReport(TypedDict, total=False):
    id: ResourceId
    filing_id: ResourceId
    insurer_naic_code: str
    tac_cents: float
    acl_covariance_cents: float
    acl_additive_cents: float
    ratio_covariance: float
    ratio_additive: float
    action_level: str
    created_at: Instant
    updated_at: Instant
    version: int


class Producer(TypedDict, total=False):
    id: ResourceId
    npn: str
    full_name: str
    home_state_code: str
    active_license_count: int
    created_at: Instant
    updated_at: Instant
    version: int


class ProducerLicense(TypedDict, total=False):
    id: ResourceId
    producer_id: ResourceId
    state_code: str
    license_class: str
    effective_from: Instant
    valid_until: Instant
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class MarketConductCall(TypedDict, total=False):
    id: ResourceId
    call_code: str
    topic: str
    lead_state_code: str
    total_cost_cents: int
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class MarketConductResponse(TypedDict, total=False):
    id: ResourceId
    call_id: ResourceId
    insurer_naic_code: str
    direct_premium_cents: int
    complaint_count: int
    exam_priority_score: float
    escalation_flag: bool
    allocated_cost_cents: Optional[int]
    cost_share_excluded: Optional[bool]
    created_at: Instant
    updated_at: Instant
    version: int


class ValuationStandard(TypedDict, total=False):
    id: ResourceId
    code: str
    version_label: str
    guidance_text: str
    author_user_id: str
    status: str
    created_at: Instant
    updated_at: Instant
    version: int

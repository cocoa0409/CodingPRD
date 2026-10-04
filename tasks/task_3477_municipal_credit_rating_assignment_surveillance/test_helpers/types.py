"""Domain types for the Municipal Credit Ratings API.

Entity shapes follow PRD section 2.5: every primary resource carries ``id``,
``created_at``, ``updated_at`` and ``version``; the two append-only records
(``CommitteeVote`` and ``IssuerNotification``) carry only ``id`` and
``created_at`` — "both `updated_at` and `version` are absent from them".

Field names are PRD-exact.  Computed and system fields are marked Optional
where the PRD allows them to be null (for example ``published_at`` before
publication, ``outcome_notch`` before a session completes).
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Status enums (PRD section 3 state vocabularies) ────────────────────────


class UserRole(str, Enum):
    """The seven declared caller roles (PRD section 2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    ISSUER = "Issuer"
    UNDERWRITER = "Underwriter"
    LEAD_ANALYST = "LeadAnalyst"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_MEMBER = "CommitteeMember"
    SURVEILLANCE_OFFICER = "SurveillanceOfficer"


class EngagementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ENGAGED = "ENGAGED"
    INFORMATION_GATHERING = "INFORMATION_GATHERING"
    ANALYSIS = "ANALYSIS"
    COMMITTEE_READY = "COMMITTEE_READY"
    RATING_ASSIGNED = "RATING_ASSIGNED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    ADJOURNED = "ADJOURNED"


class AdjournReason(str, Enum):
    QUORUM_NOT_MET = "QUORUM_NOT_MET"
    NOTCH_DEVIATION_EXCEEDED = "NOTCH_DEVIATION_EXCEEDED"


class RatingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"
    REMANDED = "REMANDED"


class SurveillancePosture(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"


class ObligationStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    SUBMITTED_ON_TIME = "SUBMITTED_ON_TIME"
    SUBMITTED_LATE = "SUBMITTED_LATE"


class CriteriaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class ReviewItemStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    COMPLETED_NO_ACTION = "COMPLETED_NO_ACTION"
    COMPLETED_RATING_ACTION = "COMPLETED_RATING_ACTION"


class Notch(str, Enum):
    """The seven-step rating scale, strongest to weakest (PRD section 2.5)."""

    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"


class Outlook(str, Enum):
    POSITIVE = "POSITIVE"
    STABLE = "STABLE"
    NEGATIVE = "NEGATIVE"
    DEVELOPING = "DEVELOPING"


class CreditType(str, Enum):
    GENERAL_OBLIGATION = "GENERAL_OBLIGATION"
    REVENUE = "REVENUE"
    ENTERPRISE = "ENTERPRISE"


class Solicitation(str, Enum):
    SOLICITED = "SOLICITED"
    UNSOLICITED = "UNSOLICITED"


class IssuerType(str, Enum):
    GENERAL_GOVERNMENT = "GENERAL_GOVERNMENT"
    SPECIAL_DISTRICT = "SPECIAL_DISTRICT"
    ENTERPRISE_PROVIDER = "ENTERPRISE_PROVIDER"


class RatingAction(str, Enum):
    AFFIRM = "AFFIRM"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    WITHDRAW = "WITHDRAW"


class WithdrawReason(str, Enum):
    NON_DISCLOSURE = "NON_DISCLOSURE"
    ISSUER_REQUEST = "ISSUER_REQUEST"
    CRITERIA = "CRITERIA"


class PricingMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class VoteKind(str, Enum):
    VOTE = "VOTE"
    RECUSAL = "RECUSAL"


class ReviewOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    RATING_ACTION = "RATING_ACTION"


class NotchHistoryCause(str, Enum):
    COMMITTEE_ASSIGNMENT = "COMMITTEE_ASSIGNMENT"
    SURVEILLANCE_ACTION = "SURVEILLANCE_ACTION"
    CRITERIA_REVIEW = "CRITERIA_REVIEW"
    REINSTATEMENT = "REINSTATEMENT"


class NotificationEventType(str, Enum):
    ENGAGEMENT_WITHDRAWN = "ENGAGEMENT_WITHDRAWN"
    RATING_ASSIGNED = "RATING_ASSIGNED"
    RATING_PUBLISHED = "RATING_PUBLISHED"
    RATING_ACTION = "RATING_ACTION"
    RATING_WITHDRAWN = "RATING_WITHDRAWN"
    RATING_REINSTATED = "RATING_REINSTATED"
    APPEAL_UPHELD = "APPEAL_UPHELD"
    APPEAL_DENIED = "APPEAL_DENIED"
    OBLIGATION_DELINQUENT = "OBLIGATION_DELINQUENT"
    REVIEW_OPENED = "REVIEW_OPENED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"


# ─── Entity TypedDicts (PRD sections 2.5 and 3) ─────────────────────────────
#
# Primary resources carry the four system-managed fields id / created_at /
# updated_at / version (PRD section 2.5).


class Issuer(TypedDict, total=False):
    id: str
    legal_name: str
    state_code: str
    issuer_type: str
    fiscal_year_end: str
    population: int
    credit_balance_cents: int
    delinquent_flag: bool
    created_at: str
    updated_at: str
    version: int


class Underwriter(TypedDict, total=False):
    id: str
    firm_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class RatingEngagement(TypedDict, total=False):
    id: str
    issuer_id: str
    underwriter_id: Optional[str]
    solicitation: str
    credit_type: str
    jurisdiction_code: str
    fee_cents: int
    fee_paid: bool
    refund_cents: int
    required_document_codes: List[str]
    received_document_codes: List[str]
    assigned_analyst_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalyticalScorecard(TypedDict, total=False):
    id: str
    engagement_id: str
    criteria_version_id: str
    score_economy: int
    score_management: int
    score_budgetary_performance: int
    score_flexibility: int
    score_liquidity: int
    score_debt_profile: int
    weighted_score: float
    anchor_notch: str
    capped: bool
    indicative_notch: str
    created_at: str
    updated_at: str
    version: int


class CriteriaVersion(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    credit_type: str
    version_label: str
    w_economy: float
    w_management: float
    w_budgetary_performance: float
    w_flexibility: float
    w_liquidity: float
    w_debt_profile: float
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeSession(TypedDict, total=False):
    id: str
    engagement_id: str
    criteria_version_id: str
    chair_id: str
    voter_ids: List[str]
    appointed_alternate_ids: List[str]
    recused_voter_ids: List[str]
    eligible_voter_count: int
    start_at: str
    end_at: str
    status: str
    outcome_notch: Optional[str]
    adjourn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    """Append-only ballot: id + created_at only (PRD section 2.5)."""

    id: str
    session_id: str
    voter_id: str
    kind: str
    notch_vote: Optional[str]
    recusal_reason: Optional[str]
    created_at: str


class NotchHistoryEntry(TypedDict, total=False):
    notch: str
    changed_at: str
    cause: str


class Rating(TypedDict, total=False):
    id: str
    engagement_id: str
    issuer_id: str
    criteria_version_id: str
    credit_type: str
    jurisdiction_code: str
    notch: str
    outlook: Optional[str]
    rationale: Optional[str]
    status: str
    surveillance_posture: str
    assigned_at: str
    published_at: Optional[str]
    withdrawn_at: Optional[str]
    withdraw_reason: Optional[str]
    notch_at_withdrawal: Optional[str]
    review_pending: bool
    notch_history: List[NotchHistoryEntry]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    rating_id: str
    new_information_codes: List[str]
    status: str
    decision_rationale: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondSale(TypedDict, total=False):
    id: str
    issuer_id: str
    rating_id: str
    par_amount_cents: int
    maturity_years: int
    sale_date: str
    pricing_mode: str
    effective_yield_bps: int
    annual_interest_cents: int
    total_interest_cents: int
    created_at: str
    updated_at: str
    version: int


class DisclosureObligation(TypedDict, total=False):
    id: str
    rating_id: str
    period_index: int
    fiscal_year_end: str
    due_at: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CriteriaReviewItem(TypedDict, total=False):
    id: str
    criteria_version_id: str
    rating_id: str
    due_at: str
    status: str
    outcome_notch: Optional[str]
    rationale: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IssuerNotification(TypedDict, total=False):
    """Append-only issuer communication: id + created_at only (PRD 2.5)."""

    id: str
    issuer_id: str
    event_type: str
    reference_id: str
    message: str
    created_at: str

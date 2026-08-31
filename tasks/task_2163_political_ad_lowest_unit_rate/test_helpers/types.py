"""Domain types for the political advertising compliance API.

Status enumerations, role names and per-entity TypedDicts, named exactly as the
PRD names them.  The rebate ledger is the one resource that carries neither
``updated_at`` nor ``version``, and its TypedDict reflects that.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATION_COMPLIANCE_OFFICER = "StationComplianceOfficer"
    TRAFFIC_SCHEDULER = "TrafficScheduler"
    ADVERTISER_AGENT = "AdvertiserAgent"
    PUBLIC_COMPLAINANT = "PublicComplainant"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EoParityBasis(str, Enum):
    SPOT_COUNT = "SPOT_COUNT"
    DOLLAR_VALUE = "DOLLAR_VALUE"


class ElectionType(str, Enum):
    PRIMARY = "PRIMARY"
    GENERAL = "GENERAL"
    RUNOFF = "RUNOFF"
    SPECIAL = "SPECIAL"


class ElectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WINDOW_OPEN = "WINDOW_OPEN"
    CLOSED = "CLOSED"


class RequestedClass(str, Enum):
    CANDIDATE = "CANDIDATE"
    ISSUE = "ISSUE"


class AdvertiserStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    CLASSIFIED_CANDIDATE = "CLASSIFIED_CANDIDATE"
    CLASSIFIED_ISSUE = "CLASSIFIED_ISSUE"
    CLASSIFICATION_REJECTED = "CLASSIFICATION_REJECTED"


class ClassificationDecision(str, Enum):
    REQUEST_INFO = "REQUEST_INFO"
    CLASSIFY_CANDIDATE = "CLASSIFY_CANDIDATE"
    CLASSIFY_ISSUE = "CLASSIFY_ISSUE"
    REJECT = "REJECT"


class Daypart(str, Enum):
    MORNING = "MORNING"
    DAYTIME = "DAYTIME"
    EARLY_NEWS = "EARLY_NEWS"
    PRIME = "PRIME"
    LATE_NIGHT = "LATE_NIGHT"


class RateClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class PaymentTerms(str, Enum):
    PREPAY = "PREPAY"
    NET_30 = "NET_30"


class DisclosureStatus(str, Enum):
    MISSING = "MISSING"
    NONCONFORMING = "NONCONFORMING"
    CONFORMING = "CONFORMING"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REFUND_DUE = "REFUND_DUE"
    REFUNDED = "REFUNDED"


class PaymentDirection(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class SpotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"


class SpotDisposition(str, Enum):
    AIRED = "AIRED"
    PREEMPTED = "PREEMPTED"


class FileEventType(str, Enum):
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    RATE_ADJUSTMENT = "RATE_ADJUSTMENT"
    EQUAL_OPPORTUNITY_RESPONSE = "EQUAL_OPPORTUNITY_RESPONSE"


class PostingStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    LATE_POSTED = "LATE_POSTED"
    OVERDUE = "OVERDUE"


class EoRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class EoDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class LucVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LucBasis(str, Enum):
    LOWEST_QUALIFYING_SPOT = "LOWEST_QUALIFYING_SPOT"
    POSTED_RATE_FALLBACK = "POSTED_RATE_FALLBACK"


class LucDeterminationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RebateReason(str, Enum):
    LUC_FINAL_REPRICE = "LUC_FINAL_REPRICE"
    SPOT_PREEMPTED = "SPOT_PREEMPTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class AllegationCode(str, Enum):
    LUC_OVERCHARGE = "LUC_OVERCHARGE"
    FILE_TIMELINESS = "FILE_TIMELINESS"
    EQUAL_OPPORTUNITY_DENIED = "EQUAL_OPPORTUNITY_DENIED"
    DISCLOSURE_DEFECT = "DISCLOSURE_DEFECT"


class RemedyCode(str, Enum):
    CURED = "CURED"
    PENDING_CURE = "PENDING_CURE"
    NO_VIOLATION = "NO_VIOLATION"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class OrderDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


# --------------------------------------------------------------- entities ---


class Station(TypedDict):
    id: str
    call_sign: str
    licensee_name: str
    market_code: str
    political_file_posting_deadline_hours: int
    daily_political_seconds_cap: int
    eo_parity_basis: str
    pending_file_entry_count: int
    overdue_file_entry_count: int
    late_posting_count: int
    open_complaint_count: int
    compliance_posture: str
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict):
    id: str
    station_id: str
    office_sought: str
    election_type: str
    election_date: str
    luc_window_days: int
    window_start_date: str
    window_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Advertiser(TypedDict):
    id: str
    station_id: str
    election_id: Optional[str]
    legal_name: str
    requested_class: str
    candidate_name: Optional[str]
    office_sought: Optional[str]
    qualification_evidence_ref: Optional[str]
    status: str
    review_round: int
    entitled_to_luc: bool
    classified_by_user_id: Optional[str]
    classification_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateClass(TypedDict):
    id: str
    station_id: str
    class_code: str
    daypart: str
    preemptible: bool
    preemption_priority: int
    posted_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommercialOrder(TypedDict):
    id: str
    station_id: str
    advertiser_id: str
    election_id: Optional[str]
    rate_class_id: str
    payment_terms: str
    agency_placed: bool
    sponsorship_disclosure_text: Optional[str]
    disclosure_duration_seconds: int
    disclosure_status: str
    status: str
    payment_status: str
    spot_count: int
    gross_charge_cents: int
    agency_commission_cents: int
    net_due_cents: int
    rebate_total_cents: int
    paid_cents: int
    refunded_cents: int
    accepted_at: Optional[str]
    accepted_by_user_id: Optional[str]
    payment_due_at: Optional[str]
    first_air_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScheduledSpot(TypedDict):
    id: str
    order_id: str
    rate_class_id: str
    air_date: str
    start_offset_seconds: int
    duration_seconds: int
    program_code: str
    status: str
    charged_rate_cents: int
    unit_equivalent_rate_cents: int
    luc_capped: bool
    luc_cap_cents: Optional[int]
    aired_at: Optional[str]
    preemption_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoliticalFileEntry(TypedDict):
    id: str
    station_id: str
    order_id: str
    event_type: str
    event_occurred_at: str
    due_at: str
    posted_at: Optional[str]
    posting_status: str
    late_by_seconds: int
    public_file_url: Optional[str]
    disclosure_snapshot: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EqualOpportunityRequest(TypedDict):
    id: str
    station_id: str
    election_id: Optional[str]
    requesting_advertiser_id: str
    trigger_order_id: str
    granted_order_id: Optional[str]
    received_at: str
    response_due_at: str
    status: str
    owed_units: int
    fulfilled_units: int
    parity_basis_applied: Optional[str]
    denial_reason: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LucDetermination(TypedDict):
    id: str
    station_id: str
    election_id: str
    rate_class_id: str
    basis_spot_id: Optional[str]
    variant: str
    luc_cents: int
    basis: str
    qualifying_spot_count: int
    window_start_date: str
    window_end_date: str
    status: str
    computed_at: str
    repriced_spot_count: int
    rebate_total_cents: int
    created_at: str
    updated_at: str
    version: int


class RebateLedgerEntry(TypedDict):
    """Immutable accounting record: carries only ``id`` and ``created_at``
    alongside its own fields; ``updated_at`` and ``version`` are absent."""

    id: str
    order_id: str
    luc_determination_id: Optional[str]
    amount_cents: int
    reason: str
    occurred_at: str
    created_at: str


class FccComplaint(TypedDict):
    id: str
    station_id: str
    order_id: Optional[str]
    complainant_name: str
    allegation_code: str
    narrative: str
    filed_at: str
    response_due_at: str
    status: str
    remedy_code: Optional[str]
    cure_due_at: Optional[str]
    responded_at: Optional[str]
    response_text: Optional[str]
    late_response: bool
    responded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int

"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOARD_PANEL = "BoardPanel"
    PETITIONER = "Petitioner"
    PATENT_OWNER = "PatentOwner"
    APPEALS_COURT = "AppealsCourt"


class PartyType(str, Enum):
    PETITIONER = "PETITIONER"
    PATENT_OWNER = "PATENT_OWNER"


class PatentStatus(str, Enum):
    ISSUED = "ISSUED"
    IN_REVIEW = "IN_REVIEW"
    PARTIALLY_CANCELLED = "PARTIALLY_CANCELLED"
    FULLY_CANCELLED = "FULLY_CANCELLED"
    CONFIRMED = "CONFIRMED"
    AMENDED = "AMENDED"


class MatterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STAYED = "STAYED"
    SETTLED = "SETTLED"
    TRIAL_COMPLETED = "TRIAL_COMPLETED"
    DISMISSED = "DISMISSED"


class StayReason(str, Enum):
    MANUAL_STAY = "MANUAL_STAY"
    INSTITUTION_STAY = "INSTITUTION_STAY"
    PATENT_CANCELLED = "PATENT_CANCELLED"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    NOTICE_ACCORDED = "NOTICE_ACCORDED"
    INSTITUTED = "INSTITUTED"
    DENIED = "DENIED"


class ReviewType(str, Enum):
    IPR = "IPR"
    PGR = "PGR"


class GroundBasis(str, Enum):
    ANTICIPATION_102 = "ANTICIPATION_102"
    OBVIOUSNESS_103 = "OBVIOUSNESS_103"
    PUBLIC_USE = "PUBLIC_USE"
    ON_SALE = "ON_SALE"
    OTHER_STATUTORY = "OTHER_STATUTORY"


class ReferenceType(str, Enum):
    PATENT = "PATENT"
    PRINTED_PUBLICATION = "PRINTED_PUBLICATION"
    PRODUCT = "PRODUCT"
    TESTIMONY = "TESTIMONY"


class InstitutionOutcome(str, Enum):
    INSTITUTED = "INSTITUTED"
    DENIED_MERITS = "DENIED_MERITS"
    DENIED_DISCRETIONARY = "DENIED_DISCRETIONARY"


class ProceedingPhase(str, Enum):
    INSTITUTED = "INSTITUTED"
    REPLY_WINDOW = "REPLY_WINDOW"
    SUR_REPLY_WINDOW = "SUR_REPLY_WINDOW"
    HEARING_PHASE = "HEARING_PHASE"
    DECISION_PHASE = "DECISION_PHASE"
    DECIDED = "DECIDED"
    REMANDED = "REMANDED"
    CLOSED = "CLOSED"


class BriefType(str, Enum):
    PO_RESPONSE = "PO_RESPONSE"
    PETITIONER_REPLY = "PETITIONER_REPLY"
    PO_SUR_REPLY = "PO_SUR_REPLY"


class DiscoveryType(str, Enum):
    ROUTINE = "ROUTINE"
    ADDITIONAL = "ADDITIONAL"


class DiscoveryStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class MotionStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class HearingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    WAIVED = "WAIVED"


class HearingOutcome(str, Enum):
    HELD = "HELD"
    WAIVED = "WAIVED"
    CONTINUED = "CONTINUED"


class ClaimOutcome(str, Enum):
    UNPATENTABLE = "UNPATENTABLE"
    NOT_UNPATENTABLE = "NOT_UNPATENTABLE"
    AMENDED_SUBSTITUTED = "AMENDED_SUBSTITUTED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    AFFIRMED = "AFFIRMED"
    VACATED_AND_REMANDED = "VACATED_AND_REMANDED"
    DISMISSED = "DISMISSED"


class AppealOutcome(str, Enum):
    AFFIRMED = "AFFIRMED"
    DISMISSED = "DISMISSED"
    VACATED_AND_REMANDED = "VACATED_AND_REMANDED"


class RemandInstructions(str, Enum):
    REOPEN_RECORD = "REOPEN_RECORD"
    RECONSIDER = "RECONSIDER"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id, created_at, updated_at, version (PRD §2.5).
# Immutable event records (InstitutionDecision, FinalWrittenDecision) carry
# only id and created_at — updated_at and version are absent (PRD §2.5).

class Party(TypedDict, total=False):
    id: str
    name: str
    party_type: str
    counsel_firm: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patent(TypedDict, total=False):
    id: str
    patent_number: str
    title: str
    issue_date: str
    owner_id: str
    total_claims: int
    status: str
    claims_alive: int
    claims_cancelled_count: int
    claims_amended_count: int
    created_at: str
    updated_at: str
    version: int


class LitigationMatter(TypedDict, total=False):
    id: str
    patent_id: str
    defendant_party_id: str
    court_name: str
    docket_number: str
    complaint_served_date: str
    trial_date: Optional[str]
    status: str
    stay_reason: Optional[str]
    estoppel_claims: List[int]
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict, total=False):
    id: str
    patent_id: str
    petitioner_id: str
    review_type: str
    challenged_claims: List[int]
    grounds: List[Dict[str, Any]]
    prior_art: List[Dict[str, Any]]
    real_party_in_interest: str
    fee_paid_cents: int
    filing_date: str
    accorded_date: Optional[str]
    status: str
    fintiv_score: int
    merits_max_score: Optional[int]
    advisory_aggregate_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InstitutionDecision(TypedDict, total=False):
    id: str
    created_at: str
    petition_id: str
    outcome: str
    merits_max_score: int
    threshold_used: int
    advisory_aggregate_score: int
    fintiv_score: int
    lead_judge_user_id: str
    decided_at: str


class Proceeding(TypedDict, total=False):
    id: str
    petition_id: str
    patent_id: str
    lead_judge_user_id: str
    instituted_claims: List[int]
    phase: str
    institution_date: str
    cycle_anchor_date: str
    fwd_due_date: str
    advisory_anniversary_date: str
    extension_used: bool
    estoppel_applied: bool
    amendment_slots_available: int
    briefing_cycle: int
    total_overage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Brief(TypedDict, total=False):
    id: str
    proceeding_id: str
    brief_type: str
    author_user_id: str
    page_count: int
    overage_fee_cents: int
    cycle: int
    created_at: str
    updated_at: str
    version: int


class ExpertDeclaration(TypedDict, total=False):
    id: str
    brief_id: str
    declarant_name: str
    page_count: int
    contains_new_evidence: bool
    created_at: str
    updated_at: str
    version: int


class DiscoveryRequest(TypedDict, total=False):
    id: str
    proceeding_id: str
    requester_user_id: str
    discovery_type: str
    factor_scores: Optional[List[int]]
    garmin_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmendmentMotion(TypedDict, total=False):
    id: str
    proceeding_id: str
    cycle: int
    substitute_claims: List[Dict[str, Any]]
    status: str
    construction_standard: str
    created_at: str
    updated_at: str
    version: int


class OralHearing(TypedDict, total=False):
    id: str
    proceeding_id: str
    hearing_room_id: Optional[str]
    start_at: Optional[str]
    end_at: Optional[str]
    argument_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingRoom(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class FinalWrittenDecision(TypedDict, total=False):
    id: str
    created_at: str
    proceeding_id: str
    cycle: int
    outcomes: List[Dict[str, Any]]
    issued_at: str
    claims_cancelled_count: int


class Appeal(TypedDict, total=False):
    id: str
    proceeding_id: str
    appellant_user_id: str
    status: str
    remand_instructions: Optional[str]
    created_at: str
    updated_at: str
    version: int

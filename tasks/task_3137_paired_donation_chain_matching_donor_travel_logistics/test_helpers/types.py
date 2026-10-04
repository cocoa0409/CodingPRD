"""Domain types: entity TypedDicts, status enums, role enum.

All types are derived from the PRD's entity and state-machine descriptions.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTRY_ADMIN = "RegistryAdmin"
    MATCH_OPERATOR = "MatchOperator"
    CENTER_COORDINATOR = "CenterCoordinator"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class CenterTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    NATIONAL_HUB = "NATIONAL_HUB"


class ParticipationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AboType(str, Enum):
    A = "A"
    B = "B"
    AB = "AB"
    O = "O"


class DonorKind(str, Enum):
    PAIRED = "PAIRED"
    ALTRUISTIC = "ALTRUISTIC"
    BRIDGE = "BRIDGE"


class DonorMedicalStatus(str, Enum):
    CLEARED = "CLEARED"
    ON_HOLD = "ON_HOLD"
    WITHDRAWN = "WITHDRAWN"
    DECEASED = "DECEASED"


class DonorSurgeryState(str, Enum):
    PRE_SURGERY = "PRE_SURGERY"
    SURGERY_SCHEDULED = "SURGERY_SCHEDULED"
    NEPHRECTOMY_DONE = "NEPHRECTOMY_DONE"
    FAILED_PREOP = "FAILED_PREOP"


class DonorChainParticipationState(str, Enum):
    POOL = "POOL"
    PROPOSED = "PROPOSED"
    LOCKED = "LOCKED"
    COMMITTED = "COMMITTED"
    COMPLETED = "COMPLETED"
    BROKEN = "BROKEN"
    WITHDRAWN = "WITHDRAWN"


class PriorityWaitlistStatus(str, Enum):
    NONE = "NONE"
    ELIGIBLE = "ELIGIBLE"
    ENROLLED = "ENROLLED"


class RecipientMedicalStatus(str, Enum):
    LISTED = "LISTED"
    ON_HOLD = "ON_HOLD"
    TRANSPLANTED = "TRANSPLANTED"
    WITHDRAWN = "WITHDRAWN"
    DECEASED = "DECEASED"


class RecipientChainParticipationState(str, Enum):
    POOL = "POOL"
    PROPOSED = "PROPOSED"
    LOCKED = "LOCKED"
    COMMITTED = "COMMITTED"
    TRANSPLANTED = "TRANSPLANTED"
    ORPHANED = "ORPHANED"
    WITHDRAWN = "WITHDRAWN"


class PairState(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFIED = "VERIFIED"
    IN_POOL = "IN_POOL"
    IN_PROPOSED_CHAIN = "IN_PROPOSED_CHAIN"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    DISSOLVED = "DISSOLVED"


class DissolutionReason(str, Enum):
    NONE = "NONE"
    RECIPIENT_TRANSPLANTED = "RECIPIENT_TRANSPLANTED"
    DONOR_WITHDRAWN = "DONOR_WITHDRAWN"
    MEDICAL_DECLINE = "MEDICAL_DECLINE"
    CHAIN_BROKEN = "CHAIN_BROKEN"


class RunState(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ChainState(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTING = "ACCEPTING"
    LOCKED = "LOCKED"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    BROKEN = "BROKEN"
    ABORTED = "ABORTED"


class CompletionGrade(str, Enum):
    PENDING = "PENDING"
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    BROKEN_PARTIAL = "BROKEN_PARTIAL"


class OfferState(str, Enum):
    PENDING_CROSSMATCH = "PENDING_CROSSMATCH"
    CROSSMATCH_PASSED = "CROSSMATCH_PASSED"
    CROSSMATCH_FAILED = "CROSSMATCH_FAILED"
    CENTER_ACCEPTED = "CENTER_ACCEPTED"
    CENTER_DECLINED = "CENTER_DECLINED"
    SCHEDULED = "SCHEDULED"
    DONOR_SURGERY_DONE = "DONOR_SURGERY_DONE"
    ORGAN_SHIPPED = "ORGAN_SHIPPED"
    TRANSPLANT_COMPLETED = "TRANSPLANT_COMPLETED"
    OFFER_FAILED = "OFFER_FAILED"


class OfferFailureReason(str, Enum):
    NONE = "NONE"
    CROSSMATCH_POSITIVE = "CROSSMATCH_POSITIVE"
    CENTER_DECLINE = "CENTER_DECLINE"
    COLD_ISCHEMIA = "COLD_ISCHEMIA"
    DONOR_UNAVAILABLE = "DONOR_UNAVAILABLE"
    CHAIN_BREAK_PROPAGATION = "CHAIN_BREAK_PROPAGATION"


class VirtualResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    WEAK_POSITIVE = "WEAK_POSITIVE"
    STRONG_POSITIVE = "STRONG_POSITIVE"
    INDETERMINATE = "INDETERMINATE"


class CrossmatchDecision(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class RoomKind(str, Enum):
    NEPHRECTOMY_OR = "NEPHRECTOMY_OR"
    TRANSPLANT_OR = "TRANSPLANT_OR"
    BACK_OR = "BACK_OR"


class SlotState(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ShipmentMode(str, Enum):
    COMMERCIAL_FLIGHT = "COMMERCIAL_FLIGHT"
    CHARTER = "CHARTER"
    GROUND_COURIER = "GROUND_COURIER"


class ShipmentState(str, Enum):
    PLANNED = "PLANNED"
    DEPARTED = "DEPARTED"
    DELAYED = "DELAYED"
    REROUTED = "REROUTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ContingencyReason(str, Enum):
    NONE = "NONE"
    WEATHER = "WEATHER"
    MECHANICAL = "MECHANICAL"
    ATC = "ATC"
    COURIER_BREAKDOWN = "COURIER_BREAKDOWN"


class ItineraryState(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REIMBURSED = "REIMBURSED"


class ItineraryCancelReason(str, Enum):
    NONE = "NONE"
    CHAIN_BROKEN = "CHAIN_BROKEN"
    DONOR_UNAVAILABLE = "DONOR_UNAVAILABLE"
    SCHEDULE_MOVED = "SCHEDULE_MOVED"


class PolicyState(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXHAUSTED = "EXHAUSTED"


class ClaimKind(str, Enum):
    COMPLICATION = "COMPLICATION"
    LOST_WAGES = "LOST_WAGES"
    TRAVEL = "TRAVEL"
    PRIORITY_KIDNEY = "PRIORITY_KIDNEY"


class ClaimState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class OutcomeKind(str, Enum):
    SUCCESS = "SUCCESS"
    DELAYED_GRAFT_FUNCTION = "DELAYED_GRAFT_FUNCTION"
    PRIMARY_NON_FUNCTION = "PRIMARY_NON_FUNCTION"
    REJECTED_30D = "REJECTED_30D"
    FAILED = "FAILED"


class OutcomeState(str, Enum):
    REPORTED = "REPORTED"
    ATTRIBUTED_TO_CENTER = "ATTRIBUTED_TO_CENTER"
    APPEALED = "APPEALED"
    FINAL = "FINAL"


class BreakTriggerKind(str, Enum):
    DONOR_MEDICAL_DECLINE = "DONOR_MEDICAL_DECLINE"
    DONOR_WITHDRAWAL = "DONOR_WITHDRAWAL"
    DONOR_DECEASED = "DONOR_DECEASED"
    SURGERY_ABORTED = "SURGERY_ABORTED"
    ORGAN_LOST_IN_TRANSIT = "ORGAN_LOST_IN_TRANSIT"


class BreakEventState(str, Enum):
    RECORDED = "RECORDED"
    CASCADED = "CASCADED"
    RECONSTRUCTED = "RECONSTRUCTED"


# --- Entity TypedDicts (all entities carry common fields) ---


class TransplantCenter(TypedDict, total=False):
    id: str
    center_code: str
    name: str
    region_code: str
    tier: str
    max_concurrent_chains: int
    participation_status: str
    failed_outcome_count: int
    shipped_organ_count: int
    probed_cold_ischemia_violations: int
    reputation_score_bps: int
    active_chain_count: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict, total=False):
    id: str
    external_ref: str
    home_center_id: str
    abo_type: str
    hla_a: str
    hla_b: str
    hla_drb1: str
    kdri_score: int
    age_at_registration: int
    donor_kind: str
    medical_status: str
    surgery_state: str
    chain_participation_state: str
    protection_policy_id: Optional[str]
    priority_waitlist_status: str
    traveled_distance_miles: float
    complications_recorded: int
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict, total=False):
    id: str
    external_ref: str
    home_center_id: str
    abo_type: str
    cpra_percent: int
    unacceptable_antigens: List[str]
    medical_status: str
    chain_participation_state: str
    paired_donor_id: Optional[str]
    listed_at_utc: str
    waiting_time_days: int
    transplant_completed_at_utc: Optional[str]
    priority_boost_active: bool
    created_at: str
    updated_at: str
    version: int


class DonorRecipientPair(TypedDict, total=False):
    id: str
    donor_id: str
    recipient_id: str
    pair_state: str
    registered_center_id: str
    entered_pool_at_utc: Optional[str]
    dissolution_reason: str
    created_at: str
    updated_at: str
    version: int


class ChainRun(TypedDict, total=False):
    id: str
    run_label: str
    started_at_utc: str
    run_state: str
    algorithm_version: Optional[str]
    candidate_pool_size: int
    proposed_chain_count: int
    created_at: str
    updated_at: str
    version: int


class Chain(TypedDict, total=False):
    id: str
    chain_run_id: str
    starter_donor_id: str
    chain_state: str
    length_target: int
    length_actual: int
    starts_at_center_id: str
    completion_grade: str
    scheduled_date: Optional[str]
    broken_at_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MatchOffer(TypedDict, total=False):
    id: str
    chain_id: str
    position_index: int
    donor_id: str
    recipient_id: str
    donor_center_id: str
    recipient_center_id: str
    offer_state: str
    match_score_bps: int
    abo_compatible: bool
    hla_mismatch_count: int
    unacceptable_antigen_hit: bool
    proposed_at_utc: str
    accepted_at_utc: Optional[str]
    crossmatch_deadline_utc: str
    center_accept_deadline_utc: str
    donor_travel_required: bool
    offer_failure_reason: str
    created_at: str
    updated_at: str
    version: int


class CrossmatchReview(TypedDict, total=False):
    id: str
    match_offer_id: str
    reviewer_center_id: str
    virtual_result: str
    flow_cytometry_channel_shift: int
    dsa_mfi_max: int
    decision: str
    decided_at_utc: Optional[str]
    review_notes: str
    created_at: str
    updated_at: str
    version: int


class SurgeryScheduleSlot(TypedDict, total=False):
    id: str
    center_id: str
    slot_start_utc: str
    slot_end_utc: str
    room_kind: str
    slot_state: str
    reserved_for_chain_id: Optional[str]
    reserved_for_offer_id: Optional[str]
    simultaneous_group_id: Optional[str]
    consumed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrganShipment(TypedDict, total=False):
    id: str
    match_offer_id: str
    origin_center_id: str
    destination_center_id: str
    shipment_mode: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    cold_ischemia_hours_actual: Optional[float]
    cold_ischemia_max_hours: int
    cold_ischemia_violation: bool
    shipment_state: str
    contingency_reason: str
    routing_sequence: int
    created_at: str
    updated_at: str
    version: int


class TravelItinerary(TypedDict, total=False):
    id: str
    donor_id: str
    origin_airport_code: str
    destination_airport_code: str
    depart_utc: str
    arrive_utc: str
    segment_miles: int
    lodging_nights: int
    itinerary_state: str
    estimated_cost_cents: Optional[int]
    cancelled_reason: str
    created_at: str
    updated_at: str
    version: int


class DonorProtectionPolicy(TypedDict, total=False):
    id: str
    donor_id: str
    policy_state: str
    covered_complication_max_cents: int
    covered_lost_wages_max_cents: int
    complications_paid_cents: int
    lost_wages_paid_cents: int
    travel_reimbursed_cents: int
    priority_kidney_claim_available: bool
    created_at: str
    updated_at: str
    version: int


class DonorProtectionClaim(TypedDict, total=False):
    id: str
    policy_id: str
    claim_kind: str
    requested_amount_cents: Optional[int]
    approved_amount_cents: Optional[int]
    claim_state: str
    adjudicator_user_id: Optional[str]
    submitted_at_utc: str
    resolved_at_utc: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransplantOutcome(TypedDict, total=False):
    id: str
    match_offer_id: str
    outcome_kind: str
    reported_at_utc: str
    followup_days: int
    outcome_state: str
    attributed_center_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChainBreakEvent(TypedDict, total=False):
    id: str
    chain_id: str
    broken_at_offer_id: str
    trigger_kind: str
    recipients_already_transplanted: int
    downstream_recipients_orphaned: int
    bridge_donor_id: Optional[str]
    event_state: str
    created_at: str
    updated_at: str
    version: int

"""Lightweight shapes describing the request payloads and the composite state
that the fixtures in this package hand back to tests.

These are documentation-grade ``TypedDict``s: they name the fields the PRD
declares so that a test reading a fixture result knows what is available.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CancellationTier(TypedDict):
    days_before_arrival_min: int
    fee_pct: float


class BenchmarkPayload(TypedDict, total=False):
    destination_tier: str
    program_type: str
    benchmark_adr_usd: float
    benchmark_service_charge_pct: float
    benchmark_tax_pct: float


class VenuePayload(TypedDict, total=False):
    name: str
    city: str
    country: str
    destination_tier: str
    guest_rooms_total: int
    largest_space_sqft: int
    preferred_supplier_status: str


class EventPayload(TypedDict, total=False):
    event_code: str
    name: str
    program_type: str
    start_date: str
    end_date: str
    peak_attendees: int
    requested_room_nights: int
    largest_meeting_space_sqft: int
    budget_ceiling_usd: float
    preferred_program_only: bool


class ShortlistEntryPayload(TypedDict, total=False):
    venue_id: str
    rank_seq: int
    inspection_required: bool


class SiteInspectionPayload(TypedDict, total=False):
    shortlist_entry_id: str
    inspector_user_id: str
    window_start: str
    window_end: str
    travel_buffer_minutes: int


class RfpPayload(TypedDict, total=False):
    round_number: int
    response_due_at: str
    standard_response_version: str
    previous_rfp_id: Optional[str]
    instructions: Optional[str]


class ProposalSubmissionPayload(TypedDict, total=False):
    room_rate_usd: float
    rate_type: str
    commission_pct: float
    room_nights_offered: int
    comp_room_ratio: int
    resort_fee_usd_per_night: float
    service_charge_pct: float
    tax_pct: float
    av_estimate_usd: float
    fnb_minimum_usd: float
    concession_credit_usd: float
    attrition_allowance_pct: float
    cancellation_schedule: List[CancellationTier]
    force_majeure_scope: str
    rebooking_credit_pct: float


class CounterPayload(TypedDict, total=False):
    expected_proposal_version: int
    term_category: str
    proposed_numeric_value: Optional[float]
    proposed_text_value: Optional[str]
    planner_note: Optional[str]


class RevisionPayload(TypedDict, total=False):
    counter_id: str
    accepted: bool
    revised_room_rate_usd: float
    revised_concession_credit_usd: float
    revised_attrition_allowance_pct: float
    revised_cancellation_schedule: List[CancellationTier]
    revised_force_majeure_scope: str
    revised_rebooking_credit_pct: float
    revised_av_estimate_usd: float
    revised_fnb_minimum_usd: float


class AwardPayload(TypedDict, total=False):
    proposal_id: str
    expected_event_version: int
    award_note: Optional[str]


class PostEventReportPayload(TypedDict, total=False):
    actual_room_nights: int
    actual_fnb_usd: float
    actual_av_usd: float
    notes: Optional[str]


class PerformanceReviewPayload(TypedDict, total=False):
    review_source: str
    service_score: int
    value_score: int
    av_quality_score: int
    responsiveness_score: int
    event_id: Optional[str]
    comment: Optional[str]


class SourcingWorld(TypedDict, total=False):
    """The composite state a sourcing scenario fixture returns.

    Keys are present only once the corresponding artefact has been created.
    """

    benchmark: Dict[str, Any]
    venue: Dict[str, Any]
    venue_id: str
    event: Dict[str, Any]
    event_id: str
    entry: Dict[str, Any]
    entry_id: str
    rfp: Dict[str, Any]
    rfp_id: str
    proposal: Dict[str, Any]
    proposal_id: str
    contract: Dict[str, Any]
    contract_id: str
    steps: List[Dict[str, Any]]
    installments: List[Dict[str, Any]]

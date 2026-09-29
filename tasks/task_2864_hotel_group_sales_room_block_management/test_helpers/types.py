"""Entity shapes and enumerations declared by the PRD.

The TypedDicts are documentation-grade: they name the properties the PRD
declares on each resource so that tests can be read without the PRD open.
They are all ``total=False`` because a response body is asserted field by
field, never structurally.
"""

from typing import Any, Dict, List, Optional, TypedDict

# --------------------------------------------------------------------------
# Roles (PRD 2.1) - spelled exactly as they must appear in X-User-Role
# --------------------------------------------------------------------------


class Role:
    SALES_MANAGER = "SalesManager"
    REVENUE_MANAGER = "RevenueManager"
    CONTRACT_ADMIN = "ContractAdmin"
    RESERVATIONS_AGENT = "ReservationsAgent"
    ACCOUNTING_CLERK = "AccountingClerk"
    GROUP_CONTACT = "GroupContact"
    SYSTEM_OPERATOR = "SystemOperator"


ALL_ROLES = [
    Role.SALES_MANAGER,
    Role.REVENUE_MANAGER,
    Role.CONTRACT_ADMIN,
    Role.RESERVATIONS_AGENT,
    Role.ACCOUNTING_CLERK,
    Role.GROUP_CONTACT,
    Role.SYSTEM_OPERATOR,
]

# A role name deliberately outside the seven declared roles (PRD 2.1).
UNDECLARED_ROLE = "GeneralManager"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class MarketSegment:
    CORPORATE = "CORPORATE"
    ASSOCIATION = "ASSOCIATION"
    GOVERNMENT = "GOVERNMENT"
    SMERF = "SMERF"


class LeadStatus:
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    TURNED_DOWN = "TURNED_DOWN"
    DISPLACEMENT_REVIEW = "DISPLACEMENT_REVIEW"
    CLEARED = "CLEARED"
    QUOTED = "QUOTED"
    WON = "WON"
    LOST = "LOST"


class AnalysisVariant:
    FORECAST_BASED = "FORECAST_BASED"
    HISTORICAL_BASED = "HISTORICAL_BASED"


class AnalysisStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Verdict:
    ACCEPT = "ACCEPT"
    OVERRIDE_REQUIRED = "OVERRIDE_REQUIRED"


class Decision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class QuoteStatus:
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ContractStatus:
    DRAFT = "DRAFT"
    SENT = "SENT"
    SIGNED = "SIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    TERMINATED_FORCE_MAJEURE = "TERMINATED_FORCE_MAJEURE"


class AttritionBasis:
    ROOM_NIGHTS = "ROOM_NIGHTS"
    PEAK_NIGHT = "PEAK_NIGHT"


class ForceMajeureClause:
    NONE = "NONE"
    STANDARD = "STANDARD"
    EXPANDED = "EXPANDED"


class CancellationReason:
    CLIENT_CANCEL = "CLIENT_CANCEL"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class BlockInventoryStatus:
    SETUP = "SETUP"
    OPEN = "OPEN"
    CUT_OFF = "CUT_OFF"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class BlockBillingStatus:
    UNBILLED = "UNBILLED"
    ATTRITION_ASSESSED = "ATTRITION_ASSESSED"
    WAIVED = "WAIVED"
    SETTLED = "SETTLED"


class ReservationStatus:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReservationSource:
    ROOMING_LIST = "ROOMING_LIST"
    INDIVIDUAL_CALL = "INDIVIDUAL_CALL"


class ChargeCategory:
    BANQUET = "BANQUET"
    AUDIOVISUAL = "AUDIOVISUAL"
    PARKING = "PARKING"
    INTERNET = "INTERNET"


class ChargeStatus:
    QUOTED = "QUOTED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ReconciliationStatus:
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class HoldStatus:
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class SpaceCode:
    GRAND_BALLROOM = "GRAND_BALLROOM"
    SALON_A = "SALON_A"
    SALON_B = "SALON_B"
    BOARDROOM = "BOARDROOM"


# --------------------------------------------------------------------------
# Entity shapes (PRD 2.5 common properties plus the per-entity fields)
# --------------------------------------------------------------------------


class CommonResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class GroupAccount(CommonResource, total=False):
    name: str
    market_segment: str
    billing_contact_email: str
    credit_hold: bool
    owner_user_id: str
    repeat_group_count: int
    lifetime_actualized_room_nights: int
    last_completed_departure_date: Optional[str]
    rebooking_incentive_pct: float


class InventoryDay(CommonResource, total=False):
    stay_date: str
    total_rooms: int
    group_ceiling_rooms: int
    transient_demand_rooms: int
    transient_adr_cents: int
    historical_pickup_rooms: int
    historical_adr_cents: int
    held_group_rooms: int
    committed_group_rooms: int


class ConcessionPackage(CommonResource, total=False):
    name: str
    room_rate_discount_pct: float
    comp_room_ratio: int
    rebate_per_room_night_cents: int
    banquet_discount_pct: float
    av_discount_pct: float
    parking_discount_pct: float
    min_peak_rooms: int
    min_total_room_nights: int
    max_discount_stack_pct: float
    discount_stack_pct: float


class Lead(CommonResource, total=False):
    account_id: str
    program_name: str
    arrival_date: str
    departure_date: str
    nights_count: int
    peak_rooms: int
    total_requested_room_nights: int
    meeting_space_sqft_needed: int
    decision_deadline_at: str
    owner_user_id: str
    status: str
    qualification_score: Optional[int]
    estimated_room_night_value_cents: Optional[int]


class DisplacementAnalysis(CommonResource, total=False):
    lead_id: str
    analysis_variant: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    override_reason: Optional[str]
    displaced_room_nights: int
    displaced_revenue_cents: int
    group_revenue_cents: int
    ancillary_projection_cents: int
    net_benefit_cents: int
    verdict: str


class RateQuote(CommonResource, total=False):
    lead_id: str
    concession_package_id: str
    base_rate_cents: int
    quoted_peak_rooms: int
    quoted_room_nights: int
    expires_at: str
    status: str
    negotiation_round: int
    hold_placed: bool
    prepared_by_user_id: str
    comp_room_ratio: int
    rebate_per_room_night_cents: int
    effective_net_rate_cents: int
    total_quote_value_cents: int
    countered_base_rate_cents: Optional[int]
    counter_note: Optional[str]


class GroupContract(CommonResource, total=False):
    quote_id: str
    status: str
    attrition_threshold_pct: float
    attrition_basis: str
    force_majeure_clause: str
    cutoff_days_before_arrival: int
    contracted_room_nights: int
    contracted_peak_rooms: int
    contracted_rate_cents: int
    arrival_date: str
    departure_date: str
    nights_count: int
    cutoff_date: Optional[str]
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    signature_name: Optional[str]
    cancellation_reason: Optional[str]
    note: Optional[str]
    assessed_damages_cents: int
    ancillary_posted_cents: int
    rebate_paid_cents: int
    receivable_total_cents: int


class RoomBlock(CommonResource, total=False):
    contract_id: str
    parent_block_id: Optional[str]
    name: str
    is_master: bool
    inventory_status: str
    billing_status: str
    cutoff_date: str
    allotted_room_nights: int
    picked_up_room_nights: int
    released_room_nights: int
    peak_night_rooms: int
    comp_room_nights: int
    waived_by_user_id: Optional[str]
    waiver_reason: Optional[str]


class BlockNight(CommonResource, total=False):
    block_id: str
    stay_date: str
    rooms_allotted: int
    rooms_sub_allocated: int
    rooms_picked_up: int
    rooms_released: int
    rooms_open: int


class Reservation(CommonResource, total=False):
    block_id: str
    guest_name: str
    arrival_date: str
    departure_date: str
    room_nights: int
    source: str
    status: str
    is_comp: bool
    rate_cents: int
    disposition_reason: Optional[str]


class AncillaryCharge(CommonResource, total=False):
    contract_id: str
    category: str
    gross_amount_cents: int
    discount_pct: float
    net_amount_cents: int
    status: str


class Reconciliation(CommonResource, total=False):
    contract_id: str
    status: str
    prepared_by_user_id: str
    finalized_by_user_id: Optional[str]
    actualized_room_nights: int
    billable_room_nights: int
    attrition_shortfall_room_nights: int
    attrition_damages_cents: int
    ancillary_net_cents: int
    gross_settlement_cents: int
    rebate_payable_cents: int
    net_before_incentive_cents: int
    incentive_rate_snapshot: float
    rebooking_incentive_cents: int
    total_settlement_cents: int


class FunctionSpaceHold(CommonResource, total=False):
    lead_id: str
    space_code: str
    start_at: str
    end_at: str
    attendee_count: int
    status: str


class PickupSummary(TypedDict, total=False):
    block_id: str
    allotted_room_nights: int
    picked_up_room_nights: int
    released_room_nights: int
    peak_night_rooms: int
    commitment_base_room_nights: int
    room_nights_basis_shortfall: int
    room_nights_basis_damages_cents: int
    peak_night_basis_shortfall: int
    peak_night_basis_damages_cents: int


class NightlyAllotment(TypedDict):
    stay_date: str
    rooms: int


# A loose accumulator threaded between the composite setup helpers.
World = Dict[str, Any]
AllotmentPlan = List[NightlyAllotment]

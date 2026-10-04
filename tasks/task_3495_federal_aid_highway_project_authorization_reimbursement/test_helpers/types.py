"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATE_DOT_PLANNER = "StateDOTPlanner"
    STATE_DOT_ENGINEER = "StateDOTEngineer"
    FHWA_DIVISION_ADMIN = "FHWADivisionAdmin"
    FHWA_REVIEWER = "FHWAReviewer"


class FundingProgramCode(str, Enum):
    NHPP = "NHPP"
    STBG = "STBG"
    HSIP = "HSIP"
    CMAQ = "CMAQ"
    TAP = "TAP"


class ActivityCode(str, Enum):
    ROAD_RESURFACING = "ROAD_RESURFACING"
    BRIDGE_REPLACEMENT = "BRIDGE_REPLACEMENT"
    SIGNAGE_LIGHTING = "SIGNAGE_LIGHTING"
    GUARDRAIL_INSTALL = "GUARDRAIL_INSTALL"
    PEDESTRIAN_CROSSING = "PEDESTRIAN_CROSSING"
    TRANSIT_EXPANSION = "TRANSIT_EXPANSION"


class StipStatus(str, Enum):
    PUBLIC_INVOLVEMENT = "PUBLIC_INVOLVEMENT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class ProjectStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    AUTHORIZED = "AUTHORIZED"
    BIDDING = "BIDDING"
    BIDS_OPENED = "BIDS_OPENED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    COMPLETE = "COMPLETE"
    CLOSED_OUT = "CLOSED_OUT"


class ClearanceKind(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    RIGHT_OF_WAY = "RIGHT_OF_WAY"


class NepaClass(str, Enum):
    CE = "CE"
    EA = "EA"
    EIS = "EIS"


class ClearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class RowCertLevel(str, Enum):
    LEVEL_1_FULL = "LEVEL_1_FULL"
    LEVEL_2_CONDITIONAL = "LEVEL_2_CONDITIONAL"


class AuthorizationStatus(str, Enum):
    OBLIGATED = "OBLIGATED"
    FULLY_DRAWN = "FULLY_DRAWN"
    CLOSED = "CLOSED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    STATE_CONCURRED = "STATE_CONCURRED"
    FEDERAL_APPROVED = "FEDERAL_APPROVED"
    FEDERAL_REJECTED = "FEDERAL_REJECTED"


class AuditStatus(str, Enum):
    INITIATED = "INITIATED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    FINAL = "FINAL"
    CLOSED = "CLOSED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ClearanceDecision(str, Enum):
    CLEARED = "CLEARED"
    REJECT = "REJECT"


class EligibilityDetermination(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts. All carry id/created_at/updated_at/version (PRD §2.5)
# except PublicComment, which carries only id/created_at plus its own fields.
# ---------------------------------------------------------------------------


class FundingProgram(TypedDict):
    id: str
    code: str
    name: str
    eligible_activity_codes: List[str]
    base_federal_share_pct: float
    created_at: str
    updated_at: str
    version: int


class Apportionment(TypedDict):
    id: str
    funding_program_id: str
    state_code: str
    federal_fiscal_year: int
    apportioned_cents: int
    obligated_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class StateProgram(TypedDict):
    id: str
    state_code: str
    state_federal_land_pct: float
    start_federal_fiscal_year: int
    end_federal_fiscal_year: int
    description: str
    status: str
    comment_period_opened_at: str
    amendment_count: int
    total_programmed_federal_cents: int
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    """Append-only resource: carries only id and created_at (PRD §2.5)."""

    id: str
    stip_id: str
    author_name: str
    comment_text: str
    created_at: str


class Project(TypedDict):
    id: str
    stip_id: str
    funding_program_id: str
    route_name: str
    description: str
    activity_code: str
    is_interstate_system: bool
    dbe_goal_pct: float
    total_estimated_cost_cents: int
    provisional_federal_share_pct: float
    provisional_federal_estimate_cents: int
    determined_federal_share_pct: Optional[float]
    status: str
    advertised_on_date: Optional[str]
    awarded_bid_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectClearance(TypedDict):
    id: str
    project_id: str
    kind: str
    nepa_class: Optional[str]
    status: str
    row_cert_level: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    project_id: str
    agreement_number: str
    initial_obligated_cents: int
    apportionment_id: str
    federal_share_pct: float
    obligated_cents: int
    reimbursed_cents: int
    repaid_cents: int
    cumulative_change_order_federal_cents: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    project_id: str
    contractor_name: str
    bid_amount_cents: int
    is_responsive: bool
    submission_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VoucherLineItem(TypedDict):
    description: str
    eligible_amount_cents: int


class Voucher(TypedDict):
    id: str
    authorization_id: str
    period_start_date: str
    period_end_date: str
    line_items: List[VoucherLineItem]
    documentation_complete: bool
    is_final: bool
    status: str
    claimed_amount_cents: int
    eligible_amount_cents: Optional[int]
    federal_reimbursable_cents: Optional[int]
    ineligible_line_indexes: Optional[List[int]]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    authorization_id: str
    description: str
    delta_cost_cents: int
    requested_by_user_id: str
    state_concurred_by_user_id: Optional[str]
    federal_participation_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    project_id: str
    auditor_user_id: str
    status: str
    findings_text: Optional[str]
    ineligible_amount_cents: Optional[int]
    findings_issued_at: Optional[str]
    final_eligible_federal_share_cents: Optional[int]
    repayment_due_cents: Optional[int]
    repaid_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int

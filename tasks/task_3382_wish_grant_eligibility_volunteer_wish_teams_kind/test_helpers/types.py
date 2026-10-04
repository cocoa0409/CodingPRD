"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the common bookkeeping spine
(id, created_at, updated_at, version), so every TypedDict below
includes those four fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (X-User-Role values, spelled exactly as the API expects them)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    NATIONAL_ADMIN = "NationalAdmin"
    REFERRAL_SOURCE = "ReferralSource"
    MEDICAL_PROVIDER = "MedicalProvider"
    ELIGIBILITY_REVIEWER = "EligibilityReviewer"
    VOLUNTEER = "Volunteer"
    WISH_COORDINATOR = "WishCoordinator"
    IN_KIND_OFFICER = "InKindOfficer"
    CHAPTER_DIRECTOR = "ChapterDirector"
    NATIONAL_DIRECTOR = "NationalDirector"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ChapterPosture(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    TRAINED = "TRAINED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReferralSourceType(str, Enum):
    FAMILY = "FAMILY"
    MEDICAL_PROFESSIONAL = "MEDICAL_PROFESSIONAL"
    SELF = "SELF"


class ReferralStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class QualifyingCondition(str, Enum):
    ONCOLOGY = "ONCOLOGY"
    CARDIAC = "CARDIAC"
    NEUROLOGIC = "NEUROLOGIC"
    GENETIC = "GENETIC"
    OTHER_PROGRESSIVE = "OTHER_PROGRESSIVE"
    NON_QUALIFYING = "NON_QUALIFYING"


class DetermineDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class WishType(str, Enum):
    TRAVEL = "TRAVEL"
    MEET_PERSON = "MEET_PERSON"
    RECEIVE_ITEM = "RECEIVE_ITEM"
    BE_SOMETHING = "BE_SOMETHING"


class WishUrgency(str, Enum):
    STANDARD = "STANDARD"
    RAPID = "RAPID"


class WishStatus(str, Enum):
    CREATED = "CREATED"
    DETERMINATION_PENDING = "DETERMINATION_PENDING"
    DETERMINED = "DETERMINED"
    PLANNING = "PLANNING"
    PLAN_APPROVED = "PLAN_APPROVED"
    READY_TO_SCHEDULE = "READY_TO_SCHEDULE"
    SCHEDULED = "SCHEDULED"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    GRANTED = "GRANTED"


class HoldReturnState(str, Enum):
    PLAN_APPROVED = "PLAN_APPROVED"
    READY_TO_SCHEDULE = "READY_TO_SCHEDULE"


class WishTeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISBANDED = "DISBANDED"
    COMPLETED = "COMPLETED"


class VisitMethod(str, Enum):
    PLAY_BASED = "PLAY_BASED"
    DRAWING = "DRAWING"
    INTERVIEW = "INTERVIEW"


class WishVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VisitOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class DonationCategory(str, Enum):
    AIRLINE = "AIRLINE"
    RESORT = "RESORT"
    RETAILER = "RETAILER"
    SPONSOR = "SPONSOR"


class ValuationMethod(str, Enum):
    RETAIL_BASIS = "RETAIL_BASIS"
    PARTNER_DECLARED = "PARTNER_DECLARED"


class DonationOfferStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULLY_RESERVED = "FULLY_RESERVED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class FulfillmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class PlanLineItemStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ClearanceDecision(str, Enum):
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class WishEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class TreatmentWindow(TypedDict):
    start_date: str  # YYYY-MM-DD, closed-interval start
    end_date: str    # YYYY-MM-DD, closed-interval end (>= start_date)


class Chapter(TypedDict):
    id: str
    name: str
    territory_zip_prefixes: List[str]
    fiscal_year_budget_cents: int
    target_avg_cost_per_wish_cents: int
    committed_cost_cents: int
    granted_wish_count: int
    granted_cost_total_cents: int
    granted_cash_total_cents: int
    avg_cost_blended_cents: int
    avg_cost_cash_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    chapter_id: str
    full_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    full_name: str
    normalized_full_name: str
    date_of_birth: str
    zip_code: str
    parent_email: str
    diagnosis_summary: str
    chapter_id: str
    treatment_windows: List[TreatmentWindow]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    child_id: str
    source_type: str
    prognosis_months: Optional[int]
    status: str
    qualifying_condition: Optional[str]
    certification_note: Optional[str]
    certified_at: Optional[str]
    age_months_at_intake: int
    denial_reason: Optional[str]
    determined_at: Optional[str]
    wish_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Wish(TypedDict):
    id: str
    child_id: str
    chapter_id: str
    referral_id: str
    wish_type: Optional[str]
    urgency: str
    status: str
    true_wish_description: Optional[str]
    determined_at: Optional[str]
    hold_return_state: Optional[str]
    granted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WishTeam(TypedDict):
    id: str
    wish_id: str
    lead_volunteer_id: str
    second_volunteer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WishVisit(TypedDict):
    id: str
    wish_team_id: str
    scheduled_start: str
    scheduled_end: str
    visit_method: str
    status: str
    captured_true_wish: Optional[str]
    captured_wish_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonationOffer(TypedDict):
    id: str
    partner_name: str
    category: str
    valuation_method: str
    description: str
    quantity_total: int
    quantity_reserved: int
    quantity_available: int
    unit_retail_cents: int
    partner_declared_unit_cents: Optional[int]
    fmv_unit_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentPlan(TypedDict):
    id: str
    wish_id: str
    cash_cost_cents: int
    notes: Optional[str]
    in_kind_value_cents: int
    total_cost_cents: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    escalation_required: bool
    created_at: str
    updated_at: str
    version: int


class PlanLineItem(TypedDict):
    id: str
    plan_id: str
    donation_offer_id: str
    quantity: int
    line_fmv_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalClearance(TypedDict):
    id: str
    wish_id: str
    status: str
    accommodations: List[str]
    valid_until: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WishEvent(TypedDict):
    id: str
    wish_id: str
    event_start_date: str
    event_end_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int

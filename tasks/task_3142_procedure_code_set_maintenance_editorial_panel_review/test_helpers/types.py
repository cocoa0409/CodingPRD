"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    EDITORIAL_STAFF = "EditorialStaff"
    EDITORIAL_PANEL_CHAIR = "EditorialPanelChair"
    COMMITTEE_REVIEWER = "CommitteeReviewer"
    LICENSING_OFFICER = "LicensingOfficer"
    LICENSEE = "Licensee"
    CHANGE_APPLICANT = "ChangeApplicant"


class CodeChangeReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    WITHDRAWN = "WITHDRAWN"
    POSTED_FOR_COMMENT = "POSTED_FOR_COMMENT"
    ADMIN_REVIEW = "ADMIN_REVIEW"
    AGENDA_SET = "AGENDA_SET"
    PANEL_REVIEW = "PANEL_REVIEW"
    REFERRED = "REFERRED"
    DETERMINED = "DETERMINED"


class CodeChangeDetermination(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REFERRED_TO_JUNE_MINUTES = "REFERRED_TO_JUNE_MINUTES"
    REJECTED = "REJECTED"
    TABLED = "TABLED"
    WITHDRAWN = "WITHDRAWN"


class AdministrativeReviewStatus(str, Enum):
    UNDER_ADMIN_REVIEW = "UNDER_ADMIN_REVIEW"
    ADMIN_COMPLETE = "ADMIN_COMPLETE"
    ADMIN_RETURNED = "ADMIN_RETURNED"


class PostingState(str, Enum):
    NOT_POSTED = "NOT_POSTED"
    POSTED = "POSTED"
    COMMENT_OPEN = "COMMENT_OPEN"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PUBLIC_COMMENT_OPEN = "PUBLIC_COMMENT_OPEN"
    OPEN = "OPEN"
    RECESSED = "RECESSED"
    CLOSED = "CLOSED"


class AgendaStatus(str, Enum):
    UNSET = "UNSET"
    SET = "SET"
    ADDENDUM_OPEN = "ADDENDUM_OPEN"


class ReleaseCycleStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RELEASED = "RELEASED"


class LicensingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TerritoryStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    READY = "READY"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class ErrataStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class ValueStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETAINED = "RETAINED"


class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    RECOMMENDED = "RECOMMENDED"
    DEEMED_NOT_RECOMMENDED = "DEEMED_NOT_RECOMMENDED"


class SpecialtySociety(TypedDict, total=False):
    id: str
    name: str
    specialty_code: str
    voting_seat_count: int
    gpci_work: float
    gpci_pe: float
    gpci_mp: float
    cea_credit_balance: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeApplicant(TypedDict, total=False):
    id: str
    name: str
    applicant_type: str
    society_id: Optional[str]
    is_entity_member: bool
    dues_paid_current: bool
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CodeChange(TypedDict, total=False):
    id: str
    code: str
    change_type: str
    category: str
    code_family: str
    applicant_id: str
    society_id: Optional[str]
    clinical_evidence_tier: str
    evidence_sufficiency_index: float
    procedure_volume_threshold: int
    organ_system_count: int
    descriptor_current: str
    descriptor_proposed: str
    guidelines: str
    parenthetical_instructions: str
    cycles_in_process: int
    administrative_review_status: str
    posting_state: str
    review_status: str
    meeting_id: Optional[str]
    comment_period_open_at: Optional[str]
    comment_period_close_at: Optional[str]
    determination: str
    held_for_full_panel: bool
    cea_credits: float
    verdict_recorded_at: Optional[str]
    cycle_id: Optional[str]
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvisoryCommitteeReview(TypedDict, total=False):
    id: str
    change_id: str
    committee_name: str
    recommendation: str
    quorum_met: bool
    yes_votes: int
    no_votes: int
    vote_percent: float
    decision: str
    review_status: str
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EditorialPanelMeeting(TypedDict, total=False):
    id: str
    meeting_code: str
    meeting_month: str
    meeting_status: str
    agenda_status: str
    quorum_present: bool
    citation_mode: bool
    starts_at: str
    ends_at: str
    public_comment_open_at: Optional[str]
    public_comment_close_at: Optional[str]
    weighted_yes: float
    weighted_no: float
    weighted_abstain: float
    conducted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict, total=False):
    id: str
    change_id: str
    commenter_id: str
    commenter_type: str
    citation_submitted: bool
    body: str
    posted_at: str
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EditorialVote(TypedDict, total=False):
    id: str
    change_id: str
    meeting_id: str
    society_id: str
    vote: str
    votes_carried: float
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class RUCValueRecommendation(TypedDict, total=False):
    id: str
    code: str
    code_value_id: Optional[str]
    work_rvu: float
    facility_pe_rvu: float
    nonfacility_pe_rvu: float
    mp_rvu: float
    survey_median_minutes: float
    specialty_id: Optional[str]
    conversion_factor_tier: str
    status: str
    recommendation_status: str
    recommended_work_rvu: float
    forward_status: str
    payability_status: str
    effective_date: Optional[str]
    vote_percent: float
    created_at: str
    updated_at: str
    version: int


class CodeValue(TypedDict, total=False):
    id: str
    code: str
    change_id: Optional[str]
    release_id: Optional[str]
    work_rvu: float
    facility_pe_rvu: float
    nonfacility_pe_rvu: float
    mp_rvu: float
    conversion_factor: float
    specialty_id: str
    rounding_variant: str
    facility_payment_cents: int
    nonfacility_payment_cents: int
    component_round_total_cents: int
    aggregate_round_total_cents: int
    dollar_split_shortfall_cents: int
    release_month: int
    effective_date: Optional[str]
    value_status: str
    superseded_by_code_value_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ErrataNotice(TypedDict, total=False):
    id: str
    code_value_id: str
    errata_effective_date: str
    prior_facility_payment_cents: int
    corrected_facility_payment_cents: int
    proration_numerator_days: int
    proration_denominator_days: int
    reason: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewErratum(TypedDict, total=False):
    id: str
    original_notice_id: str
    review_outcome: str
    corrected_proration_ratio: float
    applied_status: str
    review_status: str
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseCycle(TypedDict, total=False):
    id: str
    year: int
    comment_open: str
    comment_close: str
    addendum_comment_close: str
    meeting_ids: List[str]
    code_set_capacity: int
    submission_count: int
    editorial_reserved_codes: int
    additions_pool_codes: int
    catiii_pool_codes: int
    discretionary_codes: int
    budget_gate_status: str
    single_floor_budgeting: bool
    released_at: Optional[str]
    errata_deadline: str
    cycle_status: str
    effective_date: str
    released_code_values: List[str]
    created_at: str
    updated_at: str
    version: int


class LicensingAgreement(TypedDict, total=False):
    id: str
    licensee_type: str
    licensee_name: str
    payer_revenue_tier: Optional[str]
    vendor_worldwide: bool
    expected_users: int
    sales_unit_count: int
    royalty_fee_cents: int
    fee_threshold_gate_status: str
    base_fee_cents: int
    territory_id: Optional[str]
    distribution_scope: str
    ancillary_publication_codes: List[str]
    agreement_status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionTerritory(TypedDict, total=False):
    id: str
    territory_code: str
    method: str
    edi_payer_network: bool
    metadata_schema_version: str
    can_license: bool
    distribution_channel: str
    site_exception: bool
    transaction_set_required: bool
    reserved_range: Optional[dict]
    territory_status: str
    reserved_at: Optional[str]
    activation_details: dict
    created_at: str
    updated_at: str
    version: int


class ContentDeliveryOrder(TypedDict, total=False):
    id: str
    license_id: str
    distribution_channel: str
    format_params: dict
    payer_identifier: str
    delivery_status: str
    reserved_at: Optional[str]
    ready_at: Optional[str]
    released_at: Optional[str]
    activation_mode: str
    created_at: str
    updated_at: str
    version: int


class CodingEducationActivity(TypedDict, total=False):
    id: str
    licensee_id: str
    activity_code: str
    clock_hours: float
    assistant_targeted: bool
    cea_credits_awarded: float
    cea_credits_rounded: float
    activity_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterpretationRequest(TypedDict, total=False):
    id: str
    requesting_licensee_id: str
    code: str
    question: str
    response_status: str
    entitlement_status: str
    answered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
"""Domain types: status enums, role enum and entity shapes described by the PRD."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROPONENT = "Proponent"
    WILDLIFE_AGENCY = "WildlifeAgency"
    AUDITOR = "Auditor"
    ANONYMOUS = "Anonymous"


class ListingStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    PROPOSED = "PROPOSED"
    THREATENED = "THREATENED"
    ENDANGERED = "ENDANGERED"


class TakeAuthorizationUnit(str, Enum):
    INDIVIDUALS = "INDIVIDUALS"
    ACRES = "ACRES"
    NESTS = "NESTS"


class DesignationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FINAL = "FINAL"


class ProjectActionStatus(str, Enum):
    SCREENING = "SCREENING"
    CLEARED_NO_EFFECT = "CLEARED_NO_EFFECT"
    INFORMAL_CONSULTATION = "INFORMAL_CONSULTATION"
    FORMAL_CONSULTATION = "FORMAL_CONSULTATION"
    CONSULTATION_CONCLUDED = "CONSULTATION_CONCLUDED"
    HCP_DEVELOPMENT = "HCP_DEVELOPMENT"
    PERMITTED = "PERMITTED"
    REINITIATION_PENDING = "REINITIATION_PENDING"


class EffectDetermination(str, Enum):
    PENDING = "PENDING"
    NO_EFFECT = "NO_EFFECT"
    NLAA = "NLAA"
    LAA = "LAA"


class ActionType(str, Enum):
    FEDERAL_FUNDED = "FEDERAL_FUNDED"
    FEDERAL_PERMITTED = "FEDERAL_PERMITTED"
    NON_FEDERAL = "NON_FEDERAL"


class ReinitiationReason(str, Enum):
    NONE = "NONE"
    SPECIES_UPLISTED = "SPECIES_UPLISTED"
    TAKE_EXCEEDANCE = "TAKE_EXCEEDANCE"


class SurveyMethod(str, Enum):
    DATABASE_QUERY = "DATABASE_QUERY"
    FIELD_SURVEY = "FIELD_SURVEY"


class DetectionResult(str, Enum):
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class PresenceStatus(str, Enum):
    PRESENT = "PRESENT"
    PRESUMED_PRESENT = "PRESUMED_PRESENT"
    PRESUMED_ABSENT = "PRESUMED_ABSENT"
    ABSENT = "ABSENT"


class ConsultationType(str, Enum):
    INFORMAL = "INFORMAL"
    FORMAL = "FORMAL"


class ConsultationStatus(str, Enum):
    DRAFT_BA = "DRAFT_BA"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    CONCLUDED_CONCURRENCE = "CONCLUDED_CONCURRENCE"
    OPINION_ISSUED = "OPINION_ISSUED"
    REINITIATION_REQUIRED = "REINITIATION_REQUIRED"


class OpinionConclusion(str, Enum):
    NO_JEOPARDY = "NO_JEOPARDY"
    JEOPARDY = "JEOPARDY"
    JEOPARDY_WITH_RPA = "JEOPARDY_WITH_RPA"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IMPLEMENTING = "IMPLEMENTING"
    SUSPENDED_IMPLEMENTATION = "SUSPENDED_IMPLEMENTATION"
    CLOSED = "CLOSED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_ASSURED = "PARTIALLY_ASSURED"
    FULLY_ASSURED = "FULLY_ASSURED"


class MitigationMechanism(str, Enum):
    CONSERVATION_BANK_CREDIT = "CONSERVATION_BANK_CREDIT"
    IN_LIEU_FEE = "IN_LIEU_FEE"
    PERMITTEE_RESPONSIBLE = "PERMITTEE_RESPONSIBLE"


class CommitmentStatus(str, Enum):
    RESERVED = "RESERVED"
    SECURED = "SECURED"
    RELEASED = "RELEASED"


class InstrumentType(str, Enum):
    IRREVOCABLE_LETTER_OF_CREDIT = "IRREVOCABLE_LETTER_OF_CREDIT"
    ESCROW_ACCOUNT = "ESCROW_ACCOUNT"
    ENDOWMENT_TRANSFER = "ENDOWMENT_TRANSFER"
    PERFORMANCE_BOND = "PERFORMANCE_BOND"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AdjudicationOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class PlanDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"


class CircumstanceType(str, Enum):
    CHANGED = "CHANGED"
    UNFORESEEN = "UNFORESEEN"


class CircumstanceEventStatus(str, Enum):
    REPORTED = "REPORTED"
    RESPONSE_REQUIRED = "RESPONSE_REQUIRED"
    RESPONDED = "RESPONDED"
    ASSURANCES_INVOKED = "ASSURANCES_INVOKED"


class ComplianceVariant(str, Enum):
    LIFETIME = "LIFETIME"
    ROLLING_12_MONTH = "ROLLING_12_MONTH"


class Species(TypedDict):
    id: str
    scientific_name: str
    common_name: str
    listing_status: str
    critical_habitat_designated: bool
    take_authorization_unit: str
    take_density_per_acre: float
    recovery_unit_population: int
    survey_season_start_month: int
    survey_season_end_month: int
    listing_change_count: int
    last_listing_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriticalHabitatUnit(TypedDict):
    id: str
    species_id: str
    unit_code: str
    acres: float
    county_code: str
    designation_status: str
    primary_constituent_elements: List[str]
    created_at: str
    updated_at: str
    version: int


class Proponent(TypedDict):
    id: str
    org_name: str
    contact_email: str
    is_federal_agency: bool
    compliance_standing_score: float
    compliance_variant_applied: str
    open_reinitiation_count: int
    created_at: str
    updated_at: str
    version: int


class ProjectAction(TypedDict):
    id: str
    proponent_id: str
    action_name: str
    action_type: str
    footprint_acres: float
    county_code: str
    construction_start_date: str
    construction_end_date: str
    status: str
    effect_determination: str
    total_overlap_acres: float
    overlap_pct: float
    active_consultation_id: Optional[str]
    reinitiation_reason: str
    created_at: str
    updated_at: str
    version: int


class PresenceDetermination(TypedDict):
    id: str
    project_action_id: str
    species_id: str
    critical_habitat_unit_id: Optional[str]
    method: str
    detection_result: str
    habitat_overlap_acres: float
    survey_window_start: Optional[str]
    survey_window_end: Optional[str]
    survey_in_season: bool
    presence_status: str
    requires_reevaluation: bool
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict):
    id: str
    project_action_id: str
    consultation_type: str
    status: str
    ba_narrative: Optional[str]
    ba_revision_number: int
    ba_submitted_at: Optional[str]
    clock_started_at: str
    statutory_days: int
    tolled_days: int
    deadline_at: str
    info_request_count: int
    info_requested_at: Optional[str]
    reinitiation_count: int
    reinitiation_triggered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: carries only id and created_at beyond its own fields.
class BiologicalOpinion(TypedDict):
    id: str
    consultation_id: str
    primary_species_scientific_name: str
    primary_species_listing_status: str
    exposed_acres: float
    take_unit: str
    authorized_take_units: float
    jeopardy_fraction: float
    rpa_required: bool
    rpa_description: Optional[str]
    conclusion: str
    reinitiation_trigger_units: float
    issued_by_user_id: str
    issued_at: str
    issued_late: bool
    created_at: str


class ConservationBank(TypedDict):
    id: str
    bank_name: str
    covered_species_id: str
    service_area_county_codes: List[str]
    credit_price_cents: int
    credits_total_minted: float
    credits_available: float
    credits_reserved: float
    credits_transferred: float
    created_at: str
    updated_at: str
    version: int


class HabitatConservationPlan(TypedDict):
    id: str
    plan_name: str
    covered_acres: float
    permit_term_years: int
    plan_status: str
    funding_status: str
    preliminary_mitigation_units: float
    final_mitigation_units: Optional[float]
    mitigation_delta_units: Optional[float]
    secured_mitigation_units: float
    endowment_base_cents: int
    changed_circumstance_reserve_cents: int
    endowment_required_cents: int
    endowment_secured_cents: int
    reserve_drawn_cents: int
    reserve_remaining_cents: int
    funded_ratio: float
    approved_by_user_id: Optional[str]
    assurance_review_required: bool
    created_at: str
    updated_at: str
    version: int


class MitigationCommitment(TypedDict):
    id: str
    conservation_bank_id: Optional[str]
    mechanism: str
    units: float
    status: str
    base_fee_cents: int
    admin_fee_pct_applied: float
    admin_fee_cents: int
    total_cost_cents: int
    endowment_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


class IncidentalTakePermit(TypedDict):
    id: str
    hcp_id: str
    permit_number: str
    status: str
    term_start: str
    term_end: str
    implementing_agreement_reference: str
    take_unit: str
    authorized_take_units: float
    reinitiation_trigger_units: float
    take_consumed_units: float
    take_remaining_units: float
    suspension_count: int
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class MonitoringReport(TypedDict):
    id: str
    permit_id: str
    period_start: str
    period_end: str
    take_units_reported: float
    mitigation_units_verified: float
    status: str
    submitted_at: str
    due_at: str
    is_late: bool
    adjudicated_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangedCircumstanceEvent(TypedDict):
    id: str
    hcp_id: str
    circumstance_type: str
    description: str
    response_cost_cents: int
    status: str
    reported_at: str
    reserve_draw_cents: int
    required_additional_cents: int
    permittee_borne_cents: int
    agency_borne_cents: int
    assurances_invoked: bool
    created_at: str
    updated_at: str
    version: int

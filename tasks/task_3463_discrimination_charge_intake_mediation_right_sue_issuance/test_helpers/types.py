"""Domain types: entity TypedDicts, status enums, role enum.

Enum values mirror the PRD's declared vocabularies (sections 2.1 and 3.x).
TypedDicts list the fields a well-formed API response carries for each
resource. DisclosureRecord is the sole append-only resource: it carries only
id and created_at — no updated_at, no version (PRD section 2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1: exactly nine roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_OFFICER = "IntakeOfficer"
    CHARGING_PARTY = "ChargingParty"
    RESPONDENT_REP = "RespondentRep"
    MEDIATOR = "Mediator"
    INVESTIGATOR = "Investigator"
    DIRECTOR = "Director"
    COMMISSIONER = "Commissioner"
    STATE_AGENCY_OFFICER = "StateAgencyOfficer"


# ---------------------------------------------------------------------------
# Shared vocabularies
# ---------------------------------------------------------------------------
class BasisCode(str, Enum):
    RACE = "RACE"
    COLOR = "COLOR"
    RELIGION = "RELIGION"
    SEX = "SEX"
    NATIONAL_ORIGIN = "NATIONAL_ORIGIN"
    AGE = "AGE"
    DISABILITY = "DISABILITY"
    GENETIC_INFO = "GENETIC_INFO"
    RETALIATION = "RETALIATION"


class SizeBand(str, Enum):
    UNDER_15 = "UNDER_15"
    FROM_15_TO_19 = "FROM_15_TO_19"
    FROM_20_TO_100 = "FROM_20_TO_100"
    FROM_101_TO_200 = "FROM_101_TO_200"
    FROM_201_TO_500 = "FROM_201_TO_500"
    OVER_500 = "OVER_500"


class WorkSharingPolicy(str, Enum):
    EEOC_RETAINS_ALL = "EEOC_RETAINS_ALL"
    DUAL_FILE_DEFAULT = "DUAL_FILE_DEFAULT"
    FEPA_EXCLUSIVE = "FEPA_EXCLUSIVE"


class ChargeStatus(str, Enum):
    DOCKETED = "DOCKETED"
    IN_MEDIATION = "IN_MEDIATION"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    DETERMINATION_REVIEW = "DETERMINATION_REVIEW"
    CONCILIATION = "CONCILIATION"
    DELEGATED_TO_FEPA = "DELEGATED_TO_FEPA"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    CLOSED_NO_CAUSE = "CLOSED_NO_CAUSE"
    LITIGATION_REFERRED = "LITIGATION_REFERRED"
    RTS_ISSUED = "RTS_ISSUED"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"
    DISMISSED_NO_JURISDICTION = "DISMISSED_NO_JURISDICTION"
    WITHDRAWN = "WITHDRAWN"


class DisclosureHold(str, Enum):
    NONE = "NONE"
    SEALED = "SEALED"


class JurisdictionOutcome(str, Enum):
    TIMELY_CONFIRMED = "TIMELY_CONFIRMED"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"
    DISMISSED_NO_JURISDICTION = "DISMISSED_NO_JURISDICTION"


class InvestigationOwner(str, Enum):
    EEOC = "EEOC"
    FEPA = "FEPA"
    NONE = "NONE"


class SettledVia(str, Enum):
    MEDIATION = "MEDIATION"
    CONCILIATION = "CONCILIATION"


class PartyResponse(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MediationCaseStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    IMPASSE = "IMPASSE"
    DECLINED = "DECLINED"
    VACATED = "VACATED"


class MediationOutcome(str, Enum):
    SETTLED = "SETTLED"
    IMPASSE = "IMPASSE"


class MediationSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class InvestigationCaseStatus(str, Enum):
    OPEN = "OPEN"
    GATHERING = "GATHERING"
    SUSPENDED_MEDIATION = "SUSPENDED_MEDIATION"
    CLOSED = "CLOSED"


class EvidenceRequestType(str, Enum):
    POSITION_STATEMENT = "POSITION_STATEMENT"
    RFI = "RFI"
    DOCUMENT_DEMAND = "DOCUMENT_DEMAND"


class EvidenceRequestStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    RESPONDED = "RESPONDED"
    WAIVED = "WAIVED"


class DeterminationOutcome(str, Enum):
    CAUSE = "CAUSE"
    NO_CAUSE = "NO_CAUSE"
    UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class ConciliationStatus(str, Enum):
    INITIATED = "INITIATED"
    OFFER_TABLED = "OFFER_TABLED"
    COUNTERED = "COUNTERED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class OfferSide(str, Enum):
    COMMISSION = "COMMISSION"
    RESPONDENT = "RESPONDENT"


class ValuationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class IssuanceBasis(str, Enum):
    ELAPSED_180_DAYS = "ELAPSED_180_DAYS"
    DIRECTOR_DISCRETION = "DIRECTOR_DISCRETION"
    AUTO_ON_DISMISSAL = "AUTO_ON_DISMISSAL"


class RightToSueStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"


class SystemicCaseStatus(str, Enum):
    OPENED = "OPENED"
    EXPANDING = "EXPANDING"
    CONSOLIDATED = "CONSOLIDATED"
    RESOLVED = "RESOLVED"


class LegalBasis(str, Enum):
    COURT_ORDER = "COURT_ORDER"
    FEPA_WORK_SHARE = "FEPA_WORK_SHARE"
    PARTY_CONSENT = "PARTY_CONSENT"
    INTERNAL_ACCESS = "INTERNAL_ACCESS"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class Complainant(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    legal_name: str
    state_code: str
    employee_count_current: int
    size_band: str
    created_at: str
    updated_at: str
    version: int


class DeferralAgency(TypedDict):
    id: str
    state_code: str
    agency_name: str
    filing_deadline_days: int
    work_sharing_policy: str
    covers_age: bool
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    complainant_id: str
    employer_id: str
    deferral_agency_id: Optional[str]
    basis_codes: List[str]
    covered_bases: List[str]
    incident_date: str
    harm_description: str
    employee_count_at_incident: int
    received_date: str
    case_status: str
    disclosure_hold: str
    jurisdiction_outcome: str
    filing_deadline_date: str
    investigation_owner: str
    dual_filed: bool
    investigation_case_id: Optional[str]
    priority_escalated: bool
    settled_amount_cents: int
    settled_via: Optional[str]
    settled_at: Optional[str]
    systemic_case_id: Optional[str]
    days_elapsed_since_filing: int
    created_at: str
    updated_at: str
    version: int


class MediationCase(TypedDict):
    id: str
    charge_id: str
    round_number: int
    complainant_response: str
    respondent_response: str
    status: str
    settlement_amount_cents: Optional[int]
    concluded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict):
    id: str
    mediation_case_id: str
    mediator_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestigationCase(TypedDict):
    id: str
    charge_id: str
    assigned_investigator_id: Optional[str]
    status: str
    open_request_count: int
    overdue_request_count: int
    priority_score: int
    created_at: str
    updated_at: str
    version: int


class EvidenceRequest(TypedDict):
    id: str
    investigation_case_id: str
    request_type: str
    issued_date: str
    due_date: str
    status: str
    response_text: Optional[str]
    responded_late: bool
    created_at: str
    updated_at: str
    version: int


class WitnessInterview(TypedDict):
    id: str
    investigation_case_id: str
    investigator_user_id: str
    witness_name: str
    interview_start: str
    interview_end: str
    summary: str
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict):
    id: str
    investigation_case_id: str
    outcome: str
    rationale: str
    back_pay_cents: Optional[int]
    front_pay_cents: Optional[int]
    compensatory_damages_cents: Optional[int]
    punitive_damages_cents: Optional[int]
    harm_start_date: Optional[str]
    status: str
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConciliationProcess(TypedDict):
    id: str
    charge_id: str
    origin_determination_id: str
    status: str
    current_offer_cents: Optional[int]
    last_offer_by: Optional[str]
    rounds_count: int
    created_at: str
    updated_at: str
    version: int


class RemedyPackage(TypedDict):
    id: str
    conciliation_process_id: str
    valuation_variant: str
    back_pay_cents: int
    front_pay_cents: int
    compensatory_damages_cents: int
    punitive_damages_cents: int
    harm_start_date: str
    band_used: str
    projection_date: str
    interest_days: int
    back_pay_interest_cents: int
    front_pay_interest_cents: int
    capped_nonpecuniary_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class RightToSueNotice(TypedDict):
    id: str
    charge_id: str
    issuance_basis: str
    requested_by_role: str
    issued_date: str
    court_filing_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SystemicCase(TypedDict):
    id: str
    title: str
    basis_focus: List[str]
    commissioner_user_id: str
    status: str
    linked_charge_count: int
    created_at: str
    updated_at: str
    version: int


class DisclosureRecord(TypedDict):
    """Append-only audit row: only id + created_at (PRD section 2.5)."""
    id: str
    charge_id: str
    accessor_role: str
    accessor_user_id: str
    legal_basis: str
    target_description: Optional[str]
    disclosed_at: str
    created_at: str

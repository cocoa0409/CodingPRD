"""Domain types for the Motor Vehicle Dealer Board API.

Status enums, role enum and entity TypedDicts. Records that the PRD says
expose only `id` and `created_at` (the two append-only evidence logs)
deliberately omit `updated_at` and `version`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DEALER = "Dealer"
    MANUFACTURER = "Manufacturer"
    LICENSING_ANALYST = "LicensingAnalyst"
    HEARING_CLERK = "HearingClerk"
    COMPLAINT_INVESTIGATOR = "ComplaintInvestigator"
    BOARD_ADMIN = "BoardAdmin"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class DealerType(str, Enum):
    NEW_MOTOR_VEHICLE = "NEW_MOTOR_VEHICLE"
    USED_ONLY = "USED_ONLY"


class CountyTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class DealerLicenseStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CANCELLED = "CANCELLED"


class DealerFranchiseStatus(str, Enum):
    NONE = "NONE"
    FRANCHISED = "FRANCHISED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    DISCIPLINARY_POINTS = "DISCIPLINARY_POINTS"
    RESTITUTION_DELINQUENT = "RESTITUTION_DELINQUENT"


class ApplicationType(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"
    CHANGE_OF_OWNERSHIP = "CHANGE_OF_OWNERSHIP"
    RELOCATION = "RELOCATION"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOID_SPONSOR_CANCELLED = "VOID_SPONSOR_CANCELLED"


class ZoningCertificateStatus(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    PENDING = "PENDING"
    DENIED = "DENIED"


class DeficiencyCode(str, Enum):
    FACILITY_TOO_SMALL = "FACILITY_TOO_SMALL"
    DISPLAY_SPACES_INSUFFICIENT = "DISPLAY_SPACES_INSUFFICIENT"
    SERVICE_BAYS_INSUFFICIENT = "SERVICE_BAYS_INSUFFICIENT"
    BOND_INSUFFICIENT = "BOND_INSUFFICIENT"
    INSURANCE_INSUFFICIENT = "INSURANCE_INSUFFICIENT"
    ZONING_NOT_APPROVED = "ZONING_NOT_APPROVED"


class SalespersonLicenseStatus(str, Enum):
    PENDING = "PENDING"
    LICENSED = "LICENSED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    DENIED = "DENIED"
    SUSPENDED_BY_SPONSOR = "SUSPENDED_BY_SPONSOR"
    EXPIRED = "EXPIRED"


class DisciplineStatus(str, Enum):
    CLEAR = "CLEAR"
    PROBATION = "PROBATION"
    SUSPENDED_DISCIPLINARY = "SUSPENDED_DISCIPLINARY"
    REINSTATED = "REINSTATED"


class FilingType(str, Enum):
    TERMINATION = "TERMINATION"
    RELOCATION = "RELOCATION"
    ADDITIONAL_POINT = "ADDITIONAL_POINT"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICE_SERVED = "NOTICE_SERVED"
    PROTEST_PENDING = "PROTEST_PENDING"
    PROTEST_RESOLVED = "PROTEST_RESOLVED"
    EFFECTIVE = "EFFECTIVE"
    BARRED = "BARRED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    SCHEDULED = "SCHEDULED"
    HEARD = "HEARD"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED = "DISMISSED"


class GroundsCode(str, Enum):
    INADEQUATE_REPRESENTATION = "INADEQUATE_REPRESENTATION"
    NO_GOOD_CAUSE_FOR_TERMINATION = "NO_GOOD_CAUSE_FOR_TERMINATION"
    MARKET_ENCROACHMENT = "MARKET_ENCROACHMENT"


class SubmittingParty(str, Enum):
    PROTESTANT = "PROTESTANT"
    MANUFACTURER = "MANUFACTURER"


class StudyBasis(str, Enum):
    STATEWIDE_AVERAGE = "STATEWIDE_AVERAGE"
    COMPARABLE_MARKET = "COMPARABLE_MARKET"


class AcceptanceStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    LATE_ACCEPTED = "LATE_ACCEPTED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISMISSED_MOOT = "DISMISSED_MOOT"


class RepairType(str, Enum):
    CUSTOMER_PAID = "CUSTOMER_PAID"
    WARRANTY = "WARRANTY"
    INTERNAL = "INTERNAL"


class ManufacturerResponseType(str, Enum):
    ACCEPT = "ACCEPT"
    REBUT = "REBUT"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SANCTIONED = "SANCTIONED"
    CLOSED_SATISFIED = "CLOSED_SATISFIED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class AllegationCode(str, Enum):
    ODOMETER_MISREPRESENTATION = "ODOMETER_MISREPRESENTATION"
    FAILURE_TO_TRANSFER_TITLE = "FAILURE_TO_TRANSFER_TITLE"
    ADVERTISING_VIOLATION = "ADVERTISING_VIOLATION"
    DEPOSIT_RETENTION = "DEPOSIT_RETENTION"
    UNLICENSED_SALESPERSON = "UNLICENSED_SALESPERSON"


class SanctionType(str, Enum):
    WARNING = "WARNING"
    CIVIL_PENALTY = "CIVIL_PENALTY"
    PROBATION = "PROBATION"
    SUSPENSION_RECOMMENDED = "SUSPENSION_RECOMMENDED"


class Manufacturer(TypedDict):
    id: str
    legal_name: str
    line_make: str
    home_office_state: str
    posted_warranty_labor_rate_cents: int
    state_registration_status: str
    open_dispute_count: int
    active_filing_count: int
    created_at: str
    updated_at: str
    version: int


class HearingRoom(TypedDict):
    id: str
    room_code: str
    seating_capacity: int
    max_hearings_per_day: int
    buffer_minutes: int
    booked_hearing_count: int
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    legal_name: str
    dealer_type: str
    county_tier: str
    site_x_km: float
    site_y_km: float
    line_make: str
    license_status: str
    franchise_status: str
    suspension_reason: str
    license_effective_on: Optional[str]
    license_expires_on: Optional[str]
    disciplinary_points: int
    restitution_outstanding_cents: int
    licensed_salesperson_count: int
    approved_warranty_labor_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict):
    id: str
    dealer_id: str
    application_type: str
    status: str
    facility_sqft: int
    display_spaces: int
    service_bays: int
    bond_amount_cents: int
    insurance_liability_cents: int
    zoning_certificate_status: str
    line_make_count: int
    requested_term_start_on: Optional[str]
    relocation_site_x_km: Optional[float]
    relocation_site_y_km: Optional[float]
    new_owner_name: Optional[str]
    deficiency_codes: List[str]
    deficiency_count: int
    deficiency_note: Optional[str]
    resubmission_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decision_outcome: Optional[str]
    denial_reason_code: Optional[str]
    fee_quoted_cents: Optional[int]
    fee_total_cents: Optional[int]
    fee_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Salesperson(TypedDict):
    id: str
    sponsoring_dealer_id: str
    full_name: str
    disclosed_prior_discipline: bool
    license_status: str
    discipline_status: str
    disciplinary_points: int
    renewal_count: int
    waiver_granted: bool
    license_effective_on: Optional[str]
    license_expires_on: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FranchiseFiling(TypedDict):
    id: str
    manufacturer_id: str
    filing_type: str
    status: str
    proposed_effective_on: str
    affected_dealer_id: Optional[str]
    site_x_km: Optional[float]
    site_y_km: Optional[float]
    termination_cause_code: Optional[str]
    line_make: str
    notice_served_on: Optional[str]
    notice_days_provided: Optional[int]
    protest_window_ends_on: Optional[str]
    amendment_count: int
    active_protest_count: int
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    franchise_filing_id: str
    protestant_dealer_id: str
    grounds_code: str
    status: str
    filed_on: str
    distance_to_site_km: Optional[float]
    hearing_room_id: Optional[str]
    hearing_start_at: Optional[str]
    hearing_end_at: Optional[str]
    hearing_session_count: Optional[int]
    evidence_deadline_at: Optional[str]
    accepted_evidence_pages: int
    late_evidence_count: int
    good_cause_score: Optional[float]
    good_cause_threshold: float
    assessment_total_cents: Optional[int]
    protestant_share_cents: Optional[int]
    manufacturer_share_cents: Optional[int]
    decided_on: Optional[str]
    findings_note: Optional[str]
    appeal_filed_on: Optional[str]
    appellant_party: Optional[str]
    court_docket_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A market study is a tender into a quasi-judicial record: it exposes only
# `id` and `created_at` — no `updated_at`, no `version`.
class MarketStudy(TypedDict):
    id: str
    protest_id: str
    submitted_by_party: str
    basis: str
    total_market_registrations: int
    line_make_registrations: int
    statewide_line_make_share_pct: Optional[float]
    comparable_market_shares_pct: Optional[List[float]]
    permanency_investment_cents: int
    consumer_access_drive_minutes: int
    market_growth_pct: float
    actual_penetration_pct: float
    expected_penetration_pct: float
    shortfall_pts: float
    is_probative: bool
    created_at: str


# An evidence submission is likewise append-only: only `id` and `created_at`.
class EvidenceSubmission(TypedDict):
    id: str
    protest_id: str
    submitting_party: str
    exhibit_label: str
    page_count: int
    leave_granted: bool
    received_at: str
    acceptance_status: str
    is_late: bool
    created_at: str


class RepairOrderLine(TypedDict):
    labor_charge_cents: int
    labor_hours: float
    repair_type: str


class WarrantyRateDispute(TypedDict):
    id: str
    dealer_id: str
    manufacturer_id: str
    status: str
    repair_order_lines: List[RepairOrderLine]
    qualifying_line_count: int
    declared_rate_cents: int
    counter_rate_cents: Optional[int]
    spread_pct: Optional[float]
    manufacturer_response_type: Optional[str]
    excluded_line_indexes: List[int]
    approved_rate_cents: Optional[int]
    effective_on: Optional[str]
    filed_on: str
    decided_on: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsumerComplaint(TypedDict):
    id: str
    dealer_id: str
    salesperson_id: Optional[str]
    complainant_name: str
    allegation_code: str
    alleged_loss_cents: int
    status: str
    investigator_user_id: Optional[str]
    findings_code: Optional[str]
    substantiated: Optional[bool]
    sanction_type: Optional[str]
    points_assessed: int
    civil_penalty_cents: Optional[int]
    restitution_ordered_cents: Optional[int]
    restitution_paid_cents: int
    restitution_due_on: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
